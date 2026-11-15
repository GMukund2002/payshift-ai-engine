package com.acme.checkout.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

import java.time.Instant;

/** A charge is owned forever by the provider that created it (see {@link #getProvider()}). */
@Entity
@Table(name = "charges")
public class Charge {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(unique = true, nullable = false)
    private String orderId;

    private String provider;

    private String providerChargeId;

    private long amountCents;

    private String currency;

    @Enumerated(EnumType.STRING)
    private ChargeStatus status;

    private long refundedCents;

    private Instant createdAt;

    protected Charge() {
    }

    public Charge(String orderId, String provider, String providerChargeId, long amountCents, String currency,
                  ChargeStatus status) {
        this.orderId = orderId;
        this.provider = provider;
        this.providerChargeId = providerChargeId;
        this.amountCents = amountCents;
        this.currency = currency;
        this.status = status;
        this.createdAt = Instant.now();
    }

    public long refundableCents() {
        return amountCents - refundedCents;
    }

    public void recordRefund(long cents) {
        refundedCents += cents;
        status = refundedCents >= amountCents ? ChargeStatus.REFUNDED : ChargeStatus.PARTIALLY_REFUNDED;
    }

    public Long getId() { return id; }
    public String getOrderId() { return orderId; }
    public String getProvider() { return provider; }
    public String getProviderChargeId() { return providerChargeId; }
    public long getAmountCents() { return amountCents; }
    public String getCurrency() { return currency; }
    public ChargeStatus getStatus() { return status; }
    public long getRefundedCents() { return refundedCents; }
}
