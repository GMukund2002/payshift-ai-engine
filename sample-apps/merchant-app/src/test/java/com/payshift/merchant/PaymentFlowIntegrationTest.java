package com.payshift.merchant;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.payshift.merchant.provider.StripePaymentGateway;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import java.math.BigDecimal;
import java.util.Map;
import java.util.UUID;

import static org.hamcrest.Matchers.closeTo;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
class PaymentFlowIntegrationTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private ObjectMapper objectMapper;

    @MockBean
    private StripePaymentGateway stripeGateway;

    private String createPaymentJson(String orderRef, String amount, String idempotencyKey) throws Exception {
        return objectMapper.writeValueAsString(Map.of(
                "orderReference", orderRef,
                "amount", amount,
                "currency", "usd",
                "idempotencyKey", idempotencyKey
        ));
    }

    @Test
    void createPayment_succeeds_whenGatewayConfirmsImmediately() throws Exception {
        String piId = "pi_" + UUID.randomUUID();
        when(stripeGateway.createPaymentIntent(any(), any(), any()))
                .thenReturn(new StripePaymentGateway.ProviderPaymentResult(piId, "succeeded", "secret"));

        mockMvc.perform(post("/api/payments")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(createPaymentJson("order-1", "25.00", "idem-1")))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.provider").value("stripe"))
                .andExpect(jsonPath("$.providerPaymentId").value(piId))
                .andExpect(jsonPath("$.status").value("SUCCEEDED"))
                .andExpect(jsonPath("$.amount").value(closeTo(25.00, 0.001)));
    }

    @Test
    void createPayment_marksFailed_whenGatewayDeclines() throws Exception {
        String piId = "pi_" + UUID.randomUUID();
        when(stripeGateway.createPaymentIntent(any(), any(), any()))
                .thenReturn(new StripePaymentGateway.ProviderPaymentResult(piId, "requires_payment_method", "secret"));

        mockMvc.perform(post("/api/payments")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(createPaymentJson("order-2", "10.00", "idem-2")))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.status").value("FAILED"));
    }

    @Test
    void createPayment_isIdempotent_onRepeatedKey() throws Exception {
        String piId = "pi_" + UUID.randomUUID();
        when(stripeGateway.createPaymentIntent(any(), any(), any()))
                .thenReturn(new StripePaymentGateway.ProviderPaymentResult(piId, "succeeded", "secret"));

        String body = createPaymentJson("order-3", "15.00", "idem-3");
        mockMvc.perform(post("/api/payments").contentType(MediaType.APPLICATION_JSON).content(body))
                .andExpect(status().isCreated());
        mockMvc.perform(post("/api/payments").contentType(MediaType.APPLICATION_JSON).content(body))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.providerPaymentId").value(piId));

        verify(stripeGateway, times(1)).createPaymentIntent(any(), any(), any());
    }

    @Test
    void refund_full_marksPaymentRefunded_andRoutesToOwningProvider() throws Exception {
        String piId = "pi_" + UUID.randomUUID();
        when(stripeGateway.createPaymentIntent(any(), any(), any()))
                .thenReturn(new StripePaymentGateway.ProviderPaymentResult(piId, "succeeded", "secret"));
        mockMvc.perform(post("/api/payments").contentType(MediaType.APPLICATION_JSON)
                .content(createPaymentJson("order-4", "50.00", "idem-4"))).andExpect(status().isCreated());

        when(stripeGateway.createRefund(eq(piId), any()))
                .thenReturn(new StripePaymentGateway.ProviderRefundResult("re_1", "succeeded"));

        mockMvc.perform(post("/api/payments/" + piId + "/refunds")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{}"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.provider").value("stripe"));

        verify(stripeGateway, times(1)).createRefund(eq(piId), eq(new BigDecimal("50.00")));

        mockMvc.perform(get("/api/payments/" + piId))
                .andExpect(jsonPath("$.status").value("REFUNDED"));
    }

    @Test
    void refund_partial_leavesPaymentPartiallyRefunded() throws Exception {
        String piId = "pi_" + UUID.randomUUID();
        when(stripeGateway.createPaymentIntent(any(), any(), any()))
                .thenReturn(new StripePaymentGateway.ProviderPaymentResult(piId, "succeeded", "secret"));
        mockMvc.perform(post("/api/payments").contentType(MediaType.APPLICATION_JSON)
                .content(createPaymentJson("order-5", "50.00", "idem-5"))).andExpect(status().isCreated());

        when(stripeGateway.createRefund(eq(piId), eq(new BigDecimal("20.00"))))
                .thenReturn(new StripePaymentGateway.ProviderRefundResult("re_2", "succeeded"));

        mockMvc.perform(post("/api/payments/" + piId + "/refunds")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of("amount", "20.00"))))
                .andExpect(status().isCreated());

        mockMvc.perform(get("/api/payments/" + piId))
                .andExpect(jsonPath("$.status").value("PARTIALLY_REFUNDED"))
                .andExpect(jsonPath("$.refundedAmount").value(closeTo(20.00, 0.001)));
    }

    @Test
    void refund_rejectsOverRefund() throws Exception {
        String piId = "pi_" + UUID.randomUUID();
        when(stripeGateway.createPaymentIntent(any(), any(), any()))
                .thenReturn(new StripePaymentGateway.ProviderPaymentResult(piId, "succeeded", "secret"));
        mockMvc.perform(post("/api/payments").contentType(MediaType.APPLICATION_JSON)
                .content(createPaymentJson("order-6", "30.00", "idem-6"))).andExpect(status().isCreated());

        mockMvc.perform(post("/api/payments/" + piId + "/refunds")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(Map.of("amount", "999.00"))))
                .andExpect(status().isUnprocessableEntity());
    }

    @Test
    void refund_rejectsPaymentThatHasNotSucceeded() throws Exception {
        String piId = "pi_" + UUID.randomUUID();
        when(stripeGateway.createPaymentIntent(any(), any(), any()))
                .thenReturn(new StripePaymentGateway.ProviderPaymentResult(piId, "requires_action", "secret"));
        mockMvc.perform(post("/api/payments").contentType(MediaType.APPLICATION_JSON)
                .content(createPaymentJson("order-7", "30.00", "idem-7"))).andExpect(status().isCreated());

        mockMvc.perform(post("/api/payments/" + piId + "/refunds")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{}"))
                .andExpect(status().isUnprocessableEntity());
    }
}
