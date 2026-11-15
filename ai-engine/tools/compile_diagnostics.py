"""Deterministic enrichment of javac failures with facts from the project's
real classpath, so the repair step is handed the answer instead of asked to
guess it.

Found necessary in live run 5f1db5114a03: generated code imported
`org.springframework.web.client.RestTemplateBuilder` (the class lives in
`org.springframework.boot.web.client`). javac said "cannot find symbol";
the repair model read that as a missing dependency, twice tried to edit
pom.xml (correctly refused), and spent the whole build-repair budget on a
one-line import fix. Looking the simple name up in the project's actual
dependency jars turns that into an unambiguous instruction.

Index: `mvn dependency:build-classpath` once per workspace, then every
top-level class name in those jars, cached as JSON next to the workspace.
"""
from __future__ import annotations

import json
import logging
import re
import zipfile
from pathlib import Path

from tools.java_source_index import member_signatures, type_sources

logger = logging.getLogger("payshift.tools.compile_diagnostics")

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
# javac (via maven-compiler-plugin) reports a missing class as:
#   <file>:[7,38] cannot find symbol
#     symbol:   class RestTemplateBuilder
#     location: package org.springframework.web.client
_MISSING_CLASS = re.compile(
    r"cannot find symbol\s*\n.*?symbol:\s+class\s+(?P<cls>[A-Za-z_$][\w$]*)\s*\n.*?location:\s+(?P<loc>[^\n]+)",
    re.MULTILINE,
)
_MISSING_PACKAGE = re.compile(r"package\s+(?P<pkg>[a-z_][\w.]*)\s+does not exist")
#   cannot find symbol
#     symbol:   method getPaymentId()
#     location: variable refundRequest of type com.x.RefundRequest   (or: class com.x.Y)
_MISSING_METHOD = re.compile(
    r"cannot find symbol\s*\n.*?symbol:\s+method\s+(?P<method>\w+)\((?P<args>[^)]*)\)\s*\n.*?location:\s+"
    r"(?:variable \w+ of type |class |interface )(?P<type>[\w.]+)",
    re.MULTILINE,
)
#   X is not abstract and does not override abstract method m(A) in com.x.Iface
_NOT_ABSTRACT = re.compile(
    r"(?P<cls>[\w.]+) is not abstract and does not override abstract method (?P<method>\w+)\([^)]*\) "
    r"in (?P<iface>[\w.]+)"
)
_IMPORT_LINE = re.compile(r"^\s*import\s+(?:static\s+)?(?P<fqn>[\w.]+)\s*;", re.MULTILINE)
_PACKAGE_LINE = re.compile(r"^\s*package\s+(?P<pkg>[\w.]+)\s*;", re.MULTILINE)

# Common JDK types (not in dependency jars) that generated code often uses.
_JDK_HINTS = {
    "BigDecimal": "java.math.BigDecimal", "RoundingMode": "java.math.RoundingMode",
    "Instant": "java.time.Instant", "Duration": "java.time.Duration", "Clock": "java.time.Clock",
    "HexFormat": "java.util.HexFormat", "Base64": "java.util.Base64", "UUID": "java.util.UUID",
    "Mac": "javax.crypto.Mac", "SecretKeySpec": "javax.crypto.spec.SecretKeySpec",
    "MessageDigest": "java.security.MessageDigest", "StandardCharsets": "java.nio.charset.StandardCharsets",
    "HttpClient": "java.net.http.HttpClient", "HttpRequest": "java.net.http.HttpRequest",
    "HttpResponse": "java.net.http.HttpResponse", "URI": "java.net.URI",
}

INDEX_FILE_NAME = "classpath-index.json"


def strip_ansi(text: str) -> str:
    return _ANSI.sub("", text or "")


