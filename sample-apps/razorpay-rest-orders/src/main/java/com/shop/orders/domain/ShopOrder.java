package com.shop.orders.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "shop_orders")
public class ShopOrder {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(unique = true, nullable = false)
    private String receipt;

    private long amountPaise;

    private String currency;

    /** Which PSP owns this order's payment. Never changes after creation. */
    private String provider;

    private String providerOrderId;

    private String providerPaymentId;

    @Enumerated(EnumType.STRING)
    private OrderState state;

    protected ShopOrder() {
    }

    public ShopOrder(String receipt, long amountPaise, String currency, String provider, String providerOrderId) {
        this.receipt = receipt;
        this.amountPaise = amountPaise;
        this.currency = currency;
        this.provider = provider;
        this.providerOrderId = providerOrderId;
        this.state = OrderState.AWAITING_PAYMENT;
    }

    public void markPaid(String paymentId) {
        this.providerPaymentId = paymentId;
        this.state = OrderState.PAID;
    }

    public void markFailed() {
        this.state = OrderState.PAYMENT_FAILED;
    }

    public void markRefunded() {
        this.state = OrderState.REFUNDED;
    }

    public Long getId() { return id; }
    public String getReceipt() { return receipt; }
    public long getAmountPaise() { return amountPaise; }
    public String getCurrency() { return currency; }
    public String getProvider() { return provider; }
    public String getProviderOrderId() { return providerOrderId; }
    public String getProviderPaymentId() { return providerPaymentId; }
    public OrderState getState() { return state; }
}
