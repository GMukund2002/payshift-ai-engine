package com.store.front;

import com.store.front.paypal.PaypalClient;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import java.math.BigDecimal;
import java.util.UUID;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
class PurchaseFlowTest {

    @Autowired
    MockMvc mvc;
    @MockBean
    PaypalClient paypal;

    private String buy(String ref) {
        return "{\"reference\":\"" + ref + "\",\"amount\":12.50,\"currency\":\"EUR\"}";
    }

    @Test
    void purchaseIsCreatedOnceThroughPaypal() throws Exception {
        String ref = "p-" + UUID.randomUUID();
        when(paypal.createOrder(eq(ref), any(), eq("EUR"))).thenReturn(new PaypalClient.PaypalOrder("ORDER-1", "CREATED"));
        mvc.perform(post("/purchases").contentType(MediaType.APPLICATION_JSON).content(buy(ref)))
                .andExpect(status().isCreated()).andExpect(jsonPath("$.processor").value("paypal"));
        mvc.perform(post("/purchases").contentType(MediaType.APPLICATION_JSON).content(buy(ref)))
                .andExpect(status().isCreated()).andExpect(jsonPath("$.processorOrderId").value("ORDER-1"));
        verify(paypal, times(1)).createOrder(eq(ref), any(), eq("EUR"));
    }

    @Test
    void completedPurchaseIsRefundedThroughPaypal() throws Exception {
        String ref = "p-" + UUID.randomUUID();
        when(paypal.createOrder(eq(ref), any(), eq("EUR"))).thenReturn(new PaypalClient.PaypalOrder("CAP-2", "COMPLETED"));
        mvc.perform(post("/purchases").contentType(MediaType.APPLICATION_JSON).content(buy(ref))).andExpect(status().isCreated());
        when(paypal.refundCapture(eq("CAP-2"), any(BigDecimal.class), eq("EUR"))).thenReturn("REF-2");
        mvc.perform(post("/purchases/" + ref + "/refund"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.status").value("REFUNDED"));
    }

    @Test
    void pendingPurchaseCannotBeRefunded() throws Exception {
        String ref = "p-" + UUID.randomUUID();
        when(paypal.createOrder(eq(ref), any(), eq("EUR"))).thenReturn(new PaypalClient.PaypalOrder("ORDER-3", "CREATED"));
        mvc.perform(post("/purchases").contentType(MediaType.APPLICATION_JSON).content(buy(ref))).andExpect(status().isCreated());
        mvc.perform(post("/purchases/" + ref + "/refund")).andExpect(status().isConflict());
        verify(paypal, never()).refundCapture(any(), any(), any());
    }
}
