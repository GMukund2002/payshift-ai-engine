package com.payshift.analyzer;

import com.payshift.analyzer.check.WiringChecker;
import com.payshift.analyzer.registry.ProviderRegistry;
import com.payshift.analyzer.source.JavaSourceAnalyzer;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Set;

import static org.assertj.core.api.Assertions.assertThat;

class WiringCheckerTest {

    @TempDir
    Path repo;

    private static final String PKG = "src/main/java/com/acme/";

    private void write(String rel, String content) throws IOException {
        Path p = repo.resolve(rel);
        Files.createDirectories(p.getParent());
        Files.writeString(p, content);
    }

    private WiringChecker.Report check(String... changed) {
        return new WiringChecker().check(repo, Set.of(changed));
    }

    private static List<String> errors(WiringChecker.Report r, String check) {
        return r.findings.stream().filter(f -> f.check.equals(check) && f.severity.equals("ERROR"))
                .map(f -> f.message).toList();
    }

    private void baseApp() throws IOException {
        write("src/main/resources/application.yml", """
                payshift:
                  stripe:
                    api-key: ${STRIPE_API_KEY:sk_test_placeholder}
                """);
        write(PKG + "provider/StripePaymentGateway.java", """
                package com.acme.provider;
                public interface StripePaymentGateway { String createPaymentIntent(String ref); }
                """);
        write(PKG + "provider/StripeApiPaymentGateway.java", """
                package com.acme.provider;
                import org.springframework.stereotype.Component;
                @Component
                public class StripeApiPaymentGateway implements StripePaymentGateway {
                    public String createPaymentIntent(String ref) { return com.stripe.Thing.create(ref); }
                }
                """);
        write(PKG + "repo/PaymentRepository.java", """
                package com.acme.repo;
                import org.springframework.data.jpa.repository.JpaRepository;
                public interface PaymentRepository extends JpaRepository<Object, Long> {}
                """);
        write(PKG + "service/PaymentService.java", """
                package com.acme.service;
                import org.springframework.stereotype.Service;
                @Service
                public class PaymentService {
                    private final StripePaymentGateway stripeGateway;
                    private final PaymentRepository payments;
                    public PaymentService(StripePaymentGateway stripeGateway, PaymentRepository payments) {
                        this.stripeGateway = stripeGateway; this.payments = payments;
                    }
                }
                """);
    }

    // ------------------------------------------------------------ the live-run failure, reproduced

    @Test
    void flagsEveryDefectInTheLiveRunsGeneratedGateway() throws IOException {
        baseApp();
        String iface = PKG + "provider/RazorpayPaymentGateway.java";
        String gateway = PKG + "provider/RazorpayApiPaymentGateway.java";
        write(iface, """
                package com.acme.provider;
                public interface RazorpayPaymentGateway { void createRefund(String paymentId); }
                """);
        // Verbatim shape of what gpt-4o generated in run 3fe329852a5d.
        write(gateway, """
                package com.acme.provider;
                import org.slf4j.Logger;
                import org.slf4j.LoggerFactory;
                import org.springframework.beans.factory.annotation.Value;
                import org.springframework.stereotype.Component;
                import org.springframework.web.client.RestTemplate;

                @Component
                public class RazorpayApiPaymentGateway {
                    private static final Logger logger = LoggerFactory.getLogger(RazorpayApiPaymentGateway.class);
                    private final RestTemplate restTemplate;
                    @Value("${razorpay.api.key}")
                    private String apiKey;
                    @Value("${razorpay.api.secret}")
                    private String apiSecret;

                    public RazorpayApiPaymentGateway(RestTemplate restTemplate) { this.restTemplate = restTemplate; }

                    public void createRefund(String paymentId) {
                        String url = String.format("https://api.razorpay.com/v1/payments/%s/refund", paymentId);
                        // Implement the logic to call Razorpay API and create a refund
                        logger.info("Creating refund for payment ID: {}", paymentId);
                    }
                }
                """);

        WiringChecker.Report r = check(iface, gateway);

        assertThat(r.passed).isFalse();
        assertThat(errors(r, "missing_bean")).singleElement().asString()
                .contains("RestTemplate").contains("RestTemplateBuilder");
        assertThat(errors(r, "unresolved_placeholder")).hasSize(2)
                .anyMatch(m -> m.contains("razorpay.api.key")).anyMatch(m -> m.contains("razorpay.api.secret"));
        assertThat(errors(r, "stub_method")).singleElement().asString().contains("createRefund");
        assertThat(errors(r, "unimplemented_interface")).singleElement().asString().contains("RazorpayPaymentGateway");
    }

