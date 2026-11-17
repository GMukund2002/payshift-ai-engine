package com.store.front.orders;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;

import java.math.BigDecimal;

@Entity
public class Purchase {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    @Column(unique = true)
    private String reference;
    private BigDecimal amount;
    private String currency;
    private String processor;
    private String processorOrderId;
    private String status;

    protected Purchase() {
    }

    public Purchase(String reference, BigDecimal amount, String currency, String processor, String processorOrderId,
                    String status) {
        this.reference = reference;
        this.amount = amount;
        this.currency = currency;
        this.processor = processor;
        this.processorOrderId = processorOrderId;
        this.status = status;
    }

    public void markRefunded() {
        this.status = "REFUNDED";
    }

    public Long getId() { return id; }
    public String getReference() { return reference; }
    public BigDecimal getAmount() { return amount; }
    public String getCurrency() { return currency; }
    public String getProcessor() { return processor; }
    public String getProcessorOrderId() { return processorOrderId; }
    public String getStatus() { return status; }
}
