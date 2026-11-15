package com.payshift.analyzer.check;

import com.github.javaparser.ParseProblemException;
import com.github.javaparser.ParserConfiguration;
import com.github.javaparser.StaticJavaParser;
import com.github.javaparser.ast.CompilationUnit;
import com.github.javaparser.ast.Node;
import com.github.javaparser.ast.NodeList;
import com.github.javaparser.ast.body.ClassOrInterfaceDeclaration;
import com.github.javaparser.ast.body.ConstructorDeclaration;
import com.github.javaparser.ast.body.FieldDeclaration;
import com.github.javaparser.ast.body.MethodDeclaration;
import com.github.javaparser.ast.body.Parameter;
import com.github.javaparser.ast.body.VariableDeclarator;
import com.github.javaparser.ast.comments.Comment;
import com.github.javaparser.ast.expr.AnnotationExpr;
import com.github.javaparser.ast.expr.BooleanLiteralExpr;
import com.github.javaparser.ast.expr.Expression;
import com.github.javaparser.ast.expr.IntegerLiteralExpr;
import com.github.javaparser.ast.expr.LongLiteralExpr;
import com.github.javaparser.ast.expr.MemberValuePair;
import com.github.javaparser.ast.expr.MethodCallExpr;
import com.github.javaparser.ast.expr.NameExpr;
import com.github.javaparser.ast.expr.NormalAnnotationExpr;
import com.github.javaparser.ast.expr.NullLiteralExpr;
import com.github.javaparser.ast.expr.ObjectCreationExpr;
import com.github.javaparser.ast.expr.SingleMemberAnnotationExpr;
import com.github.javaparser.ast.expr.StringLiteralExpr;
import com.github.javaparser.ast.expr.VariableDeclarationExpr;
import com.github.javaparser.ast.stmt.BlockStmt;
import com.github.javaparser.ast.stmt.EmptyStmt;
import com.github.javaparser.ast.stmt.ExpressionStmt;
import com.github.javaparser.ast.stmt.ReturnStmt;
import com.github.javaparser.ast.stmt.Statement;
import com.github.javaparser.ast.stmt.ThrowStmt;
import com.github.javaparser.ast.type.ClassOrInterfaceType;
import com.github.javaparser.ast.type.Type;
import com.payshift.analyzer.pom.PomAnalyzer;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.regex.Pattern;
import java.util.stream.Stream;

/**
 * Deterministic, pre-compile checks for defects that compile fine but break a
 * Spring Boot application at startup or leave it hollow -- the failure classes
 * observed when an LLM generates a payment-provider integration:
 *
 * <ul>
 *   <li>{@code missing_bean}: a Spring-managed class injects a type no bean
 *       provides (e.g. a {@code RestTemplate}, which Spring Boot does not
 *       auto-configure) -- the ApplicationContext fails and every test errors.</li>
 *   <li>{@code ambiguous_bean}: two beans now satisfy one injection point with
 *       no qualifier/@Primary -- typically a new adapter implementing the
 *       existing provider's interface.</li>
 *   <li>{@code unresolved_placeholder}: {@code @Value("${key}")} with no default
 *       and no such key in the application's config.</li>
 *   <li>{@code stub_method}: a method that does nothing real (only logs /
 *       returns null / throws "not implemented"), especially when marked with an
 *       "implement this" comment.</li>
 *   <li>{@code unimplemented_interface}: a newly introduced interface with no
 *       implementing class anywhere in the project.</li>
 *   <li>{@code unused_config_value}: a credential/config value injected via
 *       {@code @Value} and then never used -- e.g. an API key read into a field
 *       while every provider call goes out unauthenticated.</li>
 *   <li>{@code unreachable_integration}: a new service/component nothing
 *       injects, so the integration exists but can never be invoked.</li>
 * </ul>
 *
 * Purely syntactic (no symbol resolution, no classpath): types are matched by
 * simple name. Findings are only reported for the files a change touched (or,
 * for ambiguity, where a touched class is one of the competing beans), so a
 * pre-existing quirk in the customer's own code never blocks a run.
 */
public class WiringChecker {

    public static class Finding {
        public String check;
        public String severity; // ERROR | WARNING
        public String file;
        public Integer line;
        public String message;

        Finding(String check, String severity, String file, Node node, String message) {
            this.check = check;
            this.severity = severity;
            this.file = file;
            this.line = node == null ? null : node.getBegin().map(p -> p.line).orElse(null);
            this.message = message;
        }
    }

    public static class Report {
        public boolean passed;
        public List<Finding> findings = new ArrayList<>();
        public List<String> errors = new ArrayList<>();
    }

    private static final Set<String> STEREOTYPES = Set.of(
            "Component", "Service", "Repository", "Controller", "RestController", "Configuration",
            "ControllerAdvice", "RestControllerAdvice", "SpringBootApplication", "ConfigurationProperties");

    private static final Set<String> SPRING_DATA_REPOSITORIES = Set.of(
            "Repository", "CrudRepository", "ListCrudRepository", "PagingAndSortingRepository",
            "ListPagingAndSortingRepository", "JpaRepository", "MongoRepository", "ReactiveCrudRepository",
            "ReactiveMongoRepository", "R2dbcRepository", "ElasticsearchRepository", "JpaSpecificationExecutor");

    /** Declarative-client / framework-proxied interfaces that legitimately have no implementing class. */
    private static final Set<String> PROXIED_INTERFACE_ANNOTATIONS = Set.of(
            "FeignClient", "HttpExchange", "FunctionalInterface", "Mapper", "RepositoryDefinition");

