package com.payshift.merchant.provider;

import java.math.BigDecimal;

/**
 * Thin port around the Stripe Java SDK. The sample app talks to Stripe only through
 * this interface so tests can substitute mocked provider responses instead of making
 * real network calls, while production wiring (StripeApiPaymentGateway) uses the
 * actual com.stripe.* SDK types and calls.
 */
public interface StripePaymentGateway {

    ProviderPaymentResult createPaymentIntent(String orderReference, BigDecimal amount, String currency);

    ProviderRefundResult createRefund(String providerPaymentId, BigDecimal amount);

    record ProviderPaymentResult(String providerPaymentId, String status, String clientSecret) {
    }

    record ProviderRefundResult(String providerRefundId, String status) {
    }
}
