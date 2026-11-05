package com.payshift.analyzer.source;

import com.github.javaparser.ParseProblemException;
import com.github.javaparser.ParserConfiguration;
import com.github.javaparser.StaticJavaParser;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.ImportDeclaration;
import com.github.javaparser.ast.body.ClassOrInterfaceDeclaration;
import com.github.javaparser.ast.body.FieldDeclaration;
import com.github.javaparser.ast.body.MethodDeclaration;
import com.github.javaparser.ast.body.Parameter;
import com.github.javaparser.ast.expr.AnnotationExpr;
import com.payshift.analyzer.model.ArchitectureAssessment;
import com.payshift.analyzer.model.DetectedProvider;
import com.payshift.analyzer.model.PaymentClass;
import com.payshift.analyzer.model.PaymentOperation;
import com.payshift.analyzer.registry.ProviderRegistry;
import com.payshift.analyzer.registry.ProviderSignature;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Stream;

public class JavaSourceAnalyzer {

    private final ProviderRegistry registry;
    private final List<String> errors = new ArrayList<>();

    public JavaSourceAnalyzer(ProviderRegistry registry) {
        this.registry = registry;
        StaticJavaParser.getConfiguration().setLanguageLevel(ParserConfiguration.LanguageLevel.JAVA_21);
    }

    public Result analyze(Path repositoryRoot) {
        List<ParsedFile> parsedFiles = parseAllJavaFiles(repositoryRoot);

        Map<String, DetectedProvider> providerMap = new LinkedHashMap<>();
        List<ClassInfo> allClasses = new ArrayList<>();
        // Which provider ids each file actually imports from. A bare class-name hint
        // (e.g. "Order", "Payment") is only trustworthy as SDK-usage evidence when the
        // same file also imports that provider's package -- otherwise a provider's
        // generic-sounding type name collides with the merchant app's own domain
        // classes and produces false positives.
        Map<String, java.util.Set<String>> fileImportedProviders = new HashMap<>();

        for (ParsedFile pf : parsedFiles) {
            for (ImportDeclaration imp : pf.unit.findAll(ImportDeclaration.class)) {
                ProviderSignature sig = registry.matchByImport(imp.getNameAsString());
                if (sig != null) {
                    providerMap.computeIfAbsent(sig.id, DetectedProvider::new)
                            .addEvidence("sdk_import: " + imp.getNameAsString() + " (" + pf.relativePath + ")");
                    fileImportedProviders.computeIfAbsent(pf.relativePath, k -> new java.util.HashSet<>()).add(sig.id);
                }
            }
            for (ClassOrInterfaceDeclaration decl : pf.unit.findAll(ClassOrInterfaceDeclaration.class)) {
                allClasses.add(buildClassInfo(decl, pf.relativePath));
            }
        }

        // Reverse map: interface simple name -> implementing/extending class simple names
        Map<String, List<String>> implementedBy = new HashMap<>();
        for (ClassInfo ci : allClasses) {
            for (String iface : ci.implementedTypeNames) {
                implementedBy.computeIfAbsent(iface, k -> new ArrayList<>()).add(ci.simpleName);
            }
            for (String ext : ci.extendedTypeNames) {
                implementedBy.computeIfAbsent(ext, k -> new ArrayList<>()).add(ci.simpleName);
            }
        }

        List<PaymentClass> paymentClasses = new ArrayList<>();
        List<PaymentOperation> operations = new ArrayList<>();

        for (ClassInfo ci : allClasses) {
            // Provider evidence from field/param/type usage inside the class. Gated on
            // the file already importing that provider's package (see fileImportedProviders
            // above) so generic-sounding SDK type names can't match our own domain classes.
            java.util.Set<String> importedHere = fileImportedProviders.getOrDefault(ci.file, java.util.Set.of());
            for (String typeName : ci.fieldAndParamTypeNames) {
                ProviderSignature sig = registry.matchByClassNameHint(typeName);
                if (sig != null && importedHere.contains(sig.id)) {
                    providerMap.computeIfAbsent(sig.id, DetectedProvider::new)
                            .addEvidence("sdk_type_usage: " + typeName + " in " + ci.file);
                }
            }

            String role = classifyRole(ci);
            boolean paymentRelated = isPaymentRelated(ci);

            if (paymentRelated) {
                PaymentClass pc = new PaymentClass(ci.file, ci.simpleName, role, ci.isInterface);
                pc.implementsInterfaces.addAll(ci.implementedTypeNames);
                pc.implementedBy.addAll(implementedBy.getOrDefault(ci.simpleName, List.of()));
                paymentClasses.add(pc);
            }

            String providerForClass = resolveSingleProviderForClass(ci);

            for (MethodDeclaration method : ci.methods) {
                String opType = classifyOperation(method.getNameAsString(), role, paymentRelated);
                if (opType == null) {
                    continue;
                }
                String provider = providerForClass;
                if (provider == null) {
                    provider = resolveProviderFromMethodBody(method);
                }
                operations.add(new PaymentOperation(opType, ci.file, ci.simpleName, method.getNameAsString(), provider));
            }
        }

        for (DetectedProvider dp : providerMap.values()) {
            dp.recomputeConfidence();
        }

        ArchitectureAssessment architecture = assessArchitecture(allClasses, implementedBy, providerMap);

        Result result = new Result();
        result.detectedProviders = new ArrayList<>(providerMap.values());
        result.paymentClasses = paymentClasses;
        result.paymentOperations = operations;
        result.architecture = architecture;
        result.errors = errors;
        return result;
    }

