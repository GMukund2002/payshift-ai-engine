package com.payshift.analyzer.check;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.dataformat.yaml.YAMLFactory;
import com.fasterxml.jackson.dataformat.yaml.YAMLParser;
import com.fasterxml.jackson.databind.MappingIterator;

import java.io.IOException;
import java.io.Reader;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.HashSet;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.Properties;
import java.util.Set;
import java.util.stream.Stream;

/**
 * The set of configuration keys a Spring Boot project defines in its
 * application.yml / application.yaml / application.properties files, normalized
 * the way Spring's relaxed binding compares them (case-insensitive, ignoring
 * '-' and '_'), so "payshift.razorpay.key-id" and "payshift.razorpay.keyId" match.
 *
 * Keys are tracked per source so the placeholder check can tell "defined for
 * real" (main, default profile) apart from "only defined in a profile-specific
 * or test config", which doesn't help a production startup.
 */
final class SpringConfigKeys {

    final Set<String> mainDefault = new HashSet<>();
    final Set<String> mainProfileOnly = new HashSet<>();
    final Set<String> testOnly = new HashSet<>();
    final List<String> errors = new java.util.ArrayList<>();

    /** Reads every module's src/main/resources and src/test/resources (multi-module aware). */
    static SpringConfigKeys load(Path repositoryRoot) {
        SpringConfigKeys keys = new SpringConfigKeys();
        Set<String> testKeys = new HashSet<>();
        List<Path> resourceDirs;
        try (Stream<Path> paths = Files.walk(repositoryRoot)) {
            resourceDirs = paths.filter(Files::isDirectory)
                    .filter(p -> !com.payshift.analyzer.pom.PomAnalyzer.isUnderBuildOutputDir(repositoryRoot, p.resolve("x")))
                    .filter(p -> {
                        String rel = repositoryRoot.relativize(p).toString().replace('\\', '/');
                        return rel.endsWith("src/main/resources") || rel.endsWith("src/test/resources");
                    })
                    .toList();
        } catch (IOException e) {
            keys.errors.add("Could not walk " + repositoryRoot + ": " + e.getMessage());
            return keys;
        }
        for (Path dir : resourceDirs) {
            if (dir.toString().replace('\\', '/').endsWith("src/main/resources")) {
                keys.loadDir(dir, keys.mainDefault, keys.mainProfileOnly);
            } else {
                keys.loadDir(dir, testKeys, testKeys);
            }
        }
        testKeys.removeAll(keys.mainDefault);
        keys.testOnly.addAll(testKeys);
        return keys;
    }

    static String normalize(String key) {
        return key.toLowerCase(java.util.Locale.ROOT).replace("-", "").replace("_", "");
    }

    private void loadDir(Path dir, Set<String> defaults, Set<String> profiles) {
        if (!Files.isDirectory(dir)) return;
        try (Stream<Path> files = Files.list(dir)) {
            for (Path f : files.toList()) {
                String name = f.getFileName().toString();
                if (!name.startsWith("application")) continue;
                boolean isDefault = name.equals("application.yml") || name.equals("application.yaml")
                        || name.equals("application.properties");
                Set<String> target = isDefault ? defaults : profiles;
                if (name.endsWith(".yml") || name.endsWith(".yaml")) {
                    loadYaml(f, target);
                } else if (name.endsWith(".properties")) {
                    loadProperties(f, target);
                }
            }
        } catch (IOException e) {
            errors.add("Could not list " + dir + ": " + e.getMessage());
        }
    }

    private void loadYaml(Path file, Set<String> target) {
        ObjectMapper mapper = new ObjectMapper(new YAMLFactory());
        try (Reader r = Files.newBufferedReader(file);
             YAMLParser parser = new YAMLFactory().createParser(r)) {
            // A YAML file can hold several documents separated by "---".
            MappingIterator<JsonNode> docs = mapper.readValues(parser, JsonNode.class);
            while (docs.hasNext()) {
                flatten("", docs.next(), target);
            }
        } catch (Exception e) {
            errors.add("Could not parse " + file + ": " + e.getMessage());
        }
    }

    private void loadProperties(Path file, Set<String> target) {
        Properties p = new Properties();
        try (Reader r = Files.newBufferedReader(file)) {
            p.load(r);
            for (String k : p.stringPropertyNames()) {
                addWithParents(k, target);
            }
        } catch (IOException e) {
            errors.add("Could not read " + file + ": " + e.getMessage());
        }
    }

    private static void flatten(String prefix, JsonNode node, Set<String> target) {
        if (node == null) return;
        if (node.isObject()) {
            if (!prefix.isEmpty()) target.add(normalize(prefix));
            Iterator<Map.Entry<String, JsonNode>> fields = node.fields();
            while (fields.hasNext()) {
                Map.Entry<String, JsonNode> e = fields.next();
                flatten(prefix.isEmpty() ? e.getKey() : prefix + "." + e.getKey(), e.getValue(), target);
            }
        } else if (node.isArray()) {
            target.add(normalize(prefix));
            for (int i = 0; i < node.size(); i++) {
                flatten(prefix + "[" + i + "]", node.get(i), target);
            }
        } else if (!prefix.isEmpty()) {
            target.add(normalize(prefix));
        }
    }

    private static void addWithParents(String key, Set<String> target) {
        target.add(normalize(key));
    }
}
