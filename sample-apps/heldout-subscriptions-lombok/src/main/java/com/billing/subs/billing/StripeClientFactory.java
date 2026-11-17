package com.billing.subs.billing;

import com.stripe.StripeClient;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class StripeClientFactory {

    @Bean
    StripeClient stripeClient(@Value("${billing.stripe.secret-key}") String secretKey) {
        return new StripeClient(secretKey);
    }
}
