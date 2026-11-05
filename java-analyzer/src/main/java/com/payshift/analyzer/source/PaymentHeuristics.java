package com.payshift.analyzer.source;

import java.util.regex.Pattern;

/**
 * Naming heuristics used to decide whether a class or method is payment-related.
 * Purely syntactic/name-based (no symbol resolution), which is a documented
 * limitation: a class that is payment-related but named unconventionally will be
 * missed rather than guessed at.
 */
final class PaymentHeuristics {

    private PaymentHeuristics() {
    }

    static final Pattern PAYMENT_RELATED_NAME = Pattern.compile(
            "(?i)payment|charge|refund|webhook|checkout|psp|provider|gateway|invoice|transaction");

    static final Pattern CREATE_PAYMENT = Pattern.compile("(?i)^(create|initiate|start|process)(payment|charge)(intent)?$");
    static final Pattern GET_STATUS = Pattern.compile("(?i)^(get|fetch|retrieve)(payment)?status$");
    // Requires "refund" to be the head verb (after an optional action prefix), not merely
    // present anywhere -- excludes plain accessors like getRefundedAmount/getRefundableAmount.
    static final Pattern CREATE_REFUND = Pattern.compile("(?i)^(create|process|initiate|issue|apply|do|cancel)?refund[a-z]*$");
    static final Pattern VERIFY_SIGNATURE = Pattern.compile("(?i)verify.*signature|validate.*signature");
    static final Pattern HANDLE_WEBHOOK = Pattern.compile("(?i)webhook|handle.*event|process.*event");
    // Same head-verb requirement -- excludes plain accessors like getFulfilledAt/isFulfilled.
    static final Pattern FULFILL_ORDER = Pattern.compile("(?i)^(mark|do|process)?fulfill(ment)?(ed)?(order)?$");

    static boolean isPaymentRelatedName(String name) {
        return name != null && PAYMENT_RELATED_NAME.matcher(name).find();
    }
}
