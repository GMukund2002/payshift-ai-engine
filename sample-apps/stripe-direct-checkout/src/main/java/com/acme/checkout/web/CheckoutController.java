package com.acme.checkout.web;

import com.acme.checkout.domain.Charge;
import com.acme.checkout.service.CheckoutException;
import com.acme.checkout.service.CheckoutService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Positive;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

@RestController
@RequestMapping("/checkout")
public class CheckoutController {

    public record CheckoutRequest(@NotBlank String orderId, @Positive long amountCents, @NotBlank String currency) {
    }

    public record RefundRequest(Long amountCents) {
    }

    public record ChargeView(Long id, String orderId, String provider, String providerChargeId, String status,
                             long amountCents, long refundedCents) {
        static ChargeView of(Charge c) {
            return new ChargeView(c.getId(), c.getOrderId(), c.getProvider(), c.getProviderChargeId(),
                    c.getStatus().name(), c.getAmountCents(), c.getRefundedCents());
        }
    }

    private final CheckoutService checkout;

    public CheckoutController(CheckoutService checkout) {
        this.checkout = checkout;
    }

    @PostMapping
    public ResponseEntity<ChargeView> createPayment(@Valid @RequestBody CheckoutRequest req) {
        Charge charge = checkout.createPayment(req.orderId(), req.amountCents(), req.currency());
        return ResponseEntity.status(HttpStatus.CREATED).body(ChargeView.of(charge));
    }

    @GetMapping("/{id}")
    public ChargeView getPaymentStatus(@PathVariable Long id) {
        return ChargeView.of(checkout.getPaymentStatus(id));
    }

    @PostMapping("/{id}/refund")
    public ChargeView refundPayment(@PathVariable Long id, @RequestBody(required = false) RefundRequest req) {
        return ChargeView.of(checkout.refundPayment(id, req == null ? null : req.amountCents()));
    }

    @ExceptionHandler(CheckoutException.class)
    public ResponseEntity<Map<String, String>> onError(CheckoutException e) {
        return ResponseEntity.status(e.getStatus()).body(Map.of("error", e.getMessage()));
    }
}
