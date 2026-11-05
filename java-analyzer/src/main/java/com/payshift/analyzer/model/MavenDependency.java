package com.payshift.analyzer.model;

public class MavenDependency {
    public String groupId;
    public String artifactId;
    public String version;

    public MavenDependency() {
    }

    public MavenDependency(String groupId, String artifactId, String version) {
        this.groupId = groupId;
        this.artifactId = artifactId;
        this.version = version;
    }
}
