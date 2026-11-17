package com.ledger.invoices.payment;

public record InvoicePayment(String invoiceNo, long amountMinor, String currency, String psp, String pspReference,
                             String status) {
}
