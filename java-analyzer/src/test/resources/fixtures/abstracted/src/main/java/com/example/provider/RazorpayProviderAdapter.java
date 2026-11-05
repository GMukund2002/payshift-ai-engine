package com.example.provider;

import com.razorpay.RazorpayClient;

public class RazorpayProviderAdapter implements PaymentProvider {
    @Override
    public String createPayment(long amount, String currency) {
        return "order_123";
    }

    @Override
    public String getPaymentStatus(String providerPaymentId) {
        return "paid";
    }

    @Override
    public String createRefund(String providerPaymentId, long amount) {
        return "rfnd_123";
    }
}
