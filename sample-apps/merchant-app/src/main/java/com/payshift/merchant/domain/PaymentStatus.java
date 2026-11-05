package com.payshift.merchant.domain;

public enum PaymentStatus {
    CREATED,
    REQUIRES_ACTION,
    SUCCEEDED,
    FAILED,
    REFUNDED,
    PARTIALLY_REFUNDED
}
