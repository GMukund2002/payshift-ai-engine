package com.payshift.analyzer.model;

import java.util.ArrayList;
import java.util.List;

public class AnalysisReport {
    public String repositoryPath;
    public List<MavenDependency> dependencies = new ArrayList<>();
    public List<DetectedProvider> detectedProviders = new ArrayList<>();
    public List<PaymentClass> paymentClasses = new ArrayList<>();
    public List<PaymentOperation> paymentOperations = new ArrayList<>();
    public ArchitectureAssessment architecture = new ArchitectureAssessment();
    public List<String> errors = new ArrayList<>();
}
