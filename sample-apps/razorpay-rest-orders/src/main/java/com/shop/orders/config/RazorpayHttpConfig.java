package com.shop.orders.config;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.client.RestClient;

@Configuration
public class RazorpayHttpConfig {

    @Bean
    public RestClient razorpayRestClient(RestClient.Builder builder,
                                         @Value("${shop.razorpay.base-url}") String baseUrl,
                                         @Value("${shop.razorpay.key-id}") String keyId,
                                         @Value("${shop.razorpay.key-secret}") String keySecret) {
        return builder.baseUrl(baseUrl)
                .defaultHeaders(headers -> headers.setBasicAuth(keyId, keySecret))
                .build();
    }
}