    /**
     * Beans Spring Boot (and the common starters) auto-configure. Deliberately
     * does NOT include RestTemplate, RestClient, WebClient, Clock or any HTTP
     * client: Boot only provides their builders, so injecting one directly with
     * no @Bean for it fails at startup.
     */
    private static final Set<String> AUTO_CONFIGURED = Set.of(
            "ObjectMapper", "Jackson2ObjectMapperBuilder", "RestTemplateBuilder", "RestClient.Builder",
            "WebClient.Builder", "JdbcTemplate", "NamedParameterJdbcTemplate", "JdbcClient", "DataSource",
            "EntityManager", "EntityManagerFactory", "PlatformTransactionManager", "TransactionTemplate",
            "ApplicationContext", "ConfigurableApplicationContext", "Environment", "ConfigurableEnvironment",
            "ApplicationEventPublisher", "ResourceLoader", "BeanFactory", "ListableBeanFactory",
            "ConversionService", "Validator", "LocalValidatorFactoryBean", "MeterRegistry", "ObservationRegistry",
            "TaskExecutor", "AsyncTaskExecutor", "ThreadPoolTaskExecutor", "Executor", "HttpMessageConverters",
            "MessageSource", "ApplicationArguments", "ServerProperties", "KafkaTemplate", "RedisTemplate",
            "StringRedisTemplate", "RedisConnectionFactory", "MongoTemplate", "ReactiveMongoTemplate",
            "RabbitTemplate", "JmsTemplate", "JavaMailSender", "HttpSecurity", "Tracer");

    /** Wrapper types Spring resolves leniently (empty / lazily) -- never a hard startup failure. */
    private static final Set<String> LENIENT_WRAPPERS = Set.of(
            "Optional", "ObjectProvider", "ObjectFactory", "Provider", "List", "Set", "Collection", "Map", "Stream");

    private static final Set<String> VALUE_TYPES = Set.of(
            "String", "Integer", "Long", "Boolean", "Double", "Float", "Short", "Byte", "Character", "BigDecimal",
            "BigInteger", "Duration", "int", "long", "boolean", "double", "float", "short", "byte", "char");

    private static final Pattern STUB_MARKER = Pattern.compile(
            "(?i)\\b(todo|fixme|implement(ed|ation)?\\b.*\\b(logic|here|this|me|later|call)|placeholder|stub"
                    + "|not\\s+(yet\\s+)?implemented|logic\\s+(to|for)\\b|(your|actual|real)\\s+(code|logic|implementation))");
    private static final Pattern CREDENTIAL_NAME = Pattern.compile("(?i)(key|secret|token|password|passwd|credential|auth)");

    /** Classes that are themselves entry points (invoked by the framework, not injected). */
    private static final Set<String> ENTRY_POINT_SUPERTYPES = Set.of(
            "CommandLineRunner", "ApplicationRunner", "Filter", "OncePerRequestFilter", "GenericFilterBean",
            "HandlerInterceptor", "WebMvcConfigurer", "ApplicationListener", "HealthIndicator", "Converter",
            "ErrorController", "AuthenticationProvider", "UserDetailsService", "Job", "Tasklet");
    private static final Set<String> ENTRY_POINT_METHOD_ANNOTATIONS = Set.of(
            "Scheduled", "EventListener", "TransactionalEventListener", "KafkaListener", "RabbitListener",
            "JmsListener", "SqsListener", "StreamListener", "Bean", "PostConstruct", "GetMapping", "PostMapping",
            "RequestMapping", "PutMapping", "DeleteMapping", "PatchMapping", "MessageMapping");
    private static final Pattern LOGGER_NAME = Pattern.compile("(?i)^(log|logger|LOG|LOGGER|slf4jLogger)$");

    private final List<ClassModel> classes = new ArrayList<>();
    private final Map<String, List<ClassModel>> bySimpleName = new HashMap<>();
    private final Map<String, ClassModel> byFqn = new HashMap<>();
    private final List<BeanMethod> beanMethods = new ArrayList<>();

    private record BeanMethod(String rawReturnType, String beanName, boolean primary, String file,
                              MethodDeclaration decl, ClassModel owner) {
    }

    /**
     * Types are identified by fully qualified name, resolved per file from its
     * package and imports -- not by simple name. Simple-name matching let a
     * generated second interface named PaymentProvider (in an invented package)
     * look like the app's real PaymentProvider, so an adapter the router could
     * never see was judged reachable (live eval run eval-multi-psp-router-1).
     */
    private static final class ClassModel {
        final String file;
        final ClassOrInterfaceDeclaration decl;
        final String simpleName;
        final String pkg;
        final String fqn;
        final Map<String, String> singleImports = new HashMap<>();
        final List<String> wildcardImports = new ArrayList<>();
        final List<String> rawSupertypes = new ArrayList<>();
        final Set<String> directSupertypes = new LinkedHashSet<>(); // resolved, filled after parsing

        ClassModel(String file, ClassOrInterfaceDeclaration decl, CompilationUnit cu) {
            this.file = file;
            this.decl = decl;
            this.simpleName = decl.getNameAsString();
            this.pkg = cu.getPackageDeclaration().map(pd -> pd.getNameAsString()).orElse("");
            this.fqn = decl.getFullyQualifiedName().orElse(pkg.isEmpty() ? simpleName : pkg + "." + simpleName);
            for (var imp : cu.getImports()) {
                if (imp.isStatic()) continue;
                String name = imp.getNameAsString();
                if (imp.isAsterisk()) wildcardImports.add(name);
                else singleImports.put(name.substring(name.lastIndexOf('.') + 1), name);
            }
            decl.getImplementedTypes().forEach(t -> rawSupertypes.add(t.getNameWithScope()));
            decl.getExtendedTypes().forEach(t -> rawSupertypes.add(t.getNameWithScope()));
        }

        boolean isInterface() {
            return decl.isInterface();
        }

        boolean hasAnnotation(String... names) {
            for (AnnotationExpr a : decl.getAnnotations()) {
                for (String n : names) {
                    if (a.getNameAsString().equals(n) || a.getNameAsString().endsWith("." + n)) return true;
                }
            }
            return false;
        }

