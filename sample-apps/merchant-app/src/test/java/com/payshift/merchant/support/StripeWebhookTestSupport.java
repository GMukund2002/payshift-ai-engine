package com.payshift.merchant.support;

import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.InvalidKeyException;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;

/**
 * Builds Stripe-compatible webhook signature headers using the algorithm Stripe
 * documents (HMAC-SHA256 over "{timestamp}.{payload}"), so tests can exercise the
 * real Webhook.constructEvent verification path with both valid and tampered signatures.
 */
public final class StripeWebhookTestSupport {

    private StripeWebhookTestSupport() {
    }

    public static String sign(String payload, String secret, long timestampEpochSeconds) {
        String signedPayload = timestampEpochSeconds + "." + payload;
        String signature = hmacSha256Hex(secret, signedPayload);
        return "t=" + timestampEpochSeconds + ",v1=" + signature;
    }

    public static String sign(String payload, String secret) {
        return sign(payload, secret, System.currentTimeMillis() / 1000L);
    }

    private static String hmacSha256Hex(String secret, String data) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8), "HmacSHA256"));
            byte[] hash = mac.doFinal(data.getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(hash);
        } catch (NoSuchAlgorithmException | InvalidKeyException e) {
            throw new RuntimeException(e);
        }
    }
}
