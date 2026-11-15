package com.payments.router;

import com.payments.router.provider.PaymentProvider;
import com.payments.router.provider.PaypalProvider;
import com.payments.router.provider.StripeProvider;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import java.util.Set;
import java.util.UUID;

import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
class RoutingTest {

    @Autowired
    MockMvc mvc;

    @MockBean
    StripeProvider stripe;

    @MockBean
    PaypalProvider paypal;

    @BeforeEach
    void identities() {
        when(stripe.id()).thenReturn("stripe");
        when(stripe.supportedCurrencies()).thenReturn(Set.of("USD", "GBP"));
        when(paypal.id()).thenReturn("paypal");
        when(paypal.supportedCurrencies()).thenReturn(Set.of("EUR", "AUD"));
    }

    private String pay(String ref, String currency) {
        return "{\"reference\":\"" + ref + "\",\"amountMinor\":1500,\"currency\":\"" + currency + "\"}";
    }

    @Test
    void usdIsRoutedToStripe() throws Exception {
        when(stripe.createPayment(anyString(), anyLong(), anyString()))
                .thenReturn(new PaymentProvider.ProviderPayment("pi_1", "succeeded"));
        mvc.perform(post("/payments").contentType(MediaType.APPLICATION_JSON).content(pay("r-" + UUID.randomUUID(), "USD")))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.providerId").value("stripe"));
        verify(paypal, never()).createPayment(anyString(), anyLong(), anyString());
    }

    @Test
    void eurIsRoutedToPaypal() throws Exception {
        when(paypal.createPayment(anyString(), anyLong(), anyString()))
                .thenReturn(new PaymentProvider.ProviderPayment("PAY-1", "CREATED"));
        mvc.perform(post("/payments").contentType(MediaType.APPLICATION_JSON).content(pay("r-" + UUID.randomUUID(), "EUR")))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.providerId").value("paypal"));
    }

    @Test
    void unsupportedCurrencyIsRejected() throws Exception {
        mvc.perform(post("/payments").contentType(MediaType.APPLICATION_JSON).content(pay("r-" + UUID.randomUUID(), "JPY")))
                .andExpect(status().isUnprocessableEntity());
    }

    @Test
    void refundGoesToTheOwningProvider() throws Exception {
        String ref = "r-" + UUID.randomUUID();
        when(paypal.createPayment(anyString(), anyLong(), anyString()))
                .thenReturn(new PaymentProvider.ProviderPayment("PAY-2", "COMPLETED"));
        mvc.perform(post("/payments").contentType(MediaType.APPLICATION_JSON).content(pay(ref, "EUR")))
                .andExpect(status().isCreated());
        when(paypal.refund("PAY-2", 1500)).thenReturn(new PaymentProvider.ProviderRefund("RF-2", "COMPLETED"));

        mvc.perform(post("/payments/" + ref + "/refunds").contentType(MediaType.APPLICATION_JSON).content("{}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("REFUNDED"));
        verify(paypal).refund("PAY-2", 1500);
        verify(stripe, never()).refund(anyString(), anyLong());
    }
}