        boolean isBeanClass() {
            if (decl.isInterface() || decl.isAbstract()) return false;
            return decl.getAnnotations().stream().anyMatch(a -> STEREOTYPES.contains(simple(a.getNameAsString())));
        }

        String beanName() {
            for (AnnotationExpr a : decl.getAnnotations()) {
                if (!STEREOTYPES.contains(simple(a.getNameAsString()))) continue;
                String explicit = annotationValue(a);
                if (explicit != null && !explicit.isBlank()) return explicit;
            }
            return decapitalize(simpleName);
        }
    }

    public WiringChecker() {
        StaticJavaParser.getConfiguration().setLanguageLevel(ParserConfiguration.LanguageLevel.JAVA_21);
    }

    public Report check(Path repositoryRoot, Set<String> changedFiles) {
        Report report = new Report();
        Set<String> changed = new HashSet<>();
        for (String f : changedFiles) changed.add(f.replace('\\', '/'));

        parseMainSources(repositoryRoot, report);
        SpringConfigKeys config = SpringConfigKeys.load(repositoryRoot);
        report.errors.addAll(config.errors);

        for (ClassModel cm : classes) {
            boolean isChanged = changed.contains(cm.file);
            if (cm.isBeanClass()) {
                for (InjectionPoint ip : injectionPoints(cm)) {
                    checkInjectionPoint(cm, ip, isChanged, changed, report);
                }
            }
            if (isChanged) {
                checkValuePlaceholders(cm, config, report);
                checkStubMethods(cm, report);
                checkUnusedConfigValues(cm, report);
                checkDuplicateTypeName(cm, changed, report);
                checkComponentScan(cm, report);
                if (cm.isInterface()) checkInterfaceImplemented(cm, report);
            }
        }
        Set<String> injectedTypes = allInjectedTypeNames();
        for (ClassModel cm : classes) {
            if (changed.contains(cm.file)) checkReachable(cm, injectedTypes, report);
        }
        // @Bean factory-method parameters are injection points too.
        for (BeanMethod bm : beanMethods) {
            boolean isChanged = changed.contains(bm.file());
            for (Parameter p : bm.decl().getParameters()) {
                checkInjectionPoint(null, new InjectionPoint(bm.owner(), bm.file(), p, p.getType(),
                        p.getNameAsString(), p.getAnnotations()), isChanged, changed, report);
            }
        }

        report.passed = report.findings.stream().noneMatch(f -> "ERROR".equals(f.severity));
        return report;
    }

    // ------------------------------------------------------------------ parsing

    private void parseMainSources(Path root, Report report) {
        List<Path> files;
        try (Stream<Path> paths = Files.walk(root)) {
            files = paths.filter(p -> p.toString().endsWith(".java"))
                    .filter(p -> !PomAnalyzer.isUnderBuildOutputDir(root, p))
                    .filter(p -> root.relativize(p).toString().replace('\\', '/').contains("src/main/java/"))
                    .toList();
        } catch (IOException e) {
            report.errors.add("Failed to walk repository: " + e.getMessage());
            return;
        }
        for (Path file : files) {
            String rel = root.relativize(file).toString().replace('\\', '/');
            CompilationUnit cu;
            try {
                cu = StaticJavaParser.parse(file);
            } catch (ParseProblemException | IOException e) {
                report.errors.add("Failed to parse " + rel + ": " + firstLine(e.getMessage()));
                continue;
            }
            for (ClassOrInterfaceDeclaration decl : cu.findAll(ClassOrInterfaceDeclaration.class)) {
                ClassModel cm = new ClassModel(rel, decl, cu);
                classes.add(cm);
                bySimpleName.computeIfAbsent(cm.simpleName, k -> new ArrayList<>()).add(cm);
                byFqn.put(cm.fqn, cm);
                boolean canDeclareBeans = cm.isBeanClass();
                if (!canDeclareBeans) continue;
                for (MethodDeclaration m : decl.getMethods()) {
                    Optional<AnnotationExpr> bean = m.getAnnotations().stream()
                            .filter(a -> simple(a.getNameAsString()).equals("Bean")).findFirst();
                    if (bean.isEmpty()) continue;
                    String name = Optional.ofNullable(annotationValue(bean.get())).filter(s -> !s.isBlank())
                            .orElse(m.getNameAsString());
                    boolean primary = m.getAnnotations().stream().anyMatch(a -> simple(a.getNameAsString()).equals("Primary"));
                    beanMethods.add(new BeanMethod(typeName(m.getType()), name, primary, rel, m, cm));
                }
            }
        }
        for (ClassModel cm : classes) {
            for (String raw : cm.rawSupertypes) cm.directSupertypes.add(resolve(cm, raw));
        }
    }

    /**
     * Resolves a type name as written in {@code ctx}'s source file to a fully
     * qualified name: explicit import, enclosing/nested types, same package,
     * wildcard imports. Project types resolve to their FQN; an external type
     * resolves to its imported FQN when imported, else stays as written. A
     * simple name with no import that matches exactly one project type
     * (sources written without imports, e.g. snippets) resolves to it.
     */
    private String resolve(ClassModel ctx, String written) {
        String n = written.contains("<") ? written.substring(0, written.indexOf('<')) : written;
        if (byFqn.containsKey(n)) return n;
        int dot = n.indexOf('.');
        if (dot > 0 && Character.isLowerCase(n.charAt(0))) return n; // already package-qualified
        String head = dot > 0 ? n.substring(0, dot) : n;
        String tail = dot > 0 ? n.substring(dot) : "";
        String imported = ctx.singleImports.get(head);
        if (imported != null) return imported + tail;
        for (String outer = ctx.fqn; outer.contains("."); outer = outer.substring(0, outer.lastIndexOf('.'))) {
            if (byFqn.containsKey(outer + "." + n)) return outer + "." + n;
        }
        if (byFqn.containsKey(ctx.pkg + "." + n)) return ctx.pkg + "." + n;
        for (String w : ctx.wildcardImports) {
            if (byFqn.containsKey(w + "." + n)) return w + "." + n;
        }
        List<ClassModel> sameName = bySimpleName.get(head);
        if (tail.isEmpty() && sameName != null && sameName.size() == 1) return sameName.get(0).fqn;
        return n;
    }

