package com.payments.router.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "transactions")
public class Transaction {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(unique = true, nullable = false)
    private String reference;

    /** Owning provider -- refunds always go back to it, whatever the router would pick today. */
    private String providerId;

    private String providerPaymentId;

    private long amountMinor;

    private String currency;

    private String status;

    private long refundedMinor;

    protected Transaction() {
    }

    public Transaction(String reference, String providerId, String providerPaymentId, long amountMinor,
                       String currency, String status) {
        this.reference = reference;
        this.providerId = providerId;
        this.providerPaymentId = providerPaymentId;
        this.amountMinor = amountMinor;
        this.currency = currency;
        this.status = status;
    }

    public void recordRefund(long amount) {
        refundedMinor += amount;
        status = refundedMinor >= amountMinor ? "REFUNDED" : "PARTIALLY_REFUNDED";
    }

    public Long getId() { return id; }
    public String getReference() { return reference; }
    public String getProviderId() { return providerId; }
    public String getProviderPaymentId() { return providerPaymentId; }
    public long getAmountMinor() { return amountMinor; }
    public String getCurrency() { return currency; }
    public String getStatus() { return status; }
    public long getRefundedMinor() { return refundedMinor; }
}
