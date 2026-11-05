package com.example.provider;

import com.stripe.model.PaymentIntent;

public class StripeProviderAdapter implements PaymentProvider {
    @Override
    public String createPayment(long amount, String currency) {
        return "pi_123";
    }

    @Override
    public String getPaymentStatus(String providerPaymentId) {
        return "succeeded";
    }

    @Override
    public String createRefund(String providerPaymentId, long amount) {
        return "re_123";
    }
}
