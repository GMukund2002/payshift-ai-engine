package com.payments.router.provider;

import java.util.Set;

/** Provider-neutral port. Every PSP adapter implements this; the router picks one per currency. */
public interface PaymentProvider {

    record ProviderPayment(String providerPaymentId, String status) {
    }

    record ProviderRefund(String providerRefundId, String status) {
    }

    /** Stable id stored on every transaction, e.g. "stripe". */
    String id();

    Set<String> supportedCurrencies();

    ProviderPayment createPayment(String reference, long amountMinor, String currency);

    ProviderRefund refund(String providerPaymentId, long amountMinor);
}
