package com.payshift.analyzer;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.payshift.analyzer.check.WiringChecker;
import com.payshift.analyzer.model.AnalysisReport;
import com.payshift.analyzer.model.MavenDependency;
import com.payshift.analyzer.pom.PomAnalyzer;
import com.payshift.analyzer.registry.ProviderRegistry;
import com.payshift.analyzer.source.JavaSourceAnalyzer;

import java.io.PrintStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

/**
 * CLI / subprocess entry point for the PayShift repository analyzer.
 *
 * Usage:
 *   java -jar java-analyzer.jar <repository-path> [--output report.json]
 *   java -jar java-analyzer.jar <repository-path> --check-wiring [--changed a.java,b.java] [--output out.json]
 *
 * The first form is repository analysis (providers, payment classes/operations,
 * architecture). The second runs the deterministic Spring wiring / stub checks
 * (see {@link WiringChecker}) and reports findings for the listed changed files.
 *
 * Always prints exactly one JSON document to stdout (or to --output if given) and
 * nothing else, so a parent process (the Python AI engine) can capture it reliably.
 * Exit code 0 means analysis completed (possibly with partial errors reported
 * inside the "errors" field); exit code 1 means the repository path was invalid.
 */
public class Main {

    public static void main(String[] args) throws Exception {
        if (args.length < 1) {
            System.err.println("Usage: java -jar java-analyzer.jar <repository-path> [--output report.json] "
                    + "[--check-wiring [--changed a.java,b.java]]");
            System.exit(1);
        }

        Path repoPath = Path.of(args[0]).toAbsolutePath().normalize();
        if (!Files.isDirectory(repoPath)) {
            System.err.println("Not a directory: " + repoPath);
            System.exit(1);
        }

        String outputFile = null;
        boolean checkWiring = false;
        Set<String> changed = new LinkedHashSet<>();
        for (int i = 1; i < args.length; i++) {
            if ("--output".equals(args[i]) && i + 1 < args.length) {
                outputFile = args[i + 1];
            } else if ("--check-wiring".equals(args[i])) {
                checkWiring = true;
            } else if ("--changed".equals(args[i]) && i + 1 < args.length) {
                for (String f : args[i + 1].split(",")) {
                    if (!f.isBlank()) changed.add(f.trim());
                }
            }
        }

        if (checkWiring) {
            WiringChecker.Report wiring = new WiringChecker().check(repoPath, changed);
            emit(new ObjectMapper().enable(SerializationFeature.INDENT_OUTPUT).writeValueAsString(wiring), outputFile);
            return;
        }

        AnalysisReport report = new AnalysisReport();
        report.repositoryPath = repoPath.toString();

        List<MavenDependency> dependencies = new PomAnalyzer().findDependencies(repoPath);
        report.dependencies = dependencies;

        ProviderRegistry registry = ProviderRegistry.loadDefault();
        JavaSourceAnalyzer.Result sourceResult = new JavaSourceAnalyzer(registry).analyze(repoPath);

        report.detectedProviders = new ArrayList<>(sourceResult.detectedProviders);
        report.paymentClasses = sourceResult.paymentClasses;
        report.paymentOperations = sourceResult.paymentOperations;
        report.architecture = sourceResult.architecture;
        report.errors = sourceResult.errors;

        // Maven-dependency evidence is folded in after source scanning so a provider
        // can be detected purely from its POM entry even with zero source usage yet.
        for (MavenDependency dep : dependencies) {
            var sig = registry.matchByMavenDependency(dep.groupId, dep.artifactId);
            if (sig != null) {
                var existing = report.detectedProviders.stream()
                        .filter(p -> p.name.equals(sig.id)).findFirst();
                var dp = existing.orElseGet(() -> {
                    var created = new com.payshift.analyzer.model.DetectedProvider(sig.id);
                    report.detectedProviders.add(created);
                    return created;
                });
                dp.addEvidence("maven_dependency: " + dep.groupId + ":" + dep.artifactId
                        + (dep.version != null ? ":" + dep.version : ""));
                dp.recomputeConfidence();
            }
        }

        // Provider API hosts configured in Spring config (e.g. a base-url property for a
        // REST client) -- the usual place a no-SDK integration puts the endpoint.
        for (String[] hit : configEndpointHits(repoPath, registry)) {
            String providerId = hit[0];
            var dp = report.detectedProviders.stream().filter(p -> p.name.equals(providerId)).findFirst()
                    .orElseGet(() -> {
                        var created = new com.payshift.analyzer.model.DetectedProvider(providerId);
                        report.detectedProviders.add(created);
                        return created;
                    });
            dp.addEvidence("config_endpoint: " + hit[1]);
            dp.recomputeConfidence();
        }

        ObjectMapper mapper = new ObjectMapper().enable(SerializationFeature.INDENT_OUTPUT);
        emit(mapper.writeValueAsString(report), outputFile);
    }

    /** [providerId, "file: line"] for every main-config line mentioning a registered provider API host. */
    static List<String[]> configEndpointHits(Path repoPath, ProviderRegistry registry) {
        List<String[]> hits = new ArrayList<>();
        try (var paths = Files.walk(repoPath)) {
            List<Path> configs = paths.filter(Files::isRegularFile)
                    .filter(p -> !PomAnalyzer.isUnderBuildOutputDir(repoPath, p))
                    .filter(p -> repoPath.relativize(p).toString().replace('\\', '/').contains("src/main/resources/"))
                    .filter(p -> p.getFileName().toString().matches("application.*\\.(ya?ml|properties)"))
                    .toList();
            for (Path cfg : configs) {
                String rel = repoPath.relativize(cfg).toString().replace('\\', '/');
                for (String line : Files.readAllLines(cfg, StandardCharsets.UTF_8)) {
                    var sig = registry.matchByDomain(line);
                    if (sig != null) hits.add(new String[]{sig.id, rel + ": " + line.trim()});
                }
            }
        } catch (java.io.IOException | java.io.UncheckedIOException e) {
            // best effort: config evidence is supplementary to source/POM evidence
        }
        return hits;
    }

    private static void emit(String json, String outputFile) throws java.io.IOException {
        if (outputFile != null) {
            Files.writeString(Path.of(outputFile), json, StandardCharsets.UTF_8);
        } else {
            PrintStream out = new PrintStream(System.out, true, StandardCharsets.UTF_8);
            out.println(json);
        }
    }
}
