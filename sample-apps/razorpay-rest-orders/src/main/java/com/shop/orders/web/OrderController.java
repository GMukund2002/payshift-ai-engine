package com.shop.orders.web;

import com.shop.orders.domain.ShopOrder;
import com.shop.orders.payments.OrderPaymentService;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Positive;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api")
public class OrderController {

    public record CreateOrder(@NotBlank String receipt, @Positive long amountPaise, @NotBlank String currency) {
    }

    public record OrderView(Long id, String receipt, String provider, String providerOrderId, String state) {
        static OrderView of(ShopOrder o) {
            return new OrderView(o.getId(), o.getReceipt(), o.getProvider(), o.getProviderOrderId(), o.getState().name());
        }
    }

    private final OrderPaymentService payments;

    public OrderController(OrderPaymentService payments) {
        this.payments = payments;
    }

    @PostMapping("/orders")
    public ResponseEntity<OrderView> createPayment(@Valid @RequestBody CreateOrder req) {
        return ResponseEntity.status(HttpStatus.CREATED)
                .body(OrderView.of(payments.createPayment(req.receipt(), req.amountPaise(), req.currency())));
    }

    @GetMapping("/orders/{id}")
    public OrderView getPaymentStatus(@PathVariable Long id) {
        return OrderView.of(payments.getPaymentStatus(id));
    }

    @PostMapping("/orders/{id}/refund")
    public OrderView refundPayment(@PathVariable Long id) {
        return OrderView.of(payments.refundPayment(id));
    }

    @PostMapping("/webhooks/razorpay")
    public ResponseEntity<String> handleWebhook(@RequestBody String body,
                                                @RequestHeader(value = "X-Razorpay-Signature", required = false) String signature,
                                                @RequestHeader(value = "X-Razorpay-Event-Id", required = false) String eventId) {
        return ResponseEntity.ok(payments.handleWebhook(body, signature, eventId) ? "processed" : "duplicate");
    }
}
