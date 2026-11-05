package com.payshift.analyzer;

import com.payshift.analyzer.model.DetectedProvider;
import com.payshift.analyzer.model.PaymentOperation;
import com.payshift.analyzer.registry.ProviderRegistry;
import com.payshift.analyzer.source.JavaSourceAnalyzer;
import org.junit.jupiter.api.Test;

import java.net.URISyntaxException;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;

class JavaSourceAnalyzerTest {

    private Path fixture(String name) throws URISyntaxException {
        return Paths.get(getClass().getClassLoader().getResource("fixtures/" + name).toURI());
    }

    @Test
    void detectsRazorpayFromImportsAndMavenDependency() throws Exception {
        Path repo = fixture("tightly-coupled");
        JavaSourceAnalyzer.Result result = new JavaSourceAnalyzer(ProviderRegistry.loadDefault()).analyze(repo);

        Optional<DetectedProvider> razorpay = result.detectedProviders.stream()
                .filter(p -> p.name.equals("razorpay")).findFirst();
        assertThat(razorpay).isPresent();
        assertThat(razorpay.get().evidence).anyMatch(e -> e.contains("sdk_import"));
    }

    @Test
    void doesNotMisattributeGenericallyNamedDomainClasses() throws Exception {
        Path repo = fixture("tightly-coupled");
        JavaSourceAnalyzer.Result result = new JavaSourceAnalyzer(ProviderRegistry.loadDefault()).analyze(repo);

        // Order.java never imports anything from com.razorpay; its mere name must not
        // generate razorpay "sdk_type_usage" evidence pointing at that file.
        Optional<DetectedProvider> razorpay = result.detectedProviders.stream()
                .filter(p -> p.name.equals("razorpay")).findFirst();
        assertThat(razorpay).isPresent();
        assertThat(razorpay.get().evidence).noneMatch(e -> e.contains("Order.java") && e.contains("sdk_type_usage"));
    }

    @Test
    void findsPaymentOperationsAndAttributesProvider() throws Exception {
        Path repo = fixture("tightly-coupled");
        JavaSourceAnalyzer.Result result = new JavaSourceAnalyzer(ProviderRegistry.loadDefault()).analyze(repo);

        List<PaymentOperation> ops = result.paymentOperations;
        assertThat(ops).anyMatch(op -> op.operation.equals("CREATE_PAYMENT") && op.className.equals("RazorpayPaymentService")
                && "razorpay".equals(op.provider));
        assertThat(ops).anyMatch(op -> op.operation.equals("CREATE_REFUND") && op.className.equals("RazorpayPaymentService"));
        assertThat(ops).anyMatch(op -> op.operation.equals("GET_PAYMENT_STATUS") && op.className.equals("RazorpayPaymentService"));
    }

    @Test
    void reportsNoProviderAbstraction_whenTightlyCoupled() throws Exception {
        Path repo = fixture("tightly-coupled");
        JavaSourceAnalyzer.Result result = new JavaSourceAnalyzer(ProviderRegistry.loadDefault()).analyze(repo);

        assertThat(result.architecture.providerAbstractionExists).isFalse();
    }

    @Test
    void detectsProviderAbstraction_whenInterfaceExistsWithImplementation() throws Exception {
        Path repo = fixture("abstracted");
        JavaSourceAnalyzer.Result result = new JavaSourceAnalyzer(ProviderRegistry.loadDefault()).analyze(repo);

        assertThat(result.architecture.providerAbstractionExists).isTrue();
        assertThat(result.architecture.multipleProvidersSupported).isTrue();
    }

    @Test
    void detectsBothProvidersBehindTheAbstraction() throws Exception {
        Path repo = fixture("abstracted");
        JavaSourceAnalyzer.Result result = new JavaSourceAnalyzer(ProviderRegistry.loadDefault()).analyze(repo);

        assertThat(result.detectedProviders).extracting(p -> p.name)
                .contains("stripe", "razorpay");
    }
}
