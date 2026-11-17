package com.ledger.invoices.gateway;

import com.stripe.Stripe;
import com.stripe.exception.StripeException;
import com.stripe.model.PaymentIntent;
import com.stripe.model.Refund;
import com.stripe.param.PaymentIntentCreateParams;
import com.stripe.param.RefundCreateParams;
import jakarta.annotation.PostConstruct;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/** Stripe's classic static API (Stripe.apiKey + Model.create). */
@Component
public class StripeGateway {

    public record Charge(String reference, String status) {
    }

    private final String apiKey;

    public StripeGateway(@Value("${ledger.stripe.api-key}") String apiKey) {
        this.apiKey = apiKey;
    }

    @PostConstruct
    void configure() {
        Stripe.apiKey = apiKey;
    }

    public Charge charge(String invoiceNo, long amountMinor, String currency) {
        try {
            PaymentIntent intent = PaymentIntent.create(PaymentIntentCreateParams.builder()
                    .setAmount(amountMinor).setCurrency(currency.toLowerCase())
                    .addPaymentMethodType("card").putMetadata("invoice_no", invoiceNo).build());
            return new Charge(intent.getId(), intent.getStatus());
        } catch (StripeException e) {
            throw new IllegalStateException("Stripe charge failed for invoice " + invoiceNo, e);
        }
    }

    public String refund(String paymentIntentId) {
        try {
            return Refund.create(RefundCreateParams.builder().setPaymentIntent(paymentIntentId).build()).getId();
        } catch (StripeException e) {
            throw new IllegalStateException("Stripe refund failed for " + paymentIntentId, e);
        }
    }
}
