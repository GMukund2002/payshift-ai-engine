package com.payshift.merchant.dto;

import com.payshift.merchant.domain.Payment;

import java.math.BigDecimal;

public record PaymentResponse(
        Long id,
        String provider,
        String providerPaymentId,
        String status,
        BigDecimal amount,
        String currency,
        BigDecimal refundedAmount
) {
    public static PaymentResponse from(Payment payment) {
        return new PaymentResponse(
                payment.getId(),
                payment.getProvider(),
                payment.getProviderPaymentId(),
                payment.getStatus().name(),
                payment.getAmount(),
                payment.getCurrency(),
                payment.getRefundedAmount()
        );
    }
}
