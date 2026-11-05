package com.payshift.analyzer.registry;

import java.util.List;

/**
 * Deserialized from provider-signatures.json. This is detection EVIDENCE DATA, not
 * orchestration logic -- the signature registry only helps the analyzer explain why
 * it suspects a given provider is present (maven dependency / import / class-name hint
 * / API domain). It is intentionally data-driven and extensible: adding a new provider
 * never requires touching analyzer code, and the core PayShift AI engine never branches
 * on these ids beyond treating them as opaque evidence keys.
 */
public class ProviderSignature {
    public String id;
    public String displayName;
    public List<String> mavenGroupIds = List.of();
    public List<String> importPrefixes = List.of();
    public List<String> classNameHints = List.of();
    public List<String> apiDomains = List.of();
}
