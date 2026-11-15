package com.shop.orders;

import com.shop.orders.payments.RazorpayGateway;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.mock.mockito.MockBean;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.util.HexFormat;
import java.util.UUID;

import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
class OrderPaymentFlowTest {

    private static final String WEBHOOK_SECRET = "whsec_placeholder";

    @Autowired
    MockMvc mvc;

    @MockBean
    RazorpayGateway razorpay;

    private static String sign(String body) throws Exception {
        Mac mac = Mac.getInstance("HmacSHA256");
        mac.init(new SecretKeySpec(WEBHOOK_SECRET.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
        return HexFormat.of().formatHex(mac.doFinal(body.getBytes(StandardCharsets.UTF_8)));
    }

    private long createOrder(String receipt, String providerOrderId) throws Exception {
        when(razorpay.createOrder(eq(receipt), anyLong(), anyString()))
                .thenReturn(new RazorpayGateway.RazorpayOrder(providerOrderId, "created"));
        String body = mvc.perform(post("/api/orders").contentType(MediaType.APPLICATION_JSON)
                        .content("{\"receipt\":\"" + receipt + "\",\"amountPaise\":49900,\"currency\":\"INR\"}"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.provider").value("razorpay"))
                .andExpect(jsonPath("$.state").value("AWAITING_PAYMENT"))
                .andReturn().getResponse().getContentAsString();
        return Long.parseLong(body.replaceAll(".*\"id\":(\\d+).*", "$1"));
    }

    private String captured(String orderId, String paymentId) {
        return "{\"event\":\"payment.captured\",\"payload\":{\"payment\":{\"entity\":{\"id\":\"" + paymentId
                + "\",\"order_id\":\"" + orderId + "\"}}}}";
    }

    @Test
    void createOrder_isIdempotentPerReceipt() throws Exception {
        String receipt = "rcpt-" + UUID.randomUUID();
        createOrder(receipt, "order_A");
        createOrder(receipt, "order_A");
        verify(razorpay, times(1)).createOrder(eq(receipt), anyLong(), anyString());
    }

    @Test
    void signedCapturedWebhook_marksOrderPaid_andRedeliveryIsIgnored() throws Exception {
        long id = createOrder("rcpt-" + UUID.randomUUID(), "order_B");
        String body = captured("order_B", "pay_B");
        String eventId = "evt-" + UUID.randomUUID();

        mvc.perform(post("/api/webhooks/razorpay").content(body)
                        .header("X-Razorpay-Signature", sign(body)).header("X-Razorpay-Event-Id", eventId))
                .andExpect(status().isOk()).andExpect(content().string("processed"));
        mvc.perform(post("/api/webhooks/razorpay").content(body)
                        .header("X-Razorpay-Signature", sign(body)).header("X-Razorpay-Event-Id", eventId))
                .andExpect(status().isOk()).andExpect(content().string("duplicate"));
        mvc.perform(get("/api/orders/" + id)).andExpect(jsonPath("$.state").value("PAID"));
    }

    @Test
    void webhookWithBadSignature_isRejected_andChangesNothing() throws Exception {
        long id = createOrder("rcpt-" + UUID.randomUUID(), "order_C");
        String body = captured("order_C", "pay_C");
        mvc.perform(post("/api/webhooks/razorpay").content(body).header("X-Razorpay-Signature", "deadbeef"))
                .andExpect(status().isBadRequest());
        mvc.perform(get("/api/orders/" + id)).andExpect(jsonPath("$.state").value("AWAITING_PAYMENT"));
    }

    @Test
    void refund_ofPaidOrder_goesToRazorpayWithTheCapturedPayment() throws Exception {
        long id = createOrder("rcpt-" + UUID.randomUUID(), "order_D");
        String body = captured("order_D", "pay_D");
        mvc.perform(post("/api/webhooks/razorpay").content(body).header("X-Razorpay-Signature", sign(body)))
                .andExpect(status().isOk());
        when(razorpay.refundPayment("pay_D", 49900)).thenReturn(new RazorpayGateway.RazorpayRefund("rfnd_D", "processed"));

        mvc.perform(post("/api/orders/" + id + "/refund"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.state").value("REFUNDED"));
        verify(razorpay).refundPayment("pay_D", 49900);
    }

    @Test
    void refund_ofUnpaidOrder_isRejected() throws Exception {
        long id = createOrder("rcpt-" + UUID.randomUUID(), "order_E");
        mvc.perform(post("/api/orders/" + id + "/refund")).andExpect(status().isUnprocessableEntity());
        verify(razorpay, never()).refundPayment(anyString(), anyLong());
    }
}
