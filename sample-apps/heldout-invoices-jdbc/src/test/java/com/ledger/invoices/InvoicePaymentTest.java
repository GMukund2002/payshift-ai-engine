package com.ledger.invoices;

import com.ledger.invoices.gateway.StripeGateway;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import java.util.UUID;

import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
class InvoicePaymentTest {

    @Autowired
    MockMvc mvc;
    @MockBean
    StripeGateway stripe;

    private static final String BODY = "{\"amountMinor\":9900,\"currency\":\"USD\"}";

    @Test
    void invoiceIsChargedOnce() throws Exception {
        String inv = "INV-" + UUID.randomUUID();
        when(stripe.charge(inv, 9900, "USD")).thenReturn(new StripeGateway.Charge("pi_1", "succeeded"));
        mvc.perform(post("/invoices/" + inv + "/payment").contentType(MediaType.APPLICATION_JSON).content(BODY))
                .andExpect(status().isCreated()).andExpect(jsonPath("$.psp").value("stripe"))
                .andExpect(jsonPath("$.status").value("PAID"));
        mvc.perform(post("/invoices/" + inv + "/payment").contentType(MediaType.APPLICATION_JSON).content(BODY))
                .andExpect(status().isCreated());
        verify(stripe, times(1)).charge(inv, 9900, "USD");
    }

    @Test
    void paidInvoiceIsRefundedWithItsStripeReference() throws Exception {
        String inv = "INV-" + UUID.randomUUID();
        when(stripe.charge(inv, 9900, "USD")).thenReturn(new StripeGateway.Charge("pi_2", "succeeded"));
        mvc.perform(post("/invoices/" + inv + "/payment").contentType(MediaType.APPLICATION_JSON).content(BODY));
        when(stripe.refund("pi_2")).thenReturn("re_2");
        mvc.perform(post("/invoices/" + inv + "/refund"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.status").value("REFUNDED"));
        verify(stripe).refund("pi_2");
    }

    @Test
    void unpaidInvoiceCannotBeRefunded() throws Exception {
        String inv = "INV-" + UUID.randomUUID();
        when(stripe.charge(inv, 9900, "USD")).thenReturn(new StripeGateway.Charge("pi_3", "requires_action"));
        mvc.perform(post("/invoices/" + inv + "/payment").contentType(MediaType.APPLICATION_JSON).content(BODY));
        mvc.perform(post("/invoices/" + inv + "/refund")).andExpect(status().isConflict());
        verify(stripe, never()).refund(anyString());
    }
}
