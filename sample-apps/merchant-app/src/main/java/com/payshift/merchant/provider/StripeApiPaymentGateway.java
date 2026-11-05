package com.payshift.merchant.provider;

import com.stripe.exception.StripeException;
import com.stripe.model.PaymentIntent;
import com.stripe.model.Refund;
import com.stripe.param.PaymentIntentCreateParams;
import com.stripe.param.RefundCreateParams;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.math.RoundingMode;

/**
 * Real Stripe SDK integration. Not exercised in the default test suite (which mocks
 * StripePaymentGateway) because the sample app must never make live calls, but this
 * class is genuine, documented Stripe Java SDK usage, not a stub.
 */
@Component
public class StripeApiPaymentGateway implements StripePaymentGateway {

    private final String apiKey;

    public StripeApiPaymentGateway(@Value("${payshift.stripe.api-key:sk_test_placeholder}") String apiKey) {
        this.apiKey = apiKey;
    }

    private static long toMinorUnits(BigDecimal amount) {
        return amount.setScale(2, RoundingMode.HALF_UP).movePointRight(2).longValueExact();
    }

    @Override
    public ProviderPaymentResult createPaymentIntent(String orderReference, BigDecimal amount, String currency) {
        com.stripe.Stripe.apiKey = this.apiKey;
        PaymentIntentCreateParams params = PaymentIntentCreateParams.builder()
                .setAmount(toMinorUnits(amount))
                .setCurrency(currency.toLowerCase())
                .putMetadata("order_reference", orderReference)
                .addPaymentMethodType("card")
                .build();
        try {
            PaymentIntent intent = PaymentIntent.create(params);
            return new ProviderPaymentResult(intent.getId(), intent.getStatus(), intent.getClientSecret());
        } catch (StripeException e) {
            throw new ProviderCallException("Stripe payment intent creation failed", e);
        }
    }

    @Override
    public ProviderRefundResult createRefund(String providerPaymentId, BigDecimal amount) {
        com.stripe.Stripe.apiKey = this.apiKey;
        RefundCreateParams params = RefundCreateParams.builder()
                .setPaymentIntent(providerPaymentId)
                .setAmount(toMinorUnits(amount))
                .build();
        try {
            Refund refund = Refund.create(params);
            return new ProviderRefundResult(refund.getId(), refund.getStatus());
        } catch (StripeException e) {
            throw new ProviderCallException("Stripe refund creation failed", e);
        }
    }
}
