package com.payshift.analyzer.source;

import com.github.javaparser.ast.body.ClassOrInterfaceDeclaration;
import com.github.javaparser.ast.body.MethodDeclaration;

import java.util.ArrayList;
import java.util.List;

class ClassInfo {
    final String simpleName;
    final String file;
    final boolean isInterface;
    final List<String> annotations = new ArrayList<>();
    final List<String> implementedTypeNames = new ArrayList<>();
    final List<String> extendedTypeNames = new ArrayList<>();
    final List<String> fieldAndParamTypeNames = new ArrayList<>();
    final List<MethodDeclaration> methods;
    final ClassOrInterfaceDeclaration declaration;

    ClassInfo(String simpleName, String file, boolean isInterface,
              List<MethodDeclaration> methods, ClassOrInterfaceDeclaration declaration) {
        this.simpleName = simpleName;
        this.file = file;
        this.isInterface = isInterface;
        this.methods = methods;
        this.declaration = declaration;
    }
}
