package com.payshift.analyzer.model;

import java.util.ArrayList;
import java.util.List;
import java.util.Objects;

/**
 * A provider identity the analyzer believes is present, with the raw evidence
 * that led to that conclusion. "confidence" is deliberately exposed so downstream
 * LLM reasoning can treat low-confidence matches with skepticism instead of the
 * analyzer silently forcing a classification it isn't sure of.
 */
public class DetectedProvider {
    public String name;
    public String confidence; // HIGH, MEDIUM, LOW
    public List<String> evidence = new ArrayList<>();

    public DetectedProvider() {
    }

    public DetectedProvider(String name) {
        this.name = name;
    }

    public void addEvidence(String item) {
        if (!evidence.contains(item)) {
            evidence.add(item);
        }
    }

    public void recomputeConfidence() {
        long distinctKinds = evidence.stream().map(e -> e.split(":")[0]).distinct().count();
        if (distinctKinds >= 2 || evidence.size() >= 3) {
            confidence = "HIGH";
        } else if (evidence.size() >= 1) {
            confidence = "MEDIUM";
        } else {
            confidence = "LOW";
        }
    }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (!(o instanceof DetectedProvider that)) return false;
        return Objects.equals(name, that.name);
    }

    @Override
    public int hashCode() {
        return Objects.hash(name);
    }
}
