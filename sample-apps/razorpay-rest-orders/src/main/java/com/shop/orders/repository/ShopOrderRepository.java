package com.shop.orders.repository;

import com.shop.orders.domain.ShopOrder;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface ShopOrderRepository extends JpaRepository<ShopOrder, Long> {
    Optional<ShopOrder> findByReceipt(String receipt);

    Optional<ShopOrder> findByProviderOrderId(String providerOrderId);
}
