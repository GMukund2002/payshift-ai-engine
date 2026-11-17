package com.store.front.config;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.web.client.RestTemplateBuilder;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.client.RestTemplate;

@Configuration
public class HttpConfig {

    /** The application's only RestTemplate today -- injected by type, without a qualifier. */
    @Bean
    public RestTemplate paypalRestTemplate(RestTemplateBuilder builder,
                                           @Value("${store.paypal.base-url}") String baseUrl,
                                           @Value("${store.paypal.client-id}") String clientId,
                                           @Value("${store.paypal.client-secret}") String clientSecret) {
        return builder.rootUri(baseUrl).basicAuthentication(clientId, clientSecret).build();
    }
}
