package com.payshift.merchant.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.payshift.merchant.domain.Payment;
import com.payshift.merchant.domain.ProcessedWebhookEvent;
import com.payshift.merchant.repository.PaymentRepository;
import com.payshift.merchant.repository.ProcessedWebhookEventRepository;
import com.stripe.exception.SignatureVerificationException;
import com.stripe.model.Event;
import com.stripe.net.Webhook;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * Webhook signature verification is deterministic cryptography (real Stripe SDK
 * HMAC verification via Webhook.constructEvent), never delegated to the LLM.
 *
 * Event payload fields (id, type) are read from the SDK's typed Event. The nested
 * data.object is read from the raw JSON instead of the SDK's typed data-object
 * deserializer, which returns empty whenever the event's api_version does not
 * exactly match the pinned SDK version -- a real-world webhook gotcha this avoids.
 */
@Service
public class WebhookService {

    private static final Logger log = LoggerFactory.getLogger(WebhookService.class);
    private static final String PROVIDER_ID = "stripe";

    private final PaymentRepository paymentRepository;
    private final ProcessedWebhookEventRepository processedWebhookEventRepository;
    private final OrderFulfillmentService orderFulfillmentService;
    private final String webhookSecret;
    private final ObjectMapper objectMapper = new ObjectMapper();

    public WebhookService(PaymentRepository paymentRepository,
                           ProcessedWebhookEventRepository processedWebhookEventRepository,
                           OrderFulfillmentService orderFulfillmentService,
                           @Value("${payshift.stripe.webhook-secret:whsec_test_placeholder}") String webhookSecret) {
        this.paymentRepository = paymentRepository;
        this.processedWebhookEventRepository = processedWebhookEventRepository;
        this.orderFulfillmentService = orderFulfillmentService;
        this.webhookSecret = webhookSecret;
    }

    public Event verifySignature(String payload, String signatureHeader) {
        try {
            return Webhook.constructEvent(payload, signatureHeader, webhookSecret);
        } catch (SignatureVerificationException e) {
            throw new InvalidWebhookSignatureException("Invalid Stripe webhook signature", e);
        }
    }

    /**
     * Returns true if the event was newly processed, false if it was a duplicate
     * delivery that was skipped. Fulfillment and payment-state updates happen in
     * the same transaction as recording the event id, so a crash mid-handling
     * cannot leave an event marked processed without its side effects applied.
     */
    @Transactional
    public boolean processEvent(Event event, String rawPayload) {
        if (processedWebhookEventRepository.existsByEventId(event.getId())) {
            log.info("Ignoring duplicate webhook delivery for event {}", event.getId());
            return false;
        }

        switch (event.getType()) {
            case "payment_intent.succeeded" -> handlePaymentSucceeded(event, rawPayload);
            case "payment_intent.payment_failed" -> handlePaymentFailed(event, rawPayload);
            default -> log.info("Ignoring unhandled Stripe event type {}", event.getType());
        }

        processedWebhookEventRepository.save(new ProcessedWebhookEvent(event.getId(), PROVIDER_ID));
        return true;
    }

    private void handlePaymentSucceeded(Event event, String rawPayload) {
        String providerPaymentId = extractDataObjectId(rawPayload);
        Payment payment = paymentRepository.findByProviderPaymentId(providerPaymentId)
                .orElseThrow(() -> new PaymentNotFoundException("No local payment for " + providerPaymentId));
        payment.markSucceeded();
        paymentRepository.save(payment);
        orderFulfillmentService.fulfill(payment.getOrderId());
    }

    private void handlePaymentFailed(Event event, String rawPayload) {
        String providerPaymentId = extractDataObjectId(rawPayload);
        Payment payment = paymentRepository.findByProviderPaymentId(providerPaymentId)
                .orElseThrow(() -> new PaymentNotFoundException("No local payment for " + providerPaymentId));
        payment.markFailed();
        paymentRepository.save(payment);
    }

    private String extractDataObjectId(String rawPayload) {
        try {
            JsonNode root = objectMapper.readTree(rawPayload);
            JsonNode idNode = root.path("data").path("object").path("id");
            if (idNode.isMissingNode()) {
                throw new IllegalStateException("Webhook payload is missing data.object.id");
            }
            return idNode.asText();
        } catch (com.fasterxml.jackson.core.JsonProcessingException e) {
            throw new IllegalStateException("Malformed webhook payload", e);
        }
    }
}
