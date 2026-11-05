package com.payshift.merchant;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.payshift.merchant.domain.Order;
import com.payshift.merchant.domain.OrderStatus;
import com.payshift.merchant.provider.StripePaymentGateway;
import com.payshift.merchant.repository.OrderRepository;
import com.payshift.merchant.support.StripeWebhookTestSupport;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import java.util.Map;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
class WebhookIntegrationTest {

    private static final String WEBHOOK_SECRET = "whsec_test_placeholder";

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private OrderRepository orderRepository;

    @MockBean
    private StripePaymentGateway stripeGateway;

    private String paymentSucceededPayload(String eventId, String providerPaymentId) throws Exception {
        return objectMapper.writeValueAsString(Map.of(
                "id", eventId,
                "object", "event",
                "api_version", "2024-06-20",
                "created", 1_700_000_000,
                "type", "payment_intent.succeeded",
                "data", Map.of("object", Map.of(
                        "id", providerPaymentId,
                        "object", "payment_intent",
                        "amount", 2000,
                        "currency", "usd",
                        "status", "succeeded"
                ))
        ));
    }

    private String createPaymentAndGetProviderId(String orderRef) throws Exception {
        String piId = "pi_" + UUID.randomUUID();
        when(stripeGateway.createPaymentIntent(any(), any(), any()))
                .thenReturn(new StripePaymentGateway.ProviderPaymentResult(piId, "requires_action", "secret"));
        mockMvc.perform(post("/api/payments")
                .contentType(MediaType.APPLICATION_JSON)
                .content(objectMapper.writeValueAsString(Map.of(
                        "orderReference", orderRef,
                        "amount", "20.00",
                        "currency", "usd",
                        "idempotencyKey", "idem-" + orderRef))));
        return piId;
    }

    @Test
    void validWebhook_marksPaymentSucceeded_andFulfillsOrderExactlyOnce() throws Exception {
        String orderRef = "wh-order-" + UUID.randomUUID();
        String piId = createPaymentAndGetProviderId(orderRef);
        String eventId = "evt_" + UUID.randomUUID();
        String payload = paymentSucceededPayload(eventId, piId);
        String signature = StripeWebhookTestSupport.sign(payload, WEBHOOK_SECRET);

        mockMvc.perform(post("/api/webhooks/stripe")
                        .header("Stripe-Signature", signature)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(payload))
                .andExpect(status().isOk())
                .andExpect(content().string("processed"));

        Order order = orderRepository.findByOrderReference(orderRef).orElseThrow();
        assertThat(order.getStatus()).isEqualTo(OrderStatus.FULFILLED);

        // Redelivery of the exact same event must be ignored, not re-fulfill the order.
        mockMvc.perform(post("/api/webhooks/stripe")
                        .header("Stripe-Signature", StripeWebhookTestSupport.sign(payload, WEBHOOK_SECRET))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(payload))
                .andExpect(status().isOk())
                .andExpect(content().string("duplicate_ignored"));
    }

    @Test
    void invalidSignature_isRejected() throws Exception {
        String orderRef = "wh-order-" + UUID.randomUUID();
        String piId = createPaymentAndGetProviderId(orderRef);
        String payload = paymentSucceededPayload("evt_" + UUID.randomUUID(), piId);
        String tamperedSignature = StripeWebhookTestSupport.sign(payload, "wrong_secret");

        mockMvc.perform(post("/api/webhooks/stripe")
                        .header("Stripe-Signature", tamperedSignature)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(payload))
                .andExpect(status().isBadRequest());

        Order order = orderRepository.findByOrderReference(orderRef).orElseThrow();
        assertThat(order.getStatus()).isEqualTo(OrderStatus.PENDING);
    }
}
