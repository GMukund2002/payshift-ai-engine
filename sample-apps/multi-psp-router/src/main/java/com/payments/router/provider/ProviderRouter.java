package com.payments.router.provider;

import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Optional;

/** Picks the provider for a NEW payment by currency, and resolves the owner of an EXISTING one by id. */
@Component
public class ProviderRouter {

    private final List<PaymentProvider> providers;

    public ProviderRouter(List<PaymentProvider> providers) {
        this.providers = providers;
    }

    public Optional<PaymentProvider> forCurrency(String currency) {
        return providers.stream().filter(p -> p.supportedCurrencies().contains(currency.toUpperCase())).findFirst();
    }

    public PaymentProvider byId(String providerId) {
        return providers.stream().filter(p -> p.id().equals(providerId)).findFirst()
                .orElseThrow(() -> new IllegalStateException("No provider registered with id " + providerId));
    }
}
