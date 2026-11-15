package com.payments.router.provider;

import com.stripe.StripeClient;
import com.stripe.exception.StripeException;
import com.stripe.model.PaymentIntent;
import com.stripe.model.Refund;
import com.stripe.param.PaymentIntentCreateParams;
import com.stripe.param.RefundCreateParams;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.util.Set;

@Component
public class StripeProvider implements PaymentProvider {

    private final StripeClient stripe;
    private final Set<String> currencies;

    public StripeProvider(StripeClient stripe, @Value("${payments.stripe.currencies}") Set<String> currencies) {
        this.stripe = stripe;
        this.currencies = currencies;
    }

    @Override
    public String id() {
        return "stripe";
    }

    @Override
    public Set<String> supportedCurrencies() {
        return currencies;
    }

    @Override
    public ProviderPayment createPayment(String reference, long amountMinor, String currency) {
        try {
            PaymentIntent intent = stripe.paymentIntents().create(PaymentIntentCreateParams.builder()
                    .setAmount(amountMinor)
                    .setCurrency(currency.toLowerCase())
                    .addPaymentMethodType("card")
                    .putMetadata("reference", reference)
                    .build());
            return new ProviderPayment(intent.getId(), intent.getStatus());
        } catch (StripeException e) {
            throw new ProviderException("stripe", e);
        }
    }

    @Override
    public ProviderRefund refund(String providerPaymentId, long amountMinor) {
        try {
            Refund refund = stripe.refunds().create(RefundCreateParams.builder()
                    .setPaymentIntent(providerPaymentId)
                    .setAmount(amountMinor)
                    .build());
            return new ProviderRefund(refund.getId(), refund.getStatus());
        } catch (StripeException e) {
            throw new ProviderException("stripe", e);
        }
    }
}
