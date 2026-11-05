package com.payshift.analyzer.pom;

import com.payshift.analyzer.model.MavenDependency;
import org.apache.maven.model.Model;
import org.apache.maven.model.io.xpp3.MavenXpp3Reader;

import java.io.FileReader;
import java.io.IOException;
import java.io.Reader;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.stream.Stream;

public class PomAnalyzer {

    public List<MavenDependency> findDependencies(Path repositoryRoot) {
        List<MavenDependency> dependencies = new ArrayList<>();
        try (Stream<Path> paths = Files.walk(repositoryRoot)) {
            List<Path> pomFiles = paths
                    .filter(p -> p.getFileName().toString().equals("pom.xml"))
                    .filter(p -> !isUnderBuildOutputDir(repositoryRoot, p))
                    .toList();
            for (Path pom : pomFiles) {
                dependencies.addAll(parsePom(pom));
            }
        } catch (IOException e) {
            dependencies.add(new MavenDependency("ERROR", "could-not-walk-repository: " + e.getMessage(), null));
        }
        return dependencies;
    }

    /**
     * Excludes build-output directories by inspecting path segments RELATIVE to the
     * repository root -- not the absolute path, which could itself happen to sit
     * inside a directory named "target" (e.g. this project's own build output).
     */
    public static boolean isUnderBuildOutputDir(Path repositoryRoot, Path file) {
        Path relative = repositoryRoot.relativize(file);
        for (int i = 0; i < relative.getNameCount() - 1; i++) {
            String segment = relative.getName(i).toString();
            if (segment.equals("target") || segment.equals("build") || segment.equals(".git")
                    || segment.equals("node_modules")) {
                return true;
            }
        }
        return false;
    }

    private List<MavenDependency> parsePom(Path pomPath) {
        List<MavenDependency> result = new ArrayList<>();
        try (Reader reader = new FileReader(pomPath.toFile())) {
            MavenXpp3Reader xpp3Reader = new MavenXpp3Reader();
            Model model = xpp3Reader.read(reader);
            if (model.getDependencies() != null) {
                for (org.apache.maven.model.Dependency d : model.getDependencies()) {
                    result.add(new MavenDependency(d.getGroupId(), d.getArtifactId(), d.getVersion()));
                }
            }
        } catch (Exception e) {
            result.add(new MavenDependency("ERROR", "could-not-parse:" + pomPath + " - " + e.getMessage(), null));
        }
        return result;
    }
}
