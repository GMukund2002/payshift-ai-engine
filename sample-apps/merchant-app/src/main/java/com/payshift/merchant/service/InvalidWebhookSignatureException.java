package com.payshift.merchant.service;

public class InvalidWebhookSignatureException extends RuntimeException {
    public InvalidWebhookSignatureException(String message, Throwable cause) {
        super(message, cause);
    }
}
