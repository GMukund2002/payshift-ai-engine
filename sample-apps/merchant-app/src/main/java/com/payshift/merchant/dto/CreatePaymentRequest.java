package com.payshift.merchant.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;

import java.math.BigDecimal;

public record CreatePaymentRequest(
        @NotBlank String orderReference,
        @NotNull @Positive BigDecimal amount,
        @NotBlank String currency,
        @NotBlank String idempotencyKey
) {
}
