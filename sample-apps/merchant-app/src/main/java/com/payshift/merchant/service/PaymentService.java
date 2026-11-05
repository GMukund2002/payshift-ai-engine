package com.payshift.merchant.service;

import com.payshift.merchant.domain.Order;
import com.payshift.merchant.domain.Payment;
import com.payshift.merchant.domain.PaymentStatus;
import com.payshift.merchant.domain.Refund;
import com.payshift.merchant.provider.StripePaymentGateway;
import com.payshift.merchant.repository.OrderRepository;
import com.payshift.merchant.repository.PaymentRepository;
import com.payshift.merchant.repository.RefundRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;

/**
 * Existing (pre-PayShift) payment service. Deliberately coupled directly to the
 * Stripe gateway with no provider abstraction -- this is the "before" state the
 * repository analyzer is expected to detect (architecture.provider_abstraction_exists = false).
 */
@Service
public class PaymentService {

    private static final String PROVIDER_ID = "stripe";

    private final PaymentRepository paymentRepository;
    private final OrderRepository orderRepository;
    private final RefundRepository refundRepository;
    private final StripePaymentGateway stripeGateway;

    public PaymentService(PaymentRepository paymentRepository,
                           OrderRepository orderRepository,
                           RefundRepository refundRepository,
                           StripePaymentGateway stripeGateway) {
        this.paymentRepository = paymentRepository;
        this.orderRepository = orderRepository;
        this.refundRepository = refundRepository;
        this.stripeGateway = stripeGateway;
    }

    @Transactional
    public Payment createPayment(String orderReference, BigDecimal amount, String currency, String idempotencyKey) {
        return paymentRepository.findByIdempotencyKey(idempotencyKey)
                .orElseGet(() -> {
                    Order order = orderRepository.findByOrderReference(orderReference)
                            .orElseGet(() -> orderRepository.save(new Order(orderReference, amount, currency)));

                    StripePaymentGateway.ProviderPaymentResult result =
                            stripeGateway.createPaymentIntent(orderReference, amount, currency);

                    PaymentStatus status = "succeeded".equals(result.status())
                            ? PaymentStatus.SUCCEEDED
                            : "requires_payment_method".equals(result.status()) || "canceled".equals(result.status())
                                ? PaymentStatus.FAILED
                                : PaymentStatus.REQUIRES_ACTION;

                    Payment payment = new Payment(order.getId(), PROVIDER_ID, result.providerPaymentId(),
                            idempotencyKey, amount, currency, status);
                    return paymentRepository.save(payment);
                });
    }

    public Payment getByProviderPaymentId(String providerPaymentId) {
        return paymentRepository.findByProviderPaymentId(providerPaymentId)
                .orElseThrow(() -> new PaymentNotFoundException("No payment for provider payment id " + providerPaymentId));
    }

    @Transactional
    public Refund refund(String providerPaymentId, BigDecimal requestedAmount) {
        Payment payment = getByProviderPaymentId(providerPaymentId);

        if (payment.getStatus() != PaymentStatus.SUCCEEDED && payment.getStatus() != PaymentStatus.PARTIALLY_REFUNDED) {
            throw new InvalidRefundException("Cannot refund a payment that has not succeeded: " + payment.getStatus());
        }

        BigDecimal amount = requestedAmount != null ? requestedAmount : payment.getRefundableAmount();
        if (amount.signum() <= 0) {
            throw new InvalidRefundException("Refund amount must be positive");
        }
        if (amount.compareTo(payment.getRefundableAmount()) > 0) {
            throw new InvalidRefundException("Refund amount exceeds refundable balance");
        }

        // Refund ownership: always route to the provider that created the original
        // payment, never whatever provider is currently the default.
        StripePaymentGateway.ProviderRefundResult result = stripeGateway.createRefund(providerPaymentId, amount);

        payment.applyRefund(amount);
        paymentRepository.save(payment);

        Refund refund = new Refund(payment.getId(), payment.getProvider(), result.providerRefundId(), amount);
        return refundRepository.save(refund);
    }
}
