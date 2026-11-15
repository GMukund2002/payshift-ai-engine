package com.acme.checkout.repository;

import com.acme.checkout.domain.Charge;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface ChargeRepository extends JpaRepository<Charge, Long> {
    Optional<Charge> findByOrderId(String orderId);
}
