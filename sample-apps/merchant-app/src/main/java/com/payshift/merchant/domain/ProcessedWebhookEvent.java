package com.payshift.merchant.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

import java.time.Instant;

/**
 * Records the provider event IDs we have already processed so a redelivered
 * webhook (Stripe retries on anything other than a 2xx) never re-fulfills an order.
 */
@Entity
@Table(name = "processed_webhook_events")
public class ProcessedWebhookEvent {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(unique = true)
    private String eventId;

    private String provider;

    private Instant processedAt;

    protected ProcessedWebhookEvent() {
    }

    public ProcessedWebhookEvent(String eventId, String provider) {
        this.eventId = eventId;
        this.provider = provider;
        this.processedAt = Instant.now();
    }

    public String getEventId() {
        return eventId;
    }

    public String getProvider() {
        return provider;
    }
}
