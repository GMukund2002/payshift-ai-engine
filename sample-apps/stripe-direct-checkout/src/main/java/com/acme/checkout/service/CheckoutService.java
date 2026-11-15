package com.acme.checkout.service;

import com.acme.checkout.domain.Charge;
import com.acme.checkout.domain.ChargeStatus;
import com.acme.checkout.repository.ChargeRepository;
import com.stripe.StripeClient;
import com.stripe.exception.StripeException;
import com.stripe.model.PaymentIntent;
import com.stripe.param.PaymentIntentCreateParams;
import com.stripe.param.RefundCreateParams;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * Talks to Stripe directly -- no provider interface between the business logic
 * and the SDK. This is the tightly coupled "before" state many real merchants have.
 */
@Service
public class CheckoutService {

    private static final String PROVIDER = "stripe";

    private final StripeClient stripe;
    private final ChargeRepository charges;

    public CheckoutService(StripeClient stripe, ChargeRepository charges) {
        this.stripe = stripe;
        this.charges = charges;
    }

    /** Idempotent per orderId: a retried checkout returns the existing charge instead of charging twice. */
    @Transactional
    public Charge createPayment(String orderId, long amountCents, String currency) {
        return charges.findByOrderId(orderId).orElseGet(() -> {
            PaymentIntentCreateParams params = PaymentIntentCreateParams.builder()
                    .setAmount(amountCents)
                    .setCurrency(currency.toLowerCase())
                    .addPaymentMethodType("card")
                    .putMetadata("order_id", orderId)
                    .build();
            PaymentIntent intent;
            try {
                intent = stripe.paymentIntents().create(params);
            } catch (StripeException e) {
                throw new CheckoutException(HttpStatus.BAD_GATEWAY, "Stripe charge failed", e);
            }
            ChargeStatus status = switch (intent.getStatus()) {
                case "succeeded" -> ChargeStatus.SUCCEEDED;
                case "requires_payment_method", "canceled" -> ChargeStatus.FAILED;
                default -> ChargeStatus.PENDING;
            };
            return charges.save(new Charge(orderId, PROVIDER, intent.getId(), amountCents, currency, status));
        });
    }

    public Charge getPaymentStatus(Long chargeId) {
        return charges.findById(chargeId)
                .orElseThrow(() -> new CheckoutException(HttpStatus.NOT_FOUND, "No charge " + chargeId, null));
    }

    @Transactional
    public Charge refundPayment(Long chargeId, Long requestedCents) {
        Charge charge = getPaymentStatus(chargeId);
        if (charge.getStatus() != ChargeStatus.SUCCEEDED && charge.getStatus() != ChargeStatus.PARTIALLY_REFUNDED) {
            throw new CheckoutException(HttpStatus.UNPROCESSABLE_ENTITY, "Charge not refundable: " + charge.getStatus(), null);
        }
        long cents = requestedCents != null ? requestedCents : charge.refundableCents();
        if (cents <= 0 || cents > charge.refundableCents()) {
            throw new CheckoutException(HttpStatus.UNPROCESSABLE_ENTITY, "Invalid refund amount " + cents, null);
        }
        try {
            stripe.refunds().create(RefundCreateParams.builder()
                    .setPaymentIntent(charge.getProviderChargeId())
                    .setAmount(cents)
                    .build());
        } catch (StripeException e) {
            throw new CheckoutException(HttpStatus.BAD_GATEWAY, "Stripe refund failed", e);
        }
        charge.recordRefund(cents);
        return charges.save(charge);
    }
}
