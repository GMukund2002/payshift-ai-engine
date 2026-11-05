package com.payshift.merchant.controller;

import com.payshift.merchant.domain.Payment;
import com.payshift.merchant.domain.Refund;
import com.payshift.merchant.dto.CreatePaymentRequest;
import com.payshift.merchant.dto.PaymentResponse;
import com.payshift.merchant.dto.RefundRequest;
import com.payshift.merchant.dto.RefundResponse;
import com.payshift.merchant.service.PaymentService;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/payments")
public class PaymentController {

    private final PaymentService paymentService;

    public PaymentController(PaymentService paymentService) {
        this.paymentService = paymentService;
    }

    @PostMapping
    public ResponseEntity<PaymentResponse> createPayment(@Valid @RequestBody CreatePaymentRequest request) {
        Payment payment = paymentService.createPayment(
                request.orderReference(), request.amount(), request.currency(), request.idempotencyKey());
        return ResponseEntity.status(HttpStatus.CREATED).body(PaymentResponse.from(payment));
    }

    @GetMapping("/{providerPaymentId}")
    public ResponseEntity<PaymentResponse> getPaymentStatus(@PathVariable String providerPaymentId) {
        Payment payment = paymentService.getByProviderPaymentId(providerPaymentId);
        return ResponseEntity.ok(PaymentResponse.from(payment));
    }

    @PostMapping("/{providerPaymentId}/refunds")
    public ResponseEntity<RefundResponse> refundPayment(@PathVariable String providerPaymentId,
                                                          @RequestBody RefundRequest request) {
        Refund refund = paymentService.refund(providerPaymentId, request.amount());
        return ResponseEntity.status(HttpStatus.CREATED).body(RefundResponse.from(refund));
    }
}