    private static String simpleOf(String name) {
        return name.substring(name.lastIndexOf('.') + 1);
    }

    // ------------------------------------------------------------------ injection

    private record InjectionPoint(ClassModel ctx, String file, Node node, Type type, String name,
                                  NodeList<AnnotationExpr> annotations) {
    }

    private List<InjectionPoint> injectionPoints(ClassModel cm) {
        List<InjectionPoint> points = new ArrayList<>();
        List<ConstructorDeclaration> ctors = cm.decl.getConstructors();
        ConstructorDeclaration chosen = null;
        if (ctors.size() == 1) {
            chosen = ctors.get(0);
        } else if (ctors.size() > 1) {
            chosen = ctors.stream().filter(c -> c.getAnnotations().stream()
                    .anyMatch(a -> Set.of("Autowired", "Inject").contains(simple(a.getNameAsString()))))
                    .findFirst().orElse(null);
        }
        if (chosen != null) {
            for (Parameter p : chosen.getParameters()) {
                points.add(new InjectionPoint(cm, cm.file, p, p.getType(), p.getNameAsString(), p.getAnnotations()));
            }
        } else if (ctors.isEmpty() && cm.hasAnnotation("RequiredArgsConstructor", "AllArgsConstructor")) {
            // Lombok-generated constructor: final (or all) non-static instance fields.
            boolean allFields = cm.hasAnnotation("AllArgsConstructor");
            for (FieldDeclaration fd : cm.decl.getFields()) {
                if (fd.isStatic()) continue;
                if (!allFields && !fd.isFinal()) continue;
                for (VariableDeclarator v : fd.getVariables()) {
                    if (v.getInitializer().isPresent()) continue;
                    points.add(new InjectionPoint(cm, cm.file, fd, v.getType(), v.getNameAsString(), fd.getAnnotations()));
                }
            }
        }
        for (FieldDeclaration fd : cm.decl.getFields()) {
            boolean autowired = fd.getAnnotations().stream()
                    .anyMatch(a -> Set.of("Autowired", "Inject", "Resource").contains(simple(a.getNameAsString())));
            if (!autowired) continue;
            for (VariableDeclarator v : fd.getVariables()) {
                points.add(new InjectionPoint(cm, cm.file, fd, v.getType(), v.getNameAsString(), fd.getAnnotations()));
            }
        }
        return points;
    }

    private void checkInjectionPoint(ClassModel owner, InjectionPoint ip, boolean ownerChanged,
                                     Set<String> changed, Report report) {
        if (hasAnnotation(ip.annotations(), "Value")) return; // config value, checked separately
        Type type = ip.type();
        if (type.isPrimitiveType()) {
            if (ownerChanged) {
                report.findings.add(new Finding("missing_bean", "ERROR", ip.file(), ip.node(),
                        "Constructor/field '" + ip.name() + "' of primitive type " + type.asString()
                                + " is injected without @Value; Spring has no bean of that type."));
            }
            return;
        }
        if (!type.isClassOrInterfaceType()) return;
        ClassOrInterfaceType cit = type.asClassOrInterfaceType();
        if (LENIENT_WRAPPERS.contains(cit.getNameAsString())) return;
        String typeName = typeName(type);
        String where = owner != null ? owner.simpleName : "@Bean method parameter";

        if (VALUE_TYPES.contains(typeName)) {
            if (ownerChanged) {
                report.findings.add(new Finding("missing_bean", "ERROR", ip.file(), ip.node(),
                        where + " injects '" + ip.name() + "' of type " + typeName + " without @Value; Spring has no "
                                + "bean of that type. Use @Value(\"${some.key:default}\") or a @ConfigurationProperties class."));
            }
            return;
        }
        if (AUTO_CONFIGURED.contains(typeName) || AUTO_CONFIGURED.contains(cit.getNameAsString())) return;

        String resolved = resolve(ip.ctx(), typeName);
        List<Candidate> candidates = candidatesFor(resolved);
        if (candidates.isEmpty()) {
            if (!ownerChanged) return;
            boolean projectType = byFqn.containsKey(resolved);
            String hint = typeName.equals("RestTemplate")
                    ? " Spring Boot auto-configures only RestTemplateBuilder: inject that and call build(), or declare "
                      + "a @Bean RestTemplate in a @Configuration class."
                    : projectType
                    ? " " + typeName + " exists in the project but nothing annotated @Component/@Service/... "
                      + "implements it, and no @Bean method returns it."
                    : " Declare a @Bean of this type in a @Configuration class, or construct it inside the class "
                      + "instead of injecting it.";
            report.findings.add(new Finding("missing_bean", "ERROR", ip.file(), ip.node(),
                    where + " requires a bean of type " + typeName + " ('" + ip.name()
                            + "'), but no bean of that type exists, so the Spring ApplicationContext cannot start." + hint));
            return;
        }
        if (candidates.size() > 1 && !hasAnnotation(ip.annotations(), "Qualifier")
                && candidates.stream().noneMatch(Candidate::primary)
                && candidates.stream().noneMatch(c -> c.beanName().equals(ip.name()))) {
            boolean involvesChange = ownerChanged || candidates.stream().anyMatch(c -> changed.contains(c.file()));
            if (involvesChange) {
                report.findings.add(new Finding("ambiguous_bean", "ERROR", ip.file(), ip.node(),
                        where + " injects " + typeName + " ('" + ip.name() + "') but " + candidates.size()
                                + " beans match: " + candidates.stream().map(Candidate::describe).toList()
                                + ". Spring will fail with NoUniqueBeanDefinitionException (and @MockBean of this "
                                + "type in tests cannot pick one). Give the new provider its own interface, or "
                                + "mark exactly one candidate @Primary / add a @Qualifier."));
            }
        }
    }

