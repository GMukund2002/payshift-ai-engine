package com.payshift.analyzer.registry;

import com.fasterxml.jackson.databind.ObjectMapper;

import java.io.IOException;
import java.io.InputStream;
import java.util.List;
import java.util.Map;

public class ProviderRegistry {

    private final List<ProviderSignature> signatures;

    private ProviderRegistry(List<ProviderSignature> signatures) {
        this.signatures = signatures;
    }

    @SuppressWarnings("unchecked")
    public static ProviderRegistry loadDefault() {
        try (InputStream in = ProviderRegistry.class.getResourceAsStream("/provider-signatures.json")) {
            if (in == null) {
                throw new IllegalStateException("provider-signatures.json not found on classpath");
            }
            ObjectMapper mapper = new ObjectMapper();
            Map<String, Object> root = mapper.readValue(in, Map.class);
            List<Map<String, Object>> raw = (List<Map<String, Object>>) root.get("providers");
            List<ProviderSignature> parsed = raw.stream().map(m -> {
                ProviderSignature sig = new ProviderSignature();
                sig.id = (String) m.get("id");
                sig.displayName = (String) m.get("displayName");
                sig.mavenGroupIds = (List<String>) m.getOrDefault("mavenGroupIds", List.of());
                sig.importPrefixes = (List<String>) m.getOrDefault("importPrefixes", List.of());
                sig.classNameHints = (List<String>) m.getOrDefault("classNameHints", List.of());
                sig.apiDomains = (List<String>) m.getOrDefault("apiDomains", List.of());
                return sig;
            }).toList();
            return new ProviderRegistry(parsed);
        } catch (IOException e) {
            throw new RuntimeException("Failed to load provider signature registry", e);
        }
    }

    public List<ProviderSignature> all() {
        return signatures;
    }

    public ProviderSignature matchByGroupId(String groupId) {
        if (groupId == null) return null;
        return signatures.stream().filter(s -> s.mavenGroupIds.stream().anyMatch(groupId::equals)).findFirst().orElse(null);
    }

    public ProviderSignature matchByImport(String importName) {
        if (importName == null) return null;
        return signatures.stream()
                .filter(s -> s.importPrefixes.stream().anyMatch(importName::startsWith))
                .findFirst().orElse(null);
    }

    public ProviderSignature matchByClassNameHint(String simpleClassOrTypeName) {
        if (simpleClassOrTypeName == null) return null;
        return signatures.stream()
                .filter(s -> s.classNameHints.stream().anyMatch(simpleClassOrTypeName::contains))
                .findFirst().orElse(null);
    }

    public ProviderSignature matchByDomain(String urlOrLiteral) {
        if (urlOrLiteral == null) return null;
        return signatures.stream()
                .filter(s -> s.apiDomains.stream().anyMatch(urlOrLiteral::contains))
                .findFirst().orElse(null);
    }
}
