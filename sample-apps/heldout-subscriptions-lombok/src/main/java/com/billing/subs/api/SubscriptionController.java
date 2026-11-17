package com.billing.subs.api;

import com.billing.subs.billing.BillingService;
import com.billing.subs.subscription.Subscription;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Positive;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/subscriptions")
@RequiredArgsConstructor
public class SubscriptionController {

    public record StartRequest(@Email String email, @NotBlank String planCode, @Positive long amountCents,
                               @NotBlank String currency) {
    }

    private final BillingService billing;

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public Subscription createPayment(@Valid @RequestBody StartRequest req) {
        return billing.createPayment(req.email(), req.planCode(), req.amountCents(), req.currency());
    }

    @GetMapping("/{id}")
    public Subscription getPaymentStatus(@PathVariable Long id) {
        return billing.getPaymentStatus(id);
    }

    @PostMapping("/{id}/refund")
    public Subscription refundPayment(@PathVariable Long id) {
        return billing.refundPayment(id);
    }
}