    private record Candidate(String beanName, String file, boolean primary, String kind) {
        String describe() {
            return beanName + " (" + kind + " in " + file + ")";
        }
    }

    /** @param typeName a resolved type name (FQN for project types). */
    private List<Candidate> candidatesFor(String typeName) {
        List<Candidate> result = new ArrayList<>();
        for (ClassModel cm : classes) {
            boolean assignable = cm.fqn.equals(typeName) || supertypesOf(cm).contains(typeName);
            if (!assignable) continue;
            if (cm.isBeanClass()) {
                result.add(new Candidate(cm.beanName(), cm.file, cm.hasAnnotation("Primary"), "class"));
            } else if (cm.isInterface() && isSpringDataRepository(cm)) {
                result.add(new Candidate(decapitalize(cm.simpleName), cm.file, false, "Spring Data repository"));
            }
        }
        for (BeanMethod bm : beanMethods) {
            String rt = resolve(bm.owner(), bm.rawReturnType());
            boolean assignable = rt.equals(typeName);
            if (!assignable && byFqn.containsKey(rt)) {
                assignable = supertypesOf(byFqn.get(rt)).contains(typeName);
            }
            if (assignable) result.add(new Candidate(bm.beanName(), bm.file(), bm.primary(), "@Bean method"));
        }
        return result;
    }

    private Set<String> supertypesOf(ClassModel cm) {
        Set<String> seen = new LinkedHashSet<>();
        List<String> queue = new ArrayList<>(cm.directSupertypes);
        while (!queue.isEmpty()) {
            String t = queue.remove(queue.size() - 1);
            if (!seen.add(t)) continue;
            ClassModel parent = byFqn.get(t);
            if (parent != null) queue.addAll(parent.directSupertypes);
        }
        return seen;
    }

    private boolean isSpringDataRepository(ClassModel cm) {
        return supertypesOf(cm).stream().map(WiringChecker::simpleOf).anyMatch(SPRING_DATA_REPOSITORIES::contains);
    }

    // ------------------------------------------------------------------ @Value

    private void checkValuePlaceholders(ClassModel cm, SpringConfigKeys config, Report report) {
        for (AnnotationExpr a : cm.decl.findAll(AnnotationExpr.class)) {
            if (!simple(a.getNameAsString()).equals("Value")) continue;
            if (a.findAncestor(ClassOrInterfaceDeclaration.class).filter(d -> d != cm.decl).isPresent()) continue;
            String value = annotationValue(a);
            if (value == null || !value.contains("${")) continue;
            for (String[] ph : topLevelPlaceholders(value)) {
                String key = ph[0];
                boolean hasDefault = ph[1] != null;
                if (hasDefault || key.isEmpty()) continue;
                String norm = SpringConfigKeys.normalize(key);
                if (config.mainDefault.contains(norm)) continue;
                if (config.mainProfileOnly.contains(norm) || config.testOnly.contains(norm)) {
                    report.findings.add(new Finding("unresolved_placeholder", "WARNING", cm.file, a,
                            "@Value(\"${" + key + "}\") is only defined in a profile-specific or test config file; "
                                    + "a default-profile production startup will fail. Add a default value or define it "
                                    + "in application.yml."));
                    continue;
                }
                report.findings.add(new Finding("unresolved_placeholder", "ERROR", cm.file, a,
                        "@Value(\"${" + key + "}\") has no default value and '" + key + "' is not defined in "
                                + "src/main/resources/application.yml/.properties, so the ApplicationContext fails to "
                                + "start (\"Could not resolve placeholder\"). Use \"${" + key + ":<safe-default>}\" or "
                                + "add the key (backed by an env var, e.g. ${ENV_VAR:...}) to application.yml."));
            }
        }
    }

    // ------------------------------------------------------------------ stubs

    private void checkStubMethods(ClassModel cm, Report report) {
        if (cm.isInterface()) return;
        for (MethodDeclaration m : cm.decl.getMethods()) {
            if (m.isAbstract() || m.getBody().isEmpty()) continue;
            if (m.getAnnotations().stream().anyMatch(a -> simple(a.getNameAsString()).equals("ExceptionHandler"))) continue;
            BlockStmt body = m.getBody().get();
            boolean marker = commentsIn(m).stream().anyMatch(c -> STUB_MARKER.matcher(c.getContent()).find());
            List<Statement> stmts = body.getStatements();
            boolean allTrivial = stmts.stream().allMatch(s -> isTrivial(s, body));
            boolean throwsNotImplemented = stmts.stream().anyMatch(this::throwsNotImplemented);
            boolean hasDeadLocal = stmts.stream().anyMatch(s -> isUnusedLocal(s, body));
            String sig = cm.simpleName + "." + m.getNameAsString() + "()";

            if (throwsNotImplemented) {
                report.findings.add(new Finding("stub_method", "ERROR", cm.file, m,
                        sig + " throws a 'not implemented' exception instead of implementing the behavior."));
            } else if (allTrivial && !stmts.isEmpty() && (marker || hasDeadLocal)) {
                report.findings.add(new Finding("stub_method", "ERROR", cm.file, m,
                        sig + " is a placeholder: its body only logs/returns a constant"
                                + (hasDeadLocal ? " and computes a value it never uses" : "")
                                + (marker ? ", with an 'implement this' style comment" : "")
                                + ". Implement the real provider call (or remove the method)."));
            } else if (allTrivial && !stmts.isEmpty() && isOverride(m)
                    && stmts.stream().allMatch(st -> st instanceof EmptyStmt || isLoggingStatement(st))) {
                report.findings.add(new Finding("stub_method", "ERROR", cm.file, m,
                        sig + " implements its interface contract only by logging; it performs no real work."));
            } else if (allTrivial && marker) {
                report.findings.add(new Finding("stub_method", "ERROR", cm.file, m,
                        sig + " has an empty body marked as to-be-implemented."));
            } else if (allTrivial && !m.getType().isVoidType() && !stmts.isEmpty() && returnsNullOrDefault(stmts)) {
                report.findings.add(new Finding("stub_method", "WARNING", cm.file, m,
                        sig + " only returns a null/default value; confirm this is intentional."));
            } else if (marker) {
                report.findings.add(new Finding("stub_method", "WARNING", cm.file, m,
                        sig + " contains a TODO/'implement' comment; it may be incomplete."));
            }
        }
    }

