package com.payshift.merchant.domain;

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

@Entity
@Table(name = "orders")
public class Order {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    private String orderReference;

    private BigDecimal amount;

    private String currency;

    @Enumerated(EnumType.STRING)
    private OrderStatus status;

    private Instant createdAt;

    private Instant fulfilledAt;

    @Version
    private Long version;

    protected Order() {
    }

    public Order(String orderReference, BigDecimal amount, String currency) {
        this.orderReference = orderReference;
        this.amount = amount;
        this.currency = currency;
        this.status = OrderStatus.PENDING;
        this.createdAt = Instant.now();
    }

    public Long getId() {
        return id;
    }

    public String getOrderReference() {
        return orderReference;
    }

    public BigDecimal getAmount() {
        return amount;
    }

    public String getCurrency() {
        return currency;
    }

    public OrderStatus getStatus() {
        return status;
    }

    public Instant getFulfilledAt() {
        return fulfilledAt;
    }

    /**
     * Fulfillment must be idempotent: repeated calls after the order is already
     * FULFILLED are no-ops so a duplicate webhook can never trigger double fulfillment.
     */
    public boolean markFulfilled() {
        if (this.status == OrderStatus.FULFILLED) {
            return false;
        }
        this.status = OrderStatus.FULFILLED;
        this.fulfilledAt = Instant.now();
        return true;
    }
}
