package com.payshift.analyzer;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
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
import java.util.List;

/**
 * CLI / subprocess entry point for the PayShift repository analyzer.
 *
 * Usage:
 *   java -jar java-analyzer.jar <repository-path> [--output report.json]
 *
 * Always prints exactly one JSON document to stdout (or to --output if given) and
 * nothing else, so a parent process (the Python AI engine) can capture it reliably.
 * Exit code 0 means analysis completed (possibly with partial errors reported
 * inside the "errors" field); exit code 1 means the repository path was invalid.
 */
public class Main {

    public static void main(String[] args) throws Exception {
        if (args.length < 1) {
            System.err.println("Usage: java -jar java-analyzer.jar <repository-path> [--output report.json]");
            System.exit(1);
        }

        Path repoPath = Path.of(args[0]).toAbsolutePath().normalize();
        if (!Files.isDirectory(repoPath)) {
            System.err.println("Not a directory: " + repoPath);
            System.exit(1);
        }

        String outputFile = null;
        for (int i = 1; i < args.length; i++) {
            if ("--output".equals(args[i]) && i + 1 < args.length) {
                outputFile = args[i + 1];
            }
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
            var sig = registry.matchByGroupId(dep.groupId);
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

        ObjectMapper mapper = new ObjectMapper().enable(SerializationFeature.INDENT_OUTPUT);
        String json = mapper.writeValueAsString(report);

        if (outputFile != null) {
            Files.writeString(Path.of(outputFile), json, StandardCharsets.UTF_8);
        } else {
            PrintStream out = new PrintStream(System.out, true, StandardCharsets.UTF_8);
            out.println(json);
        }
    }
}
