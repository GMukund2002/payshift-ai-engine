package com.payshift.analyzer.model;

public class PaymentOperation {
    public String operation; // CREATE_PAYMENT, GET_PAYMENT_STATUS, CREATE_REFUND, HANDLE_WEBHOOK, VERIFY_WEBHOOK_SIGNATURE
    public String sourceFile;
    public String className;
    public String method;
    public String provider; // nullable if provider could not be determined

    public PaymentOperation() {
    }

    public PaymentOperation(String operation, String sourceFile, String className, String method, String provider) {
        this.operation = operation;
        this.sourceFile = sourceFile;
        this.className = className;
        this.method = method;
        this.provider = provider;
    }
}