    private static List<Comment> commentsIn(MethodDeclaration m) {
        List<Comment> all = new ArrayList<>(m.getAllContainedComments());
        m.getBody().ifPresent(b -> all.addAll(b.getOrphanComments()));
        return all;
    }

    private boolean isTrivial(Statement s, BlockStmt body) {
        if (s instanceof EmptyStmt) return true;
        if (s instanceof ReturnStmt r) {
            return r.getExpression().map(WiringChecker::isConstantish).orElse(true);
        }
        if (s instanceof ThrowStmt) return throwsNotImplemented(s);
        if (s instanceof ExpressionStmt es) {
            Expression e = es.getExpression();
            if (e instanceof MethodCallExpr call && isLoggingCall(call)) return true;
            if (e instanceof VariableDeclarationExpr) return isUnusedLocal(s, body);
        }
        return false;
    }

    private static boolean isConstantish(Expression e) {
        if (e instanceof NullLiteralExpr) return true;
        if (e instanceof BooleanLiteralExpr || e instanceof IntegerLiteralExpr || e instanceof LongLiteralExpr) return true;
        if (e instanceof StringLiteralExpr s) return s.getValue().isEmpty();
        if (e instanceof MethodCallExpr call) {
            String n = call.getNameAsString();
            String scope = call.getScope().map(Node::toString).orElse("");
            return (scope.equals("Optional") && n.equals("empty"))
                    || (Set.of("List", "Set", "Map").contains(scope) && n.equals("of") && call.getArguments().isEmpty())
                    || (scope.equals("Collections") && n.startsWith("empty"));
        }
        return false;
    }

    private static boolean returnsNullOrDefault(List<Statement> stmts) {
        return stmts.stream().anyMatch(s -> s instanceof ReturnStmt r && r.getExpression().map(WiringChecker::isConstantish).orElse(false));
    }

    private static boolean isLoggingCall(MethodCallExpr call) {
        Optional<Expression> scope = call.getScope();
        if (scope.isEmpty()) return false;
        String sc = scope.get().toString();
        if (sc.equals("System.out") || sc.equals("System.err")) return true;
        String last = sc.contains(".") ? sc.substring(sc.lastIndexOf('.') + 1) : sc;
        return LOGGER_NAME.matcher(last).matches()
                && Set.of("trace", "debug", "info", "warn", "error", "println", "print", "printf").contains(call.getNameAsString());
    }

    private boolean throwsNotImplemented(Statement s) {
        if (!(s instanceof ThrowStmt t)) return false;
        if (!(t.getExpression() instanceof ObjectCreationExpr oce)) return false;
        String type = oce.getType().getNameAsString();
        if (type.equals("UnsupportedOperationException") || type.equals("NotImplementedException")) return true;
        return oce.getArguments().stream().anyMatch(a -> a instanceof StringLiteralExpr lit
                && STUB_MARKER.matcher(lit.getValue()).find());
    }

    private static boolean isUnusedLocal(Statement s, BlockStmt body) {
        if (!(s instanceof ExpressionStmt es) || !(es.getExpression() instanceof VariableDeclarationExpr vde)) return false;
        for (VariableDeclarator v : vde.getVariables()) {
            String name = v.getNameAsString();
            long uses = body.findAll(NameExpr.class).stream().filter(n -> n.getNameAsString().equals(name)).count();
            if (uses > 0) return false;
        }
        return true;
    }

    // ------------------------------------------------------------------ interfaces

    private void checkInterfaceImplemented(ClassModel iface, Report report) {
        if (isSpringDataRepository(iface)) return;
        if (iface.decl.getAnnotations().stream().anyMatch(a -> PROXIED_INTERFACE_ANNOTATIONS.contains(simple(a.getNameAsString())))) {
            return;
        }
        boolean implemented = classes.stream()
                .anyMatch(c -> !c.isInterface() && supertypesOf(c).contains(iface.fqn));
        if (!implemented) {
            report.findings.add(new Finding("unimplemented_interface", "ERROR", iface.file, iface.decl,
                    "Interface " + iface.simpleName + " was introduced but no class in the project implements it, "
                            + "so anything depending on it has no bean and the new provider is never actually wired in."));
        }
    }

    // ------------------------------------------------------------------ unused config / reachability

    private void checkUnusedConfigValues(ClassModel cm, Report report) {
        // @Value fields.
        for (FieldDeclaration fd : cm.decl.getFields()) {
            if (!hasAnnotation(fd.getAnnotations(), "Value")) continue;
            for (VariableDeclarator v : fd.getVariables()) {
                if (!fieldUsedOutsideConstructorAssignments(cm, v.getNameAsString())) {
                    reportUnused(cm, fd, v.getNameAsString(), report);
                }
            }
        }
        // @Value constructor parameters: used directly in the constructor, or
        // stored in a field that is then used elsewhere.
        for (ConstructorDeclaration ctor : cm.decl.getConstructors()) {
            for (Parameter p : ctor.getParameters()) {
                if (!hasAnnotation(p.getAnnotations(), "Value")) continue;
                String name = p.getNameAsString();
                List<String> sinkFields = new ArrayList<>();
                long directUses = 0;
                for (NameExpr n : ctor.getBody().findAll(NameExpr.class)) {
                    if (!n.getNameAsString().equals(name)) continue;
                    Optional<String> sink = assignedField(n);
                    if (sink.isPresent()) sinkFields.add(sink.get()); else directUses++;
                }
                boolean used = directUses > 0
                        || sinkFields.stream().anyMatch(f -> fieldUsedOutsideConstructorAssignments(cm, f));
                if (!used) reportUnused(cm, p, name, report);
            }
        }
    }

