package com.acme.checkout.service;

import org.springframework.http.HttpStatus;

public class CheckoutException extends RuntimeException {
    private final HttpStatus status;

    public CheckoutException(HttpStatus status, String message, Throwable cause) {
        super(message, cause);
        this.status = status;
    }

    public HttpStatus getStatus() {
        return status;
    }
}
