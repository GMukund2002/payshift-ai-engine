package com.shop.orders.payments;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.shop.orders.domain.OrderState;
import com.shop.orders.domain.ProcessedEvent;
import com.shop.orders.domain.ShopOrder;
import com.shop.orders.repository.ProcessedEventRepository;
import com.shop.orders.repository.ShopOrderRepository;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

@Service
public class OrderPaymentService {

    private static final String PROVIDER = "razorpay";

    private final RazorpayGateway razorpay;
    private final WebhookSignatureVerifier verifier;
    private final ShopOrderRepository orders;
    private final ProcessedEventRepository processedEvents;
    private final ObjectMapper json;

    public OrderPaymentService(RazorpayGateway razorpay, WebhookSignatureVerifier verifier,
                               ShopOrderRepository orders, ProcessedEventRepository processedEvents, ObjectMapper json) {
        this.razorpay = razorpay;
        this.verifier = verifier;
        this.orders = orders;
        this.processedEvents = processedEvents;
        this.json = json;
    }

    /** Idempotent per receipt. */
    @Transactional
    public ShopOrder createPayment(String receipt, long amountPaise, String currency) {
        return orders.findByReceipt(receipt).orElseGet(() -> {
            RazorpayGateway.RazorpayOrder order = razorpay.createOrder(receipt, amountPaise, currency);
            return orders.save(new ShopOrder(receipt, amountPaise, currency, PROVIDER, order.id()));
        });
    }

    public ShopOrder getPaymentStatus(Long id) {
        return orders.findById(id).orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND));
    }

    @Transactional
    public ShopOrder refundPayment(Long id) {
        ShopOrder order = getPaymentStatus(id);
        if (order.getState() != OrderState.PAID) {
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY, "Order is not paid: " + order.getState());
        }
        razorpay.refundPayment(order.getProviderPaymentId(), order.getAmountPaise());
        order.markRefunded();
        return orders.save(order);
    }

    /** @return false if this event id was already processed (Razorpay redelivery). */
    @Transactional
    public boolean handleWebhook(String rawBody, String signature, String eventId) {
        if (!verifier.isValid(rawBody, signature)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Invalid webhook signature");
        }
        if (eventId != null && processedEvents.existsById(eventId)) {
            return false;
        }
        JsonNode root;
        try {
            root = json.readTree(rawBody);
        } catch (Exception e) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "Malformed webhook body");
        }
        String event = root.path("event").asText();
        JsonNode payment = root.path("payload").path("payment").path("entity");
        orders.findByProviderOrderId(payment.path("order_id").asText()).ifPresent(order -> {
            switch (event) {
                case "payment.captured" -> order.markPaid(payment.path("id").asText());
                case "payment.failed" -> order.markFailed();
                default -> { }
            }
            orders.save(order);
        });
        if (eventId != null) {
            processedEvents.save(new ProcessedEvent(eventId));
        }
        return true;
    }
}
