package com.payments.router.web;

import com.payments.router.domain.Transaction;
import com.payments.router.service.PaymentService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Positive;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/payments")
public class PaymentController {

    public record PayRequest(@NotBlank String reference, @Positive long amountMinor, @NotBlank String currency) {
    }

    public record RefundRequest(Long amountMinor) {
    }

    private final PaymentService payments;

    public PaymentController(PaymentService payments) {
        this.payments = payments;
    }

    @PostMapping
    public ResponseEntity<Transaction> createPayment(@Valid @RequestBody PayRequest req) {
        return ResponseEntity.status(HttpStatus.CREATED)
                .body(payments.createPayment(req.reference(), req.amountMinor(), req.currency()));
    }

    @GetMapping("/{reference}")
    public Transaction getPaymentStatus(@PathVariable String reference) {
        return payments.getPaymentStatus(reference);
    }

    @PostMapping("/{reference}/refunds")
    public Transaction refundPayment(@PathVariable String reference, @RequestBody(required = false) RefundRequest req) {
        return payments.refundPayment(reference, req == null ? null : req.amountMinor());
    }
}
