package com.billing.subs.subscription;

import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import lombok.AccessLevel;
import lombok.Getter;
import lombok.NoArgsConstructor;

@Entity
@Getter
@NoArgsConstructor(access = AccessLevel.PROTECTED)
public class Subscription {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;
    private String customerEmail;
    private String planCode;
    private long amountCents;
    private String currency;
    /** Payment gateway that owns this subscription's charge; fixed at creation. */
    private String gateway;
    private String gatewayPaymentId;
    private String state;

    public Subscription(String customerEmail, String planCode, long amountCents, String currency,
                        String gateway, String gatewayPaymentId, String state) {
        this.customerEmail = customerEmail;
        this.planCode = planCode;
        this.amountCents = amountCents;
        this.currency = currency;
        this.gateway = gateway;
        this.gatewayPaymentId = gatewayPaymentId;
        this.state = state;
    }

    public void markRefunded() {
        this.state = "REFUNDED";
    }
}
