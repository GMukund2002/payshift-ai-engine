"""Small, deterministic facts about a Java project's own sources, used to give
the LLM ground truth instead of letting it guess -- every item here was
motivated by a failure in the live evaluation:

- application base packages: new classes placed outside the component-scanned
  package silently don't exist at runtime (eval-stripe-direct-checkout-2);
- the real source of existing types a new file must use: generated code
  called refundRequest.getPaymentId() on a record that only has amount(),
  event.setPayload() on an entity with no setter, and implemented only part
  of an existing PaymentProvider interface (eval round 2, 4 of 6 failures);
- member signatures of a type, for compile-error hints.

Regex-based on purpose (fast, no JVM): it only needs declarations, not a full
parse, and every use degrades to "no extra context" rather than failing.
"""
from __future__ import annotations

import re
from pathlib import Path

_PACKAGE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.MULTILINE)
_SPRING_BOOT_APP = re.compile(r"@SpringBootApplication\b")
_COMPONENT_SCAN_PACKAGES = re.compile(r"@ComponentScan\s*\(([^)]*)\)", re.DOTALL)
_STRING = re.compile(r'"([a-z_][\w.]*)"')
_MEMBER = re.compile(
    r"^\s*(?:public|protected)?\s*(?:static\s+)?(?:default\s+)?(?:abstract\s+)?(?:final\s+)?"
    r"(?:<[^>]+>\s*)?[\w.<>\[\], ?]+\s+(\w+)\s*\(([^)]*)\)\s*(?:throws [\w., ]+)?\s*[;{]",
    re.MULTILINE,
)
_RECORD = re.compile(r"\brecord\s+(\w+)\s*\(([^)]*)\)")
_JAVA_KEYWORDS = {"if", "for", "while", "switch", "catch", "return", "new", "else", "try", "synchronized"}


def main_java_files(root: Path) -> list[Path]:
    root = Path(root)
    return [p for p in root.rglob("*.java")
            if "src/main/java/" in p.relative_to(root).as_posix() and "target" not in p.relative_to(root).parts]


def spring_boot_base_packages(root: Path) -> list[str]:
    """Packages Spring Boot component-scans: each @SpringBootApplication class's
    package plus literal @ComponentScan base packages."""
    packages: list[str] = []
    for f in main_java_files(root):
        text = f.read_text(encoding="utf-8", errors="replace")
        if not _SPRING_BOOT_APP.search(text) and "@ComponentScan" not in text:
            continue
        pkg = _PACKAGE.search(text)
        if _SPRING_BOOT_APP.search(text) and pkg:
            packages.append(pkg.group(1))
        for m in _COMPONENT_SCAN_PACKAGES.finditer(text):
            packages += _STRING.findall(m.group(1))
    return sorted(set(packages))


def rebase_path_into_scan(path: str, base_packages: list[str]) -> str:
    """If a src/main/java path's package is outside every scanned package, move it
    under the first base package, keeping the part after the common prefix:
    com/acme/payment/config/X.java with base com.acme.checkout ->
    com/acme/checkout/payment/config/X.java. Other paths are returned unchanged."""
    marker = next((m for m in ("src/main/java/", "src/test/java/") if m in path), None)
    if marker is None or not base_packages or not path.endswith(".java"):
        return path
    prefix, rel = path.split(marker, 1)
    parts = rel.split("/")
    pkg_parts, filename = parts[:-1], parts[-1]
    pkg = ".".join(pkg_parts)
    if any(pkg == b or pkg.startswith(b + ".") for b in base_packages):
        return path
    base = base_packages[0].split(".")
    common = 0
    while common < min(len(base), len(pkg_parts)) and base[common] == pkg_parts[common]:
        common += 1
    new_pkg = base + pkg_parts[common:]
    return f"{prefix}{marker}{'/'.join(new_pkg)}/{filename}"


def type_sources(root: Path) -> dict[str, tuple[str, str]]:
    """simple type name -> (relative path, source) for top-level project types."""
    root = Path(root)
    out = {}
    for f in main_java_files(root):
        out.setdefault(f.stem, (f.relative_to(root).as_posix(), f.read_text(encoding="utf-8", errors="replace")))
    return out


def relevant_existing_sources(root: Path, mention_text: str, always: list[str] | None = None,
                              max_chars: int = 24_000) -> dict[str, str]:
    """Source of existing project types whose simple name appears (as a word) in
    `mention_text` -- e.g. the plan, the target file's reason, and files already
    generated -- plus `always` (e.g. the abstraction interface). Smallest first,
    so many small DTOs/interfaces fit before one large service would."""
    sources = type_sources(root)
    wanted = set(always or [])
    for name in sources:
        if re.search(rf"\b{re.escape(name)}\b", mention_text):
            wanted.add(name)
    picked: dict[str, str] = {}
    total = 0
    for name in sorted(wanted & sources.keys(), key=lambda n: len(sources[n][1])):
        rel, src = sources[name]
        if total + len(src) > max_chars:
            continue
        picked[rel] = src
        total += len(src)
    return picked


def member_signatures(source: str) -> list[str]:
    """Method signatures (and record components as accessor methods) declared in
    a type's source -- what code using that type can actually call."""
    sigs = []
    for m in _RECORD.finditer(source):
        for comp in [c.strip() for c in m.group(2).split(",") if c.strip()]:
            name = comp.split()[-1]
            sigs.append(f"{name}()  [record component: {comp}]")
    for m in _MEMBER.finditer(source):
        name = m.group(1)
        if name in _JAVA_KEYWORDS:
            continue
        line = " ".join(m.group(0).strip().rstrip("{;").split())
        sigs.append(line)
    seen, out = set(), []
    for s in sigs:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out