    private List<ParsedFile> parseAllJavaFiles(Path repositoryRoot) {
        List<ParsedFile> parsed = new ArrayList<>();
        try (Stream<Path> paths = Files.walk(repositoryRoot)) {
            List<Path> javaFiles = paths
                    .filter(p -> p.toString().endsWith(".java"))
                    .filter(p -> !com.payshift.analyzer.pom.PomAnalyzer.isUnderBuildOutputDir(repositoryRoot, p))
                    .toList();
            for (Path file : javaFiles) {
                try {
                    CompilationUnit cu = StaticJavaParser.parse(file);
                    parsed.add(new ParsedFile(repositoryRoot.relativize(file).toString(), cu));
                } catch (ParseProblemException | IOException e) {
                    errors.add("Failed to parse " + file + ": " + e.getMessage());
                }
            }
        } catch (IOException e) {
            errors.add("Failed to walk repository: " + e.getMessage());
        }
        return parsed;
    }

    private ClassInfo buildClassInfo(ClassOrInterfaceDeclaration decl, String relativePath) {
        ClassInfo ci = new ClassInfo(decl.getNameAsString(), relativePath, decl.isInterface(),
                decl.getMethods(), decl);

        for (AnnotationExpr a : decl.getAnnotations()) {
            ci.annotations.add(a.getNameAsString());
        }
        decl.getImplementedTypes().forEach(t -> ci.implementedTypeNames.add(t.getNameAsString()));
        decl.getExtendedTypes().forEach(t -> ci.extendedTypeNames.add(t.getNameAsString()));

        for (FieldDeclaration fd : decl.getFields()) {
            ci.fieldAndParamTypeNames.add(fd.getElementType().asString());
        }
        decl.getConstructors().forEach(c -> c.getParameters().forEach(
                (Parameter p) -> ci.fieldAndParamTypeNames.add(p.getType().asString())));
        for (MethodDeclaration m : decl.getMethods()) {
            m.getParameters().forEach((Parameter p) -> ci.fieldAndParamTypeNames.add(p.getType().asString()));
        }
        return ci;
    }

    private String classifyRole(ClassInfo ci) {
        if (hasAnnotation(ci, "RestController", "Controller")) return "CONTROLLER";
        if (hasAnnotation(ci, "Service")) return "SERVICE";
        if (ci.extendedTypeNames.stream().anyMatch(n -> n.contains("Repository"))) return "REPOSITORY";
        if (hasAnnotation(ci, "Entity")) return "DOMAIN";
        if (hasAnnotation(ci, "Configuration")) return "CONFIG";
        if (ci.simpleName.matches("(?i).*webhook.*")) return "WEBHOOK_HANDLER";
        if (ci.simpleName.matches("(?i).*(gateway|provider)s?$") || ci.simpleName.matches("(?i).*(gateway|provider).*client.*")) {
            return "PROVIDER_GATEWAY";
        }
        if (hasAnnotation(ci, "Component")) return "COMPONENT";
        return "OTHER";
    }

    private boolean hasAnnotation(ClassInfo ci, String... names) {
        for (String n : names) {
            if (ci.annotations.contains(n)) return true;
        }
        return false;
    }

    private boolean isPaymentRelated(ClassInfo ci) {
        if (PaymentHeuristics.isPaymentRelatedName(ci.simpleName)) return true;
        for (MethodDeclaration m : ci.methods) {
            if (PaymentHeuristics.isPaymentRelatedName(m.getNameAsString())) return true;
        }
        // Brand-qualified type usage (e.g. a field of type "StripePaymentGateway") is a
        // reliable relatedness signal since it requires the provider's own brand name
        // to appear in the type, unlike a bare SDK class-name hint.
        return resolveSingleProviderForClass(ci) != null;
    }

