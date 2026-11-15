package com.payments.router.config;

import com.stripe.StripeClient;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.client.RestClient;

@Configuration
public class ProviderClientsConfig {

    @Bean
    public StripeClient stripeClient(@Value("${payments.stripe.secret-key}") String secretKey) {
        return new StripeClient(secretKey);
    }

    @Bean
    public RestClient paypalRestClient(RestClient.Builder builder,
                                       @Value("${payments.paypal.base-url}") String baseUrl,
                                       @Value("${payments.paypal.client-id}") String clientId,
                                       @Value("${payments.paypal.client-secret}") String clientSecret) {
        return builder.baseUrl(baseUrl)
                .defaultHeaders(h -> h.setBasicAuth(clientId, clientSecret))
                .build();
    }
}
