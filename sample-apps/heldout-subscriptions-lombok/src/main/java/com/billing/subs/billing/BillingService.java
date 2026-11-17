package com.billing.subs.billing;

import com.billing.subs.subscription.Subscription;
import com.billing.subs.subscription.SubscriptionRepository;
import com.stripe.StripeClient;
import com.stripe.exception.StripeException;
import com.stripe.model.PaymentIntent;
import com.stripe.param.PaymentIntentCreateParams;
import com.stripe.param.RefundCreateParams;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

@Slf4j
@Service
@RequiredArgsConstructor
public class BillingService {

    private final StripeClient stripe;
    private final SubscriptionRepository subscriptions;

    @Transactional
    public Subscription createPayment(String email, String planCode, long amountCents, String currency) {
        try {
            PaymentIntent intent = stripe.paymentIntents().create(PaymentIntentCreateParams.builder()
                    .setAmount(amountCents).setCurrency(currency.toLowerCase())
                    .addPaymentMethodType("card").putMetadata("plan", planCode).setReceiptEmail(email).build());
            String state = "succeeded".equals(intent.getStatus()) ? "ACTIVE" : "PENDING_PAYMENT";
            log.info("Started {} subscription for {} via stripe ({})", planCode, email, intent.getId());
            return subscriptions.save(new Subscription(email, planCode, amountCents, currency, "stripe", intent.getId(), state));
        } catch (StripeException e) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Payment gateway error", e);
        }
    }

    public Subscription getPaymentStatus(Long id) {
        return subscriptions.findById(id).orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND));
    }

    @Transactional
    public Subscription refundPayment(Long id) {
        Subscription sub = getPaymentStatus(id);
        if (!"ACTIVE".equals(sub.getState())) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Only active subscriptions can be refunded");
        }
        try {
            stripe.refunds().create(RefundCreateParams.builder().setPaymentIntent(sub.getGatewayPaymentId()).build());
        } catch (StripeException e) {
            throw new ResponseStatusException(HttpStatus.BAD_GATEWAY, "Payment gateway error", e);
        }
        sub.markRefunded();
        return subscriptions.save(sub);
    }
}
