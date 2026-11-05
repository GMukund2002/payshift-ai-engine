package com.payshift.merchant.dto;

import java.math.BigDecimal;

/** amount is optional: null means a full refund of whatever remains refundable. */
public record RefundRequest(BigDecimal amount) {
}
