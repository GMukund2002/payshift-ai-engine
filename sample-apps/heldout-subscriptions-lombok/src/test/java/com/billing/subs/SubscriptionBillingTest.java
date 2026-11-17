package com.billing.subs;

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

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
class SubscriptionBillingTest {

    @Autowired
    MockMvc mvc;
    @MockBean
    StripeClient stripe;
    PaymentIntentService intents = mock(PaymentIntentService.class);
    RefundService refunds = mock(RefundService.class);

    @BeforeEach
    void wire() {
        when(stripe.paymentIntents()).thenReturn(intents);
        when(stripe.refunds()).thenReturn(refunds);
    }

    private long start(String status) throws Exception {
        PaymentIntent pi = new PaymentIntent();
        pi.setId("pi_" + status);
        pi.setStatus(status);
        when(intents.create(any(PaymentIntentCreateParams.class))).thenReturn(pi);
        String body = mvc.perform(post("/subscriptions").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"email\":\"a@b.co\",\"planCode\":\"pro\",\"amountCents\":1900,\"currency\":\"USD\"}"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.gateway").value("stripe"))
                .andReturn().getResponse().getContentAsString();
        return Long.parseLong(body.replaceAll(".*\"id\":(\\d+).*", "$1"));
    }

    @Test
    void paidSubscriptionBecomesActive() throws Exception {
        long id = start("succeeded");
        mvc.perform(org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get("/subscriptions/" + id))
                .andExpect(jsonPath("$.state").value("ACTIVE"));
    }

    @Test
    void activeSubscriptionCanBeRefundedThroughStripe() throws Exception {
        long id = start("succeeded");
        when(refunds.create(any(RefundCreateParams.class))).thenReturn(new Refund());
        mvc.perform(post("/subscriptions/" + id + "/refund"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.state").value("REFUNDED"));
        verify(refunds).create(any(RefundCreateParams.class));
    }

    @Test
    void unpaidSubscriptionCannotBeRefunded() throws Exception {
        long id = start("requires_action");
        mvc.perform(post("/subscriptions/" + id + "/refund")).andExpect(status().isConflict());
        verify(refunds, never()).create(any(RefundCreateParams.class));
    }
}
