package com.payments.router.provider;

import com.fasterxml.jackson.databind.JsonNode;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

import java.math.BigDecimal;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** PayPal Orders v2 + Payments v2 over REST. */
@Component
public class PaypalProvider implements PaymentProvider {

    private final RestClient http;
    private final Set<String> currencies;

    public PaypalProvider(@Qualifier("paypalRestClient") RestClient http,
                          @Value("${payments.paypal.currencies}") Set<String> currencies) {
        this.http = http;
        this.currencies = currencies;
    }

    @Override
    public String id() {
        return "paypal";
    }

    @Override
    public Set<String> supportedCurrencies() {
        return currencies;
    }

    private static String major(long amountMinor) {
        return BigDecimal.valueOf(amountMinor, 2).toPlainString();
    }

    @Override
    public ProviderPayment createPayment(String reference, long amountMinor, String currency) {
        JsonNode order = http.post().uri("/v2/checkout/orders")
                .body(Map.of("intent", "CAPTURE", "purchase_units", List.of(Map.of(
                        "reference_id", reference,
                        "amount", Map.of("currency_code", currency, "value", major(amountMinor))))))
                .retrieve()
                .body(JsonNode.class);
        return new ProviderPayment(order.path("id").asText(), order.path("status").asText());
    }

    @Override
    public ProviderRefund refund(String providerPaymentId, long amountMinor) {
        JsonNode refund = http.post().uri("/v2/payments/captures/{id}/refund", providerPaymentId)
                .body(Map.of("amount", Map.of("value", major(amountMinor))))
                .retrieve()
                .body(JsonNode.class);
        return new ProviderRefund(refund.path("id").asText(), refund.path("status").asText());
    }
}