    private String resolveSingleProviderForClass(ClassInfo ci) {
        String found = null;
        for (String type : ci.fieldAndParamTypeNames) {
            for (ProviderSignature sig : registry.all()) {
                if (type.toLowerCase().contains(sig.displayName.toLowerCase())
                        || type.toLowerCase().contains(sig.id.toLowerCase())) {
                    if (found != null && !found.equals(sig.id)) {
                        return null; // ambiguous: class touches more than one provider
                    }
                    found = sig.id;
                }
            }
        }
        return found;
    }

    private String resolveProviderFromMethodBody(MethodDeclaration method) {
        String body = method.getBody().map(Object::toString).orElse("");
        for (ProviderSignature sig : registry.all()) {
            if (body.contains(sig.displayName)) {
                return sig.id;
            }
        }
        return null;
    }

    private String classifyOperation(String methodName, String classRole, boolean classPaymentRelated) {
        if (PaymentHeuristics.VERIFY_SIGNATURE.matcher(methodName).find()) return "VERIFY_WEBHOOK_SIGNATURE";
        if (PaymentHeuristics.HANDLE_WEBHOOK.matcher(methodName).find()
                || ("WEBHOOK_HANDLER".equals(classRole) && methodName.toLowerCase().contains("handle"))) {
            return "HANDLE_WEBHOOK";
        }
        if (PaymentHeuristics.CREATE_REFUND.matcher(methodName).find()) return "CREATE_REFUND";
        if (PaymentHeuristics.CREATE_PAYMENT.matcher(methodName).find()
                || (classPaymentRelated && methodName.equalsIgnoreCase("createPayment"))) {
            return "CREATE_PAYMENT";
        }
        if (PaymentHeuristics.GET_STATUS.matcher(methodName).find()
                && (classPaymentRelated || methodName.toLowerCase().contains("payment"))) {
            return "GET_PAYMENT_STATUS";
        }
        if (PaymentHeuristics.FULFILL_ORDER.matcher(methodName).find()) return "FULFILL_ORDER";
        return null;
    }

    private ArchitectureAssessment assessArchitecture(List<ClassInfo> allClasses,
                                                        Map<String, List<String>> implementedBy,
                                                        Map<String, DetectedProvider> providerMap) {
        ArchitectureAssessment arch = new ArchitectureAssessment();

        for (ClassInfo ci : allClasses) {
            if (!ci.isInterface) continue;
            int categories = 0;
            boolean hasCreate = false, hasStatus = false, hasRefund = false;
            for (MethodDeclaration m : ci.methods) {
                String name = m.getNameAsString();
                if (!hasCreate && PaymentHeuristics.CREATE_PAYMENT.matcher(name).find()) {
                    hasCreate = true;
                }
                if (!hasStatus && PaymentHeuristics.GET_STATUS.matcher(name).find()) {
                    hasStatus = true;
                }
                if (!hasRefund && PaymentHeuristics.CREATE_REFUND.matcher(name).find()) {
                    hasRefund = true;
                }
            }
            categories = (hasCreate ? 1 : 0) + (hasStatus ? 1 : 0) + (hasRefund ? 1 : 0);
            if (categories >= 2) {
                List<String> implementors = implementedBy.getOrDefault(ci.simpleName, List.of());
                arch.abstractionInterfaces.add(ci.simpleName + " (" + ci.file + ")");
                if (!implementors.isEmpty()) {
                    arch.providerAbstractionExists = true;
                    if (implementors.size() >= 2) {
                        arch.multipleProvidersSupported = true;
                    }
                } else {
                    arch.warnings.add("Interface " + ci.simpleName
                            + " looks like a provider abstraction but has no detected implementation.");
                }
            }
        }

        long confidentProviders = providerMap.values().stream()
                .filter(p -> "HIGH".equals(p.confidence) || "MEDIUM".equals(p.confidence))
                .count();
        if (arch.providerAbstractionExists && confidentProviders >= 2) {
            arch.multipleProvidersSupported = true;
        }
        if (!arch.providerAbstractionExists && confidentProviders >= 1) {
            arch.warnings.add("No provider abstraction detected; the existing integration is tightly coupled "
                    + "to its current provider(s). Adding or migrating providers will require introducing one.");
        }
        return arch;
    }

    private record ParsedFile(String relativePath, CompilationUnit unit) {
    }

    public static class Result {
        public List<DetectedProvider> detectedProviders;
        public List<PaymentClass> paymentClasses;
        public List<PaymentOperation> paymentOperations;
        public ArchitectureAssessment architecture;
        public List<String> errors;
    }
}