    private void reportUnused(ClassModel cm, Node node, String name, Report report) {
        boolean credential = CREDENTIAL_NAME.matcher(name).find();
        report.findings.add(new Finding("unused_config_value", credential ? "ERROR" : "WARNING", cm.file, node,
                cm.simpleName + " injects '" + name + "' via @Value but never uses it"
                        + (credential ? " -- so calls to the provider are made without the credential (they would "
                        + "be rejected as unauthenticated). Apply it (e.g. basic auth / Authorization header)." : ".")));
    }

    /** `this.f = name` or `f = name` inside a constructor: returns f. */
    private static Optional<String> assignedField(NameExpr n) {
        return n.getParentNode()
                .filter(parent -> parent instanceof com.github.javaparser.ast.expr.AssignExpr)
                .map(parent -> (com.github.javaparser.ast.expr.AssignExpr) parent)
                .filter(a -> a.getValue() == n)
                .map(a -> a.getTarget() instanceof com.github.javaparser.ast.expr.FieldAccessExpr fa
                        ? fa.getNameAsString() : a.getTarget().toString());
    }

    private static boolean fieldUsedOutsideConstructorAssignments(ClassModel cm, String field) {
        for (MethodDeclaration m : cm.decl.getMethods()) {
            if (m.findAll(NameExpr.class).stream().anyMatch(n -> n.getNameAsString().equals(field))) return true;
            if (m.findAll(com.github.javaparser.ast.expr.FieldAccessExpr.class).stream()
                    .anyMatch(fa -> fa.getNameAsString().equals(field))) return true;
        }
        for (ConstructorDeclaration c : cm.decl.getConstructors()) {
            for (NameExpr n : c.getBody().findAll(NameExpr.class)) {
                if (n.getNameAsString().equals(field) && assignedField(n).isEmpty()) return true;
            }
        }
        for (FieldDeclaration fd : cm.decl.getFields()) { // used in another field's initializer
            for (VariableDeclarator v : fd.getVariables()) {
                if (v.getInitializer().map(i -> i.findAll(NameExpr.class).stream()
                        .anyMatch(n -> n.getNameAsString().equals(field))).orElse(false)) return true;
            }
        }
        return false;
    }

    private Set<String> allInjectedTypeNames() {
        Set<String> types = new HashSet<>();
        for (ClassModel cm : classes) {
            if (!cm.isBeanClass()) continue;
            for (InjectionPoint ip : injectionPoints(cm)) addTypeAndArgs(cm, ip.type(), types);
        }
        for (BeanMethod bm : beanMethods) {
            for (Parameter p : bm.decl().getParameters()) addTypeAndArgs(bm.owner(), p.getType(), types);
        }
        return types;
    }

    private void addTypeAndArgs(ClassModel ctx, Type type, Set<String> into) {
        into.add(resolve(ctx, typeName(type)));
        if (type.isClassOrInterfaceType()) {
            type.asClassOrInterfaceType().getTypeArguments()
                    .ifPresent(args -> args.forEach(a -> addTypeAndArgs(ctx, a, into)));
        }
    }

    private void checkReachable(ClassModel cm, Set<String> injectedTypes, Report report) {
        if (!cm.isBeanClass() || !cm.hasAnnotation("Component", "Service", "Repository")) return;
        Set<String> names = new HashSet<>(supertypesOf(cm));
        names.add(cm.fqn);
        if (names.stream().anyMatch(injectedTypes::contains)) return;
        if (names.stream().map(WiringChecker::simpleOf).anyMatch(ENTRY_POINT_SUPERTYPES::contains)) return;
        boolean hasEntryMethod = cm.decl.getMethods().stream().anyMatch(m -> m.getAnnotations().stream()
                .anyMatch(a -> ENTRY_POINT_METHOD_ANNOTATIONS.contains(simple(a.getNameAsString()))));
        if (hasEntryMethod) return;
        report.findings.add(new Finding("unreachable_integration", "ERROR", cm.file, cm.decl,
                cm.simpleName + " is a Spring bean that nothing injects (no service, controller, router or @Bean "
                        + "method depends on it or on its interfaces), so the new integration can never be invoked. "
                        + "Make it implement the interface the existing router/service already injects, or add a new "
                        + "@Service/@RestController file that uses it (new files are allowed; unplanned existing "
                        + "files are not editable)."));
    }

    /**
     * Packages Spring Boot component-scans: each @SpringBootApplication class's
     * package, plus literal basePackages of any @ComponentScan.
     */
    private Set<String> componentScanRoots() {
        Set<String> roots = new LinkedHashSet<>();
        for (ClassModel cm : classes) {
            for (AnnotationExpr a : cm.decl.getAnnotations()) {
                String name = simple(a.getNameAsString());
                if (name.equals("SpringBootApplication")) roots.add(cm.pkg);
                if (name.equals("ComponentScan") || name.equals("SpringBootApplication")) {
                    for (StringLiteralExpr lit : a.findAll(StringLiteralExpr.class)) {
                        if (lit.getValue().matches("[a-z_][\\w.]*")) roots.add(lit.getValue());
                    }
                }
            }
        }
        return roots;
    }

