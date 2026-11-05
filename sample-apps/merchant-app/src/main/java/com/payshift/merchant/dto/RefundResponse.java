package com.payshift.merchant.dto;

import com.payshift.merchant.domain.Refund;

import java.math.BigDecimal;

public record RefundResponse(Long id, String provider, String providerRefundId, BigDecimal amount) {
    public static RefundResponse from(Refund refund) {
        return new RefundResponse(refund.getId(), refund.getProvider(), refund.getProviderRefundId(), refund.getAmount());
    }
}
