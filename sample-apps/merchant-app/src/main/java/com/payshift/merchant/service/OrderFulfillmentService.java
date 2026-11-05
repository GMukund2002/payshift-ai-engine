package com.payshift.merchant.service;

import com.payshift.merchant.domain.Order;
import com.payshift.merchant.repository.OrderRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class OrderFulfillmentService {

    private static final Logger log = LoggerFactory.getLogger(OrderFulfillmentService.class);

    private final OrderRepository orderRepository;

    public OrderFulfillmentService(OrderRepository orderRepository) {
        this.orderRepository = orderRepository;
    }

    /**
     * Idempotent: fulfilling an already-fulfilled order is a no-op. This is the
     * invariant that protects against double fulfillment from a duplicate webhook.
     */
    @Transactional
    public boolean fulfill(Long orderId) {
        Order order = orderRepository.findById(orderId)
                .orElseThrow(() -> new IllegalStateException("Order not found: " + orderId));
        boolean fulfilledNow = order.markFulfilled();
        orderRepository.save(order);
        if (fulfilledNow) {
            log.info("Order {} fulfilled", order.getOrderReference());
        } else {
            log.info("Order {} was already fulfilled; skipping", order.getOrderReference());
        }
        return fulfilledNow;
    }
}
