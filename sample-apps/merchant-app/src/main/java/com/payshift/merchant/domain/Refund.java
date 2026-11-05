package com.payshift.merchant.domain;

import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

import java.math.BigDecimal;
import java.time.Instant;

@Entity
@Table(name = "refunds")
public class Refund {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    private Long paymentId;

    private String provider;

    private String providerRefundId;

    private BigDecimal amount;

    private Instant createdAt;

    protected Refund() {
    }

    public Refund(Long paymentId, String provider, String providerRefundId, BigDecimal amount) {
        this.paymentId = paymentId;
        this.provider = provider;
        this.providerRefundId = providerRefundId;
        this.amount = amount;
        this.createdAt = Instant.now();
    }

    public Long getId() {
        return id;
    }

    public Long getPaymentId() {
        return paymentId;
    }

    public String getProvider() {
        return provider;
    }

    public String getProviderRefundId() {
        return providerRefundId;
    }

    public BigDecimal getAmount() {
        return amount;
    }
}
