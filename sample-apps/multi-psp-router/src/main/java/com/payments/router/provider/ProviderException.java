package com.payments.router.provider;

public class ProviderException extends RuntimeException {
    public ProviderException(String provider, Throwable cause) {
        super(provider + " call failed: " + cause.getMessage(), cause);
    }
}
