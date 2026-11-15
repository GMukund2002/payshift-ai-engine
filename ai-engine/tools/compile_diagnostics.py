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
_IMPORT_LINE = re.compile(r"^\s*import\s+(?:static\s+)?(?P<fqn>[\w.]+)\s*;", re.MULTILINE)

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


def hints_for_compile_failure(output: str, index: dict[str, list[str]], workspace: Path | None = None) -> list[str]:
    """Turns "cannot find symbol: class X" / "package P does not exist" errors
    into concrete, classpath-backed instructions."""
    text = strip_ansi(output)
    hints: list[str] = []
    seen: set[str] = set()

    for m in _MISSING_CLASS.finditer(text):
        cls, location = m.group("cls"), m.group("loc").strip()
        if cls in seen:
            continue
        seen.add(cls)
        hints.append(_hint_for_class(cls, location, index))

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
                    hints.append(_hint_for_class(cls, f"package {pkg}", index))
        else:
            hints.append(f"Package {pkg} is not on this project's classpath. Use only libraries already "
                         f"declared in pom.xml (build files are not editable).")
    return hints


def _hint_for_class(cls: str, location: str, index: dict[str, list[str]]) -> str:
    candidates = index.get(cls) or ([_JDK_HINTS[cls]] if cls in _JDK_HINTS else [])
    wrong_pkg = location.removeprefix("package ").strip() if location.startswith("package ") else None
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
