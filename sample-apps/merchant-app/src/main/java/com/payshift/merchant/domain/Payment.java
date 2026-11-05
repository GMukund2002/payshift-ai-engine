package com.payshift.merchant.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import jakarta.persistence.Version;

import java.math.BigDecimal;
import java.time.Instant;

/**
 * A payment is permanently owned by the provider that created it. This ownership
 * is never re-derived at request time (no "pick a provider" on refund) so that
 * MIGRATE_PSP can change routing for new payments without touching old ones.
 */
@Entity
@Table(name = "payments")
public class Payment {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    private Long orderId;

    /** Generic provider identifier, e.g. "stripe". Never branched on in core logic beyond routing. */
    private String provider;

    private String providerPaymentId;

    @Column(unique = true)
    private String idempotencyKey;

    private BigDecimal amount;

    private String currency;

    @Enumerated(EnumType.STRING)
    private PaymentStatus status;

    private BigDecimal refundedAmount = BigDecimal.ZERO;

    private Instant createdAt;

    private Instant updatedAt;

    @Version
    private Long version;

    protected Payment() {
    }

    public Payment(Long orderId, String provider, String providerPaymentId, String idempotencyKey,
                    BigDecimal amount, String currency, PaymentStatus status) {
        this.orderId = orderId;
        this.provider = provider;
        this.providerPaymentId = providerPaymentId;
        this.idempotencyKey = idempotencyKey;
        this.amount = amount;
        this.currency = currency;
        this.status = status;
        this.createdAt = Instant.now();
        this.updatedAt = Instant.now();
    }

    public Long getId() {
        return id;
    }

    public Long getOrderId() {
        return orderId;
    }

    public String getProvider() {
        return provider;
    }

    public String getProviderPaymentId() {
        return providerPaymentId;
    }

    public String getIdempotencyKey() {
        return idempotencyKey;
    }

    public BigDecimal getAmount() {
        return amount;
    }

    public String getCurrency() {
        return currency;
    }

    public PaymentStatus getStatus() {
        return status;
    }

    public BigDecimal getRefundedAmount() {
        return refundedAmount;
    }

    public BigDecimal getRefundableAmount() {
        return amount.subtract(refundedAmount);
    }

    public void markSucceeded() {
        this.status = PaymentStatus.SUCCEEDED;
        this.updatedAt = Instant.now();
    }

    public void markFailed() {
        this.status = PaymentStatus.FAILED;
        this.updatedAt = Instant.now();
    }

    public void applyRefund(BigDecimal refundAmount) {
        this.refundedAmount = this.refundedAmount.add(refundAmount);
        this.status = this.refundedAmount.compareTo(this.amount) >= 0
                ? PaymentStatus.REFUNDED
                : PaymentStatus.PARTIALLY_REFUNDED;
        this.updatedAt = Instant.now();
    }
}
