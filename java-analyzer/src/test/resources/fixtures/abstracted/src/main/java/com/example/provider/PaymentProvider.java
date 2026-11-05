package com.example.provider;

public interface PaymentProvider {
    String createPayment(long amount, String currency);
    String getPaymentStatus(String providerPaymentId);
    String createRefund(String providerPaymentId, long amount);
}