def build_classpath_index(project_dir: Path, run_maven) -> dict[str, list[str]]:
    """simple class name -> sorted fully-qualified names found on the project's
    compile classpath. `run_maven(project_dir, goals, timeout)` is injected so
    this module stays free of subprocess details (see tools/java_tools.py)."""
    project_dir = Path(project_dir)
    cache = project_dir.parent / INDEX_FILE_NAME
    if cache.is_file():
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass

    out_file = project_dir.parent / "classpath.txt"
    code, output, _ = run_maven(project_dir, ["-q", "dependency:build-classpath",
                                              f"-Dmdep.outputFile={out_file}"], 300)
    if code != 0 or not out_file.is_file():
        logger.warning("Could not resolve classpath for diagnostics: %s", strip_ansi(output)[-500:])
        return {}

    index: dict[str, set[str]] = {}
    for jar in out_file.read_text(encoding="utf-8").strip().split(":"):
        if not jar.endswith(".jar"):
            continue
        try:
            with zipfile.ZipFile(jar) as zf:
                for name in zf.namelist():
                    if not name.endswith(".class") or "$" in name or name.startswith("META-INF/"):
                        continue
                    fqn = name[:-6].replace("/", ".")
                    index.setdefault(fqn.rsplit(".", 1)[-1], set()).add(fqn)
        except (OSError, zipfile.BadZipFile):
            continue
    result = {k: sorted(v) for k, v in index.items()}
    try:
        cache.write_text(json.dumps(result), encoding="utf-8")
    except OSError:
        pass
    return result


