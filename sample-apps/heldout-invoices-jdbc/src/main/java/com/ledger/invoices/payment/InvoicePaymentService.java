package com.ledger.invoices.payment;

import com.ledger.invoices.gateway.StripeGateway;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

@Service
public class InvoicePaymentService {

    private final StripeGateway stripe;
    private final InvoicePaymentDao payments;

    public InvoicePaymentService(StripeGateway stripe, InvoicePaymentDao payments) {
        this.stripe = stripe;
        this.payments = payments;
    }

    @Transactional
    public InvoicePayment createPayment(String invoiceNo, long amountMinor, String currency) {
        return payments.find(invoiceNo).orElseGet(() -> {
            StripeGateway.Charge charge = stripe.charge(invoiceNo, amountMinor, currency);
            InvoicePayment payment = new InvoicePayment(invoiceNo, amountMinor, currency, "stripe", charge.reference(),
                    "succeeded".equals(charge.status()) ? "PAID" : "PENDING");
            payments.insert(payment);
            return payment;
        });
    }

    public InvoicePayment getPaymentStatus(String invoiceNo) {
        return payments.find(invoiceNo).orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND));
    }

    @Transactional
    public InvoicePayment refundPayment(String invoiceNo) {
        InvoicePayment payment = getPaymentStatus(invoiceNo);
        if (!"PAID".equals(payment.status())) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Invoice is not paid");
        }
        stripe.refund(payment.pspReference());
        payments.updateStatus(invoiceNo, "REFUNDED");
        return getPaymentStatus(invoiceNo);
    }
}
