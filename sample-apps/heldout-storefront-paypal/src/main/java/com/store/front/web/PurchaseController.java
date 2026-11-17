package com.store.front.web;

import com.store.front.orders.Purchase;
import com.store.front.orders.PurchaseService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Positive;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

import java.math.BigDecimal;

@RestController
@RequestMapping("/purchases")
public class PurchaseController {

    public record BuyRequest(@NotBlank String reference, @NotNull @Positive BigDecimal amount, @NotBlank String currency) {
    }

    private final PurchaseService purchases;

    public PurchaseController(PurchaseService purchases) {
        this.purchases = purchases;
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public Purchase createPayment(@Valid @RequestBody BuyRequest req) {
        return purchases.createPayment(req.reference(), req.amount(), req.currency());
    }

    @GetMapping("/{reference}")
    public Purchase getPaymentStatus(@PathVariable String reference) {
        return purchases.getPaymentStatus(reference);
    }

    @PostMapping("/{reference}/refund")
    public Purchase refundPayment(@PathVariable String reference) {
        return purchases.refundPayment(reference);
    }
}
