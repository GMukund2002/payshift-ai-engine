package com.acme.checkout;

import com.stripe.StripeClient;
import com.stripe.model.PaymentIntent;
import com.stripe.model.Refund;
import com.stripe.param.PaymentIntentCreateParams;
import com.stripe.param.RefundCreateParams;
import com.stripe.service.PaymentIntentService;
import com.stripe.service.RefundService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import java.util.UUID;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
class CheckoutFlowTest {

    @Autowired
    MockMvc mvc;

    @MockBean
    StripeClient stripe;

    PaymentIntentService paymentIntents = mock(PaymentIntentService.class);
    RefundService refunds = mock(RefundService.class);

    @BeforeEach
    void wireStripeServices() {
        when(stripe.paymentIntents()).thenReturn(paymentIntents);
        when(stripe.refunds()).thenReturn(refunds);
    }

    private static PaymentIntent intent(String id, String status) {
        PaymentIntent pi = new PaymentIntent();
        pi.setId(id);
        pi.setStatus(status);
        return pi;
    }

    private String checkout(String orderId, long cents) {
        return "{\"orderId\":\"" + orderId + "\",\"amountCents\":" + cents + ",\"currency\":\"USD\"}";
    }

    private long createSucceededCharge(String orderId, long cents) throws Exception {
        when(paymentIntents.create(any(PaymentIntentCreateParams.class))).thenReturn(intent("pi_" + orderId, "succeeded"));
        String body = mvc.perform(post("/checkout").contentType(MediaType.APPLICATION_JSON).content(checkout(orderId, cents)))
                .andExpect(status().isCreated())
                .andReturn().getResponse().getContentAsString();
        return Long.parseLong(body.replaceAll(".*\"id\":(\\d+).*", "$1"));
    }

    @Test
    void successfulCharge_isRecordedAgainstStripe() throws Exception {
        when(paymentIntents.create(any(PaymentIntentCreateParams.class))).thenReturn(intent("pi_ok", "succeeded"));
        mvc.perform(post("/checkout").contentType(MediaType.APPLICATION_JSON).content(checkout("o-" + UUID.randomUUID(), 2500)))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.provider").value("stripe"))
                .andExpect(jsonPath("$.providerChargeId").value("pi_ok"))
                .andExpect(jsonPath("$.status").value("SUCCEEDED"));
    }

    @Test
    void declinedCharge_isMarkedFailed() throws Exception {
        when(paymentIntents.create(any(PaymentIntentCreateParams.class)))
                .thenReturn(intent("pi_declined", "requires_payment_method"));
        mvc.perform(post("/checkout").contentType(MediaType.APPLICATION_JSON).content(checkout("o-" + UUID.randomUUID(), 900)))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.status").value("FAILED"));
    }

    @Test
    void retriedCheckout_doesNotChargeTwice() throws Exception {
        String orderId = "o-" + UUID.randomUUID();
        when(paymentIntents.create(any(PaymentIntentCreateParams.class))).thenReturn(intent("pi_once", "succeeded"));
        mvc.perform(post("/checkout").contentType(MediaType.APPLICATION_JSON).content(checkout(orderId, 1000)))
                .andExpect(status().isCreated());
        mvc.perform(post("/checkout").contentType(MediaType.APPLICATION_JSON).content(checkout(orderId, 1000)))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.providerChargeId").value("pi_once"));
        verify(paymentIntents, times(1)).create(any(PaymentIntentCreateParams.class));
    }

    @Test
    void partialThenFullRefund_isRoutedToStripeWithTheOriginalPaymentIntent() throws Exception {
        String orderId = "o-" + UUID.randomUUID();
        long id = createSucceededCharge(orderId, 5000);
        when(refunds.create(any(RefundCreateParams.class))).thenReturn(new Refund());

        mvc.perform(post("/checkout/" + id + "/refund").contentType(MediaType.APPLICATION_JSON).content("{\"amountCents\":2000}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("PARTIALLY_REFUNDED"))
                .andExpect(jsonPath("$.refundedCents").value(2000));
        mvc.perform(post("/checkout/" + id + "/refund").contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("REFUNDED"))
                .andExpect(jsonPath("$.refundedCents").value(5000));

        verify(refunds, times(2)).create(argThat((RefundCreateParams p) -> ("pi_" + orderId).equals(p.getPaymentIntent())));
    }

    @Test
    void overRefund_isRejectedWithoutCallingStripe() throws Exception {
        long id = createSucceededCharge("o-" + UUID.randomUUID(), 1000);
        mvc.perform(post("/checkout/" + id + "/refund").contentType(MediaType.APPLICATION_JSON).content("{\"amountCents\":5000}"))
                .andExpect(status().isUnprocessableEntity());
        verify(refunds, never()).create(any(RefundCreateParams.class));
    }
}