    /**
     * A stereotype-annotated class outside every component-scanned package is
     * never registered: the "integration" does not exist at runtime. Live eval
     * run eval-stripe-direct-checkout-2 put every new class in com.acme.payment
     * while the app scans com.acme.checkout -- it compiled, tests passed, and no
     * Razorpay bean existed.
     */
    private void checkComponentScan(ClassModel cm, Report report) {
        if (!cm.isBeanClass() || cm.decl.isNestedType()) return;
        Set<String> roots = componentScanRoots();
        if (roots.isEmpty()) return; // not a Spring Boot app we can reason about
        boolean scanned = roots.stream().anyMatch(r -> cm.pkg.equals(r) || cm.pkg.startsWith(r + "."));
        if (!scanned) {
            report.findings.add(new Finding("outside_component_scan", "ERROR", cm.file, cm.decl,
                    cm.simpleName + " is in package " + cm.pkg + ", outside the component-scanned package(s) "
                            + roots + ", so Spring never registers it and it does not exist at runtime. Move it "
                            + "under " + roots.iterator().next() + " (e.g. " + roots.iterator().next() + "."
                            + cm.pkg.substring(cm.pkg.lastIndexOf('.') + 1) + ")."));
        }
    }

    /**
     * A changed type that reuses the simple name of an existing, untouched
     * project type in another package. Almost always a hallucinated import
     * "fixed" by inventing a parallel type instead of using the real one.
     */
    private void checkDuplicateTypeName(ClassModel cm, Set<String> changed, Report report) {
        if (cm.decl.isNestedType()) return;
        for (ClassModel other : bySimpleName.getOrDefault(cm.simpleName, List.of())) {
            if (other == cm || other.fqn.equals(cm.fqn) || other.decl.isNestedType() || changed.contains(other.file)) {
                continue;
            }
            report.findings.add(new Finding("duplicate_type_name", "ERROR", cm.file, cm.decl,
                    cm.fqn + " duplicates the name of existing type " + other.fqn + " (" + other.file + "). "
                            + "Use the existing " + other.simpleName + " (import " + other.fqn + ") instead of "
                            + "declaring a parallel one -- code depending on the original will never see this one."));
            return;
        }
    }

    private static boolean isOverride(MethodDeclaration m) {
        return m.getAnnotations().stream().anyMatch(a -> simple(a.getNameAsString()).equals("Override"));
    }

    private static boolean isLoggingStatement(Statement s) {
        return s instanceof ExpressionStmt es && es.getExpression() instanceof MethodCallExpr call && isLoggingCall(call);
    }

    // ------------------------------------------------------------------ helpers

    /**
     * Top-level ${key} / ${key:default} placeholders in an @Value string. Nested
     * placeholders inside a default (${a:${b}}) are only consulted by Spring when
     * the outer key is missing, so the outer one having a default is enough.
     * Returns [key, defaultOrNull] pairs.
     */
    public static List<String[]> topLevelPlaceholders(String value) {
        List<String[]> out = new ArrayList<>();
        int i = 0;
        while ((i = value.indexOf("${", i)) >= 0) {
            int depth = 1, j = i + 2, colon = -1;
            while (j < value.length() && depth > 0) {
                if (value.startsWith("${", j)) { depth++; j += 2; continue; }
                char c = value.charAt(j);
                if (c == '}') depth--;
                else if (c == ':' && depth == 1 && colon < 0) colon = j;
                j++;
            }
            if (depth != 0) break; // unterminated -- not a placeholder Spring would resolve either
            int end = j - 1;
            String key = value.substring(i + 2, colon >= 0 ? colon : end).trim();
            out.add(new String[]{key, colon >= 0 ? value.substring(colon + 1, end) : null});
            i = j;
        }
        return out;
    }

    private static boolean hasAnnotation(NodeList<AnnotationExpr> annotations, String name) {
        return annotations.stream().anyMatch(a -> simple(a.getNameAsString()).equals(name));
    }

    private static String annotationValue(AnnotationExpr a) {
        if (a instanceof SingleMemberAnnotationExpr s) return literal(s.getMemberValue());
        if (a instanceof NormalAnnotationExpr n) {
            for (MemberValuePair p : n.getPairs()) {
                if (p.getNameAsString().equals("value") || p.getNameAsString().equals("name")) return literal(p.getValue());
            }
        }
        return null;
    }

    private static String literal(Expression e) {
        if (e instanceof StringLiteralExpr s) return s.getValue();
        if (e.isBinaryExpr()) { // "${a." + "b}" style concatenation of literals
            StringBuilder sb = new StringBuilder();
            for (StringLiteralExpr lit : e.findAll(StringLiteralExpr.class)) sb.append(lit.getValue());
            return sb.toString();
        }
        return null;
    }

    /** Simple (or nested, e.g. "RestClient.Builder") type name with package qualifiers and type args removed. */
    private static String typeName(Type type) {
        if (!type.isClassOrInterfaceType()) return type.asString();
        String withScope = type.asClassOrInterfaceType().getNameWithScope();
        String[] parts = withScope.split("\\.");
        int start = 0;
        while (start < parts.length - 1 && !parts[start].isEmpty() && Character.isLowerCase(parts[start].charAt(0))) {
            start++;
        }
        return String.join(".", java.util.Arrays.copyOfRange(parts, start, parts.length));
    }

    private static String simple(String annotationName) {
        int i = annotationName.lastIndexOf('.');
        return i >= 0 ? annotationName.substring(i + 1) : annotationName;
    }

    private static String decapitalize(String s) {
        if (s.length() > 1 && Character.isUpperCase(s.charAt(0)) && Character.isUpperCase(s.charAt(1))) return s;
        return s.isEmpty() ? s : Character.toLowerCase(s.charAt(0)) + s.substring(1);
    }

    private static String firstLine(String s) {
        if (s == null) return "";
        int nl = s.indexOf('\n');
        return nl >= 0 ? s.substring(0, nl) : s;
    }
}
