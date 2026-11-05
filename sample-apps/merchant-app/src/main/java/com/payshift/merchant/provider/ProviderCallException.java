package com.payshift.merchant.provider;

public class ProviderCallException extends RuntimeException {
    public ProviderCallException(String message, Throwable cause) {
        super(message, cause);
    }
}
