"""Subprocess wrapper around the java-analyzer CLI (Phase 2). This is the one
and only way the Python side learns about a repository's Java source --
deterministic static analysis, never the LLM guessing at file contents.
"""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from schemas.providers import RepositoryAnalysis

logger = logging.getLogger("payshift.tools.repository")

AI_ENGINE_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = AI_ENGINE_ROOT.parent

# "dist/" is a committed, deploy-ready copy (so a fresh clone / cloud deploy
# works with no build step); "target/" is local `make build-analyzer` output,
# checked second so a local rebuild is always picked up over the vendored copy.
_ANALYZER_JAR_CANDIDATES = [
    REPO_ROOT / "java-analyzer" / "target" / "java-analyzer.jar",
    REPO_ROOT / "java-analyzer" / "dist" / "java-analyzer.jar",
]


def _resolve_analyzer_jar() -> Path:
    for candidate in _ANALYZER_JAR_CANDIDATES:
        if candidate.exists():
            return candidate
    return _ANALYZER_JAR_CANDIDATES[0]  # default, for the "not found" error message


ANALYZER_JAR = _resolve_analyzer_jar()


class RepositoryAnalysisError(RuntimeError):
    pass


def analyze_repository(repository_path: Path | str, timeout_seconds: int = 120) -> RepositoryAnalysis:
    repository_path = Path(repository_path).resolve()
    if not repository_path.is_dir():
        raise RepositoryAnalysisError(f"Not a directory: {repository_path}")
    if not ANALYZER_JAR.exists():
        raise RepositoryAnalysisError(
            f"java-analyzer.jar not found at {ANALYZER_JAR}. Build it with "
            f"'mvn -s ../settings.xml package' in java-analyzer/ first."
        )

    cmd = ["java", "-jar", str(ANALYZER_JAR), str(repository_path)]
    logger.info("Running repository analyzer: %s", " ".join(cmd))
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_seconds, check=False)
    except subprocess.TimeoutExpired as e:
        raise RepositoryAnalysisError(f"Analyzer timed out after {timeout_seconds}s") from e

    if result.returncode != 0:
        raise RepositoryAnalysisError(
            f"Analyzer exited with code {result.returncode}.\nstderr: {result.stderr}\nstdout: {result.stdout[:2000]}"
        )

    try:
        raw = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RepositoryAnalysisError(f"Analyzer did not emit valid JSON: {e}\nstdout: {result.stdout[:2000]}") from e

    return RepositoryAnalysis.model_validate(raw)
