package com.payshift.merchant.repository;

import com.payshift.merchant.domain.Order;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface OrderRepository extends JpaRepository<Order, Long> {
    Optional<Order> findByOrderReference(String orderReference);
}
