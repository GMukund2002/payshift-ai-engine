package com.ledger.invoices.web;

import com.ledger.invoices.payment.InvoicePayment;
import com.ledger.invoices.payment.InvoicePaymentService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Positive;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/invoices")
public class InvoicePaymentController {

    public record PayInvoice(@Positive long amountMinor, @NotBlank String currency) {
    }

    private final InvoicePaymentService service;

    public InvoicePaymentController(InvoicePaymentService service) {
        this.service = service;
    }

    @PostMapping("/{invoiceNo}/payment")
    @ResponseStatus(HttpStatus.CREATED)
    public InvoicePayment createPayment(@PathVariable String invoiceNo, @Valid @RequestBody PayInvoice req) {
        return service.createPayment(invoiceNo, req.amountMinor(), req.currency());
    }

    @GetMapping("/{invoiceNo}/payment")
    public InvoicePayment getPaymentStatus(@PathVariable String invoiceNo) {
        return service.getPaymentStatus(invoiceNo);
    }

    @PostMapping("/{invoiceNo}/refund")
    public InvoicePayment refundPayment(@PathVariable String invoiceNo) {
        return service.refundPayment(invoiceNo);
    }
}
