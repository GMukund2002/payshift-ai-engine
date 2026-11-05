package com.example;

import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class OrderController {

    private final RazorpayPaymentService paymentService;

    public OrderController(RazorpayPaymentService paymentService) {
        this.paymentService = paymentService;
    }

    @PostMapping("/orders")
    public String createOrder() {
        return "ok";
    }
}
