package com.shop.orders.payments;

import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

import java.util.Map;

/** Thin REST client over Razorpay's Orders and Refunds APIs (no SDK). */
@Component
public class RazorpayGateway {

    public record RazorpayOrder(String id, String status) {
    }

    public record RazorpayRefund(String id, String status) {
    }

    private final RestClient http;

    public RazorpayGateway(@Qualifier("razorpayRestClient") RestClient http) {
        this.http = http;
    }

    public RazorpayOrder createOrder(String receipt, long amountPaise, String currency) {
        return http.post().uri("/orders")
                .body(Map.of("amount", amountPaise, "currency", currency, "receipt", receipt))
                .retrieve()
                .body(RazorpayOrder.class);
    }

    public RazorpayRefund refundPayment(String paymentId, long amountPaise) {
        return http.post().uri("/payments/{id}/refund", paymentId)
                .body(Map.of("amount", amountPaise))
                .retrieve()
                .body(RazorpayRefund.class);
    }
}
