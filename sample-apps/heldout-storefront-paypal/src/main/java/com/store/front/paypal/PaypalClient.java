package com.store.front.paypal;

import org.springframework.stereotype.Component;
import org.springframework.web.client.RestTemplate;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;

/** PayPal Orders v2 / Payments v2 over REST. */
@Component
public class PaypalClient {

    public record PaypalOrder(String id, String status) {
    }

    private final RestTemplate rest;

    public PaypalClient(RestTemplate rest) {
        this.rest = rest;
    }

    @SuppressWarnings("unchecked")
    public PaypalOrder createOrder(String reference, BigDecimal amount, String currency) {
        Map<String, Object> body = Map.of("intent", "CAPTURE", "purchase_units", List.of(Map.of(
                "reference_id", reference,
                "amount", Map.of("currency_code", currency, "value", amount.toPlainString()))));
        Map<String, Object> res = rest.postForObject("/v2/checkout/orders", body, Map.class);
        return new PaypalOrder((String) res.get("id"), (String) res.get("status"));
    }

    @SuppressWarnings("unchecked")
    public String refundCapture(String captureId, BigDecimal amount, String currency) {
        Map<String, Object> body = Map.of("amount", Map.of("currency_code", currency, "value", amount.toPlainString()));
        Map<String, Object> res = rest.postForObject("/v2/payments/captures/{id}/refund", body, Map.class, captureId);
        return (String) res.get("id");
    }
}
