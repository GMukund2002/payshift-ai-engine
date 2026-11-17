package com.store.front.orders;

import com.store.front.paypal.PaypalClient;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import java.math.BigDecimal;

@Service
public class PurchaseService {

    private final PaypalClient paypal;
    private final PurchaseRepository purchases;

    public PurchaseService(PaypalClient paypal, PurchaseRepository purchases) {
        this.paypal = paypal;
        this.purchases = purchases;
    }

    @Transactional
    public Purchase createPayment(String reference, BigDecimal amount, String currency) {
        return purchases.findByReference(reference).orElseGet(() -> {
            PaypalClient.PaypalOrder order = paypal.createOrder(reference, amount, currency);
            return purchases.save(new Purchase(reference, amount, currency, "paypal", order.id(), order.status()));
        });
    }

    public Purchase getPaymentStatus(String reference) {
        return purchases.findByReference(reference)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND));
    }

    @Transactional
    public Purchase refundPayment(String reference) {
        Purchase purchase = getPaymentStatus(reference);
        if (!"COMPLETED".equals(purchase.getStatus())) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "Purchase is not completed");
        }
        paypal.refundCapture(purchase.getProcessorOrderId(), purchase.getAmount(), purchase.getCurrency());
        purchase.markRefunded();
        return purchases.save(purchase);
    }
}
