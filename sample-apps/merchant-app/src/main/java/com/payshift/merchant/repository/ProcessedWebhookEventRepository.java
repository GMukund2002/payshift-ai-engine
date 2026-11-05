package com.payshift.merchant.repository;

import com.payshift.merchant.domain.ProcessedWebhookEvent;
import org.springframework.data.jpa.repository.JpaRepository;

public interface ProcessedWebhookEventRepository extends JpaRepository<ProcessedWebhookEvent, Long> {
    boolean existsByEventId(String eventId);
}