    @Test
    void aCorrectlyWiredRealImplementationPasses() throws IOException {
        baseApp();
        write("src/main/resources/application.yml", """
                payshift:
                  razorpay:
                    key-id: ${RAZORPAY_KEY_ID:rzp_test_placeholder}
                """);
        String iface = PKG + "provider/RazorpayPaymentGateway.java";
        String gateway = PKG + "provider/RazorpayApiPaymentGateway.java";
        write(iface, """
                package com.acme.provider;
                public interface RazorpayPaymentGateway { String createOrder(long amount); }
                """);
        write(gateway, """
                package com.acme.provider;
                @Component
                public class RazorpayApiPaymentGateway implements RazorpayPaymentGateway {
                    private final RestTemplate restTemplate;
                    private final String keyId;
                    private final String secret;
                    public RazorpayApiPaymentGateway(RestTemplateBuilder builder,
                                                     @Value("${payshift.razorpay.keyId}") String keyId,
                                                     @Value("${payshift.razorpay.key-secret:placeholder}") String secret) {
                        this.restTemplate = builder.build(); this.keyId = keyId; this.secret = secret;
                    }
                    public String createOrder(long amount) {
                        Map body = restTemplate.postForObject("https://api.razorpay.com/v1/orders", Map.of("amount", amount), Map.class);
                        return (String) body.get("id");
                    }
                }
                """);

        WiringChecker.Report r = check(iface, gateway);

        assertThat(r.findings).isEmpty();
        assertThat(r.passed).isTrue();
    }

    // ------------------------------------------------------------ beans

    @Test
    void aBeanMethodSatisfiesTheDependency() throws IOException {
        baseApp();
        write(PKG + "config/HttpConfig.java", """
                package com.acme.config;
                @Configuration
                public class HttpConfig {
                    @Bean RestTemplate razorpayRestTemplate(RestTemplateBuilder b) { return b.build(); }
                }
                """);
        String client = PKG + "provider/Client.java";
        write(client, """
                package com.acme.provider;
                @Component
                public class Client {
                    private final RestTemplate rt;
                    public Client(RestTemplate rt) { this.rt = rt; }
                    public String ping() { return rt.getForObject("https://x", String.class); }
                }
                """);
        assertThat(check(client).findings).isEmpty();
    }

    @Test
    void secondImplementationOfAnInjectedInterfaceIsAmbiguousUnlessPrimary() throws IOException {
        baseApp();
        String adapter = PKG + "provider/RazorpayAdapter.java";
        write(adapter, """
                package com.acme.provider;
                @Component
                public class RazorpayAdapter implements StripePaymentGateway {
                    public String createPaymentIntent(String ref) { return http.post(ref); }
                }
                """);
        WiringChecker.Report r = check(adapter);
        assertThat(errors(r, "ambiguous_bean")).singleElement().asString()
                .contains("PaymentService").contains("stripeApiPaymentGateway").contains("razorpayAdapter");

        write(adapter, """
                package com.acme.provider;
                @Primary @Component
                public class RazorpayAdapter implements StripePaymentGateway {
                    public String createPaymentIntent(String ref) { return http.post(ref); }
                }
                """);
        assertThat(errors(check(adapter), "ambiguous_bean")).isEmpty();
    }

    @Test
    void preExistingIssuesInUntouchedFilesNeverBlock() throws IOException {
        baseApp();
        write(PKG + "legacy/Legacy.java", """
                package com.acme.legacy;
                @Service
                public class Legacy {
                    public Legacy(RestTemplate rt, @Value("${not.defined}") String x) {}
                    public void later() { /* TODO implement */ }
                }
                """);
        String unrelated = PKG + "provider/Unrelated.java";
        write(unrelated, """
                package com.acme.provider;
                public class Unrelated { public int one() { return 1 + 0; } }
                """);
        assertThat(check(unrelated).findings).isEmpty();
    }

    @Test
    void lombokRequiredArgsConstructorFieldsAreInjectionPoints() throws IOException {
        baseApp();
        String svc = PKG + "service/Lomboked.java";
        write(svc, """
                package com.acme.service;
                @Service @RequiredArgsConstructor
                public class Lomboked {
                    private final RestTemplate rt;
                    private final PaymentRepository payments;
                    private int counter = 0;
                    public Object go() { return rt.getForObject("https://x", Object.class); }
                }
                """);
        assertThat(errors(check(svc), "missing_bean")).singleElement().asString().contains("RestTemplate");
    }

