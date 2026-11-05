package com.payshift.merchant.controller;

import com.payshift.merchant.service.WebhookService;
import com.stripe.model.Event;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/webhooks")
public class WebhookController {

    private final WebhookService webhookService;

    public WebhookController(WebhookService webhookService) {
        this.webhookService = webhookService;
    }

    @PostMapping("/stripe")
    public ResponseEntity<String> handleStripeWebhook(@RequestBody String payload,
                                                        @RequestHeader("Stripe-Signature") String signatureHeader) {
        Event event = webhookService.verifySignature(payload, signatureHeader);
        boolean processed = webhookService.processEvent(event, payload);
        return ResponseEntity.ok(processed ? "processed" : "duplicate_ignored");
    }
}
