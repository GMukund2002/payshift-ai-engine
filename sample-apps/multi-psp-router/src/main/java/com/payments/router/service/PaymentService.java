package com.payments.router.service;

import com.payments.router.domain.Transaction;
import com.payments.router.domain.TransactionRepository;
import com.payments.router.provider.PaymentProvider;
import com.payments.router.provider.ProviderRouter;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

@Service
public class PaymentService {

    private final ProviderRouter router;
    private final TransactionRepository transactions;

    public PaymentService(ProviderRouter router, TransactionRepository transactions) {
        this.router = router;
        this.transactions = transactions;
    }

    @Transactional
    public Transaction createPayment(String reference, long amountMinor, String currency) {
        return transactions.findByReference(reference).orElseGet(() -> {
            PaymentProvider provider = router.forCurrency(currency).orElseThrow(() ->
                    new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY, "No provider supports " + currency));
            PaymentProvider.ProviderPayment p = provider.createPayment(reference, amountMinor, currency);
            return transactions.save(new Transaction(reference, provider.id(), p.providerPaymentId(), amountMinor,
                    currency.toUpperCase(), p.status()));
        });
    }

    public Transaction getPaymentStatus(String reference) {
        return transactions.findByReference(reference)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND));
    }

    @Transactional
    public Transaction refundPayment(String reference, Long amountMinor) {
        Transaction tx = getPaymentStatus(reference);
        long amount = amountMinor != null ? amountMinor : tx.getAmountMinor() - tx.getRefundedMinor();
        if (amount <= 0 || amount > tx.getAmountMinor() - tx.getRefundedMinor()) {
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY, "Invalid refund amount");
        }
        router.byId(tx.getProviderId()).refund(tx.getProviderPaymentId(), amount);
        tx.recordRefund(amount);
        return transactions.save(tx);
    }
}
