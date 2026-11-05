package com.payshift.analyzer.model;

import java.util.ArrayList;
import java.util.List;

public class PaymentClass {
    public String file;
    public String className;
    public String role; // CONTROLLER, SERVICE, PROVIDER_GATEWAY, WEBHOOK_HANDLER, REPOSITORY, DOMAIN, CONFIG, OTHER
    public boolean isInterface;
    public List<String> implementedBy = new ArrayList<>();
    public List<String> implementsInterfaces = new ArrayList<>();

    public PaymentClass() {
    }

    public PaymentClass(String file, String className, String role, boolean isInterface) {
        this.file = file;
        this.className = className;
        this.role = role;
        this.isInterface = isInterface;
    }
}