    // ------------------------------------------------------------ placeholders

    @Test
    void placeholderOnlyInTestConfigIsAWarningNotAnError() throws IOException {
        baseApp();
        write("src/test/resources/application.yml", "razorpay:\n  key: test\n");
        String cls = PKG + "provider/Keyed.java";
        write(cls, """
                package com.acme.provider;
                @Component
                public class Keyed {
                    public Keyed(@Value("${razorpay.key}") String key) {}
                    public String id() { return "x" + 1; }
                }
                """);
        WiringChecker.Report r = check(cls);
        assertThat(r.passed).isTrue();
        assertThat(r.findings).singleElement().satisfies(f -> {
            assertThat(f.check).isEqualTo("unresolved_placeholder");
            assertThat(f.severity).isEqualTo("WARNING");
        });
    }

    @Test
    void nestedDefaultsAndMultiplePlaceholdersAreParsedAtTopLevel() {
        List<String[]> ph = WiringChecker.topLevelPlaceholders("${a:${b}}-${c}");
        assertThat(ph).hasSize(2);
        assertThat(ph.get(0)[0]).isEqualTo("a");
        assertThat(ph.get(0)[1]).isEqualTo("${b}");
        assertThat(ph.get(1)[0]).isEqualTo("c");
        assertThat(ph.get(1)[1]).isNull();
    }

    // ------------------------------------------------------------ stubs

    @Test
    void notImplementedThrowIsAStubButRealCodeWithATodoIsOnlyAWarning() throws IOException {
        baseApp();
        String cls = PKG + "provider/Mixed.java";
        write(cls, """
                package com.acme.provider;
                public class Mixed {
                    public String a() { throw new UnsupportedOperationException("Not implemented yet"); }
                    public String b(String x) {
                        // TODO: add retries
                        return x.trim();
                    }
                }
                """);
        WiringChecker.Report r = check(cls);
        assertThat(errors(r, "stub_method")).singleElement().asString().contains("Mixed.a()");
        assertThat(r.findings).anyMatch(f -> f.severity.equals("WARNING") && f.message.contains("Mixed.b()"));
    }

    // ------------------------------------------------------------ registry / analyzer regressions

    @Test
    void squareIsDetectedOnlyByItsPaymentsSdkNotOtherComSquareupLibraries() {
        ProviderRegistry registry = ProviderRegistry.loadDefault();
        assertThat(registry.matchByMavenDependency("com.squareup", "javapoet")).isNull();
        assertThat(registry.matchByImport("com.squareup.moshi.Moshi")).isNull();
        assertThat(registry.matchByMavenDependency("com.squareup", "square").id).isEqualTo("square");
        assertThat(registry.matchByImport("com.squareup.square.SquareClient").id).isEqualTo("square");
    }

    @Test
    void braintreeIsDetectedAsBraintreeNotPaypal() {
        ProviderRegistry registry = ProviderRegistry.loadDefault();
        assertThat(registry.matchByImport("com.braintreegateway.BraintreeGateway").id).isEqualTo("braintree");
        assertThat(registry.matchByMavenDependency("com.braintreepayments.gateway", "braintree-java").id)
                .isEqualTo("braintree");
    }

    @Test
    void testSourcesAreNotTreatedAsPaymentOperations() throws IOException {
        baseApp();
        write("src/test/java/com/acme/WebhookIntegrationTest.java", """
                package com.acme;
                class WebhookIntegrationTest { void validWebhook_marksPaymentSucceeded() {} }
                """);
        JavaSourceAnalyzer.Result result = new JavaSourceAnalyzer(ProviderRegistry.loadDefault()).analyze(repo);
        assertThat(result.paymentOperations).noneMatch(op -> op.sourceFile.contains("src/test/"));
        assertThat(result.paymentClasses).noneMatch(c -> c.file.contains("src/test/"));
    }

    @Test
    void entityAccessorsAreNotPaymentOperations() throws IOException {
        write(PKG + "domain/Payment.java", """
                package com.acme.domain;
                @Entity
                public class Payment {
                    public String getStatus() { return status; }
                    public void applyRefund(long amount) { refunded += amount; }
                }
                """);
        JavaSourceAnalyzer.Result result = new JavaSourceAnalyzer(ProviderRegistry.loadDefault()).analyze(repo);
        assertThat(result.paymentOperations).noneMatch(op -> op.className.equals("Payment"));
        assertThat(result.paymentClasses).anyMatch(c -> c.className.equals("Payment") && c.role.equals("DOMAIN"));
    }
}
