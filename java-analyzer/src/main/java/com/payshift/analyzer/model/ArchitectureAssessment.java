package com.payshift.analyzer.model;

import java.util.ArrayList;
import java.util.List;

public class ArchitectureAssessment {
    public boolean providerAbstractionExists;
    public boolean multipleProvidersSupported;
    public List<String> abstractionInterfaces = new ArrayList<>();
    public List<String> warnings = new ArrayList<>();
}