def project_class_index(workspace: Path) -> dict[str, list[str]]:
    """simple name -> FQNs of the project's own top-level types (src/main/java).
    Found necessary in a live eval run: generation imported the app's own
    PaymentProvider from an invented package, and with only dependency jars
    indexed the hint could not say where the real one lives -- so a repair
    invented a parallel interface instead."""
    index: dict[str, set[str]] = {}
    for java in Path(workspace).rglob("*.java"):
        rel = java.relative_to(workspace).as_posix()
        if "src/main/java/" not in rel or "/target/" in f"/{rel}":
            continue
        try:
            m = _PACKAGE_LINE.search(java.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        fqn = f"{m.group('pkg')}.{java.stem}" if m else java.stem
        index.setdefault(java.stem, set()).add(fqn)
    return {k: sorted(v) for k, v in index.items()}


def hints_for_compile_failure(output: str, index: dict[str, list[str]], workspace: Path | None = None) -> list[str]:
    """Turns "cannot find symbol: class X" / "package P does not exist" errors
    into concrete instructions backed by the project's real classpath and its
    own sources (project types take precedence)."""
    text = strip_ansi(output)
    if workspace is not None:
        project = project_class_index(workspace)
        index = {**index, **{k: v for k, v in project.items()}}
        project_fqns = {fqn for v in project.values() for fqn in v}
    else:
        project_fqns = set()
    hints: list[str] = []
    seen: set[str] = set()

    for m in _MISSING_CLASS.finditer(text):
        cls, location = m.group("cls"), m.group("loc").strip()
        if cls in seen:
            continue
        seen.add(cls)
        hints.append(_hint_for_class(cls, location, index, project_fqns))

    sources = type_sources(workspace) if workspace is not None else {}
    for m in _MISSING_METHOD.finditer(text):
        type_simple = m.group("type").split(".")[-1]
        key = f"method:{type_simple}.{m.group('method')}"
        if key in seen or type_simple not in sources:
            continue
        seen.add(key)
        sigs = member_signatures(sources[type_simple][1])
        hints.append(f"{type_simple} has no method {m.group('method')}({m.group('args')}). Its real members are: "
                     + ("; ".join(sigs) if sigs else "(none found)")
                     + f". Use one of these (or change only code generated in this run); {type_simple} itself is an "
                       f"existing file and is not editable.")

    for m in _NOT_ABSTRACT.finditer(text):
        iface_simple = m.group("iface").split(".")[-1]
        key = f"abstract:{m.group('cls')}:{iface_simple}"
        if key in seen or iface_simple not in sources:
            continue
        seen.add(key)
        sigs = member_signatures(sources[iface_simple][1])
        hints.append(f"{m.group('cls').split('.')[-1]} implements {iface_simple} but not all of its methods. "
                     f"{iface_simple} declares exactly: " + "; ".join(sigs)
                     + ". Implement every one of these with exactly these signatures.")

    for m in _MISSING_PACKAGE.finditer(text):
        pkg = m.group("pkg")
        if pkg in seen:
            continue
        seen.add(pkg)
        # Which imported classes from that package were meant?
        classes = sorted({fqn.rsplit(".", 1)[-1] for fqn in _imports_from(workspace, pkg)}) if workspace else []
        if classes:
            for cls in classes:
                if cls not in seen:
                    seen.add(cls)
                    hints.append(_hint_for_class(cls, f"package {pkg}", index, project_fqns))
        else:
            hints.append(f"Package {pkg} is not on this project's classpath. Use only libraries already "
                         f"declared in pom.xml (build files are not editable).")
    return hints


def _hint_for_class(cls: str, location: str, index: dict[str, list[str]], project_fqns: set[str] | None = None) -> str:
    candidates = index.get(cls) or ([_JDK_HINTS[cls]] if cls in _JDK_HINTS else [])
    wrong_pkg = location.removeprefix("package ").strip() if location.startswith("package ") else None
    if candidates and any(c in (project_fqns or set()) for c in candidates):
        where = ", ".join(c for c in candidates if c in project_fqns)
        return (f"{cls} already exists in this project as {where}"
                + (f" (not in package {wrong_pkg})" if wrong_pkg else "")
                + ". Import and use that existing type; do NOT create a new class or interface named " + cls + ".")
    if candidates:
        where = ", ".join(candidates[:3])
        if wrong_pkg:
            return (f"{cls} is not in package {wrong_pkg}. On this project's classpath it is: {where}. "
                    f"Fix the import; no dependency change is needed.")
        return f"{cls} is not imported where it is used. On this project's classpath it is: {where}. Add that import."
    return (f"No class named {cls} exists on this project's classpath (dependencies are fixed and pom.xml is not "
            f"editable). Use a different class that is available, or define {cls} yourself as a new file.")


def _imports_from(workspace: Path | None, package: str) -> list[str]:
    if not workspace or not Path(workspace).is_dir():
        return []
    found = []
    for java in Path(workspace).rglob("*.java"):
        if "target" in java.parts:
            continue
        try:
            for m in _IMPORT_LINE.finditer(java.read_text(encoding="utf-8", errors="replace")):
                fqn = m.group("fqn")
                if fqn.rsplit(".", 1)[0] == package:
                    found.append(fqn)
        except OSError:
            continue
    return found


def fix_misimports(workspace: Path, files: list[str], run_maven) -> list[dict]:
    """Rewrites an import whose class does not exist where it says, when exactly
    one class with that simple name exists in the project or on its classpath --
    the same thing an IDE's "organize imports" does. Found in 3 of 8 runs of the
    second live eval (RestTemplateBuilder imported from the wrong package), each
    costing a full compile + LLM repair round to fix one line.

    Never touches java.* / javax.* imports (the JDK is not indexed), nested-class
    imports, static or wildcard imports, or anything with 0 or >1 candidates.
    Returns [{file, from, to}] for the report."""
    workspace = Path(workspace)
    jar_index = build_classpath_index(workspace, run_maven)
    if not jar_index:
        return []
    project = project_class_index(workspace)
    known = {fqn for v in jar_index.values() for fqn in v} | {fqn for v in project.values() for fqn in v}
    fixes = []
    for rel in files:
        f = workspace / rel
        if not f.is_file() or not rel.endswith(".java"):
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        new_text = text
        for m in _IMPORT_LINE.finditer(text):
            line = m.group(0)
            fqn = m.group("fqn")
            if " static " in f" {line.strip()} " or fqn.startswith(("java.", "javax.")) or fqn in known:
                continue
            if fqn.rsplit(".", 1)[0] in known:  # nested class import (Outer.Inner) of a real class
                continue
            simple = fqn.rsplit(".", 1)[-1]
            candidates = project.get(simple) or jar_index.get(simple) or []
            if len(candidates) != 1:
                continue
            new_text = new_text.replace(line, line.replace(fqn, candidates[0]), 1)
            fixes.append({"file": rel, "from": fqn, "to": candidates[0]})
        if new_text != text:
            f.write_text(new_text, encoding="utf-8")
    return fixes
