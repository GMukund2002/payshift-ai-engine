"""Metric definitions for the baseline-vs-PayShift evaluation. Every function
here computes a metric from real measured data passed in -- none of them
invent a plausible-looking number when the underlying run didn't happen
(e.g. LLM-dependent steps with no provider configured return None, not a
guess, and the report must say so explicitly).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DetectionAccuracy:
    expected_providers: set[str]
    detected_providers: set[str]

    @property
    def true_positives(self) -> set[str]:
        return self.expected_providers & self.detected_providers

    @property
    def false_positives(self) -> set[str]:
        return self.detected_providers - self.expected_providers

    @property
    def false_negatives(self) -> set[str]:
        return self.expected_providers - self.detected_providers

    @property
    def precision(self) -> float | None:
        if not self.detected_providers:
            return None
        return len(self.true_positives) / len(self.detected_providers)

    @property
    def recall(self) -> float | None:
        if not self.expected_providers:
            return None
        return len(self.true_positives) / len(self.expected_providers)


@dataclass
class OperationDiscoveryRecall:
    expected_operations: set[str]
    discovered_operations: set[str]

    @property
    def recall(self) -> float | None:
        if not self.expected_operations:
            return None
        return len(self.expected_operations & self.discovered_operations) / len(self.expected_operations)

    @property
    def missed(self) -> set[str]:
        return self.expected_operations - self.discovered_operations


@dataclass
class EvaluationRun:
    """One row of the benchmark: either the 'baseline' (direct LLM generation,
    not run here since it requires a configured LLM) or 'payshift' (this
    repo's real pipeline) condition, for one sample app variant."""
    condition: str  # "baseline" | "payshift"
    sample_variant: str
    detection: DetectionAccuracy | None = None
    operation_recall: OperationDiscoveryRecall | None = None
    documentation_retrieval_relevant: bool | None = None  # did top retrieval actually mention the operation?
    compilation_success: bool | None = None
    test_pass_rate: float | None = None
    repair_attempts_used: int | None = None
    self_repair_succeeded: bool | None = None
    notes: list[str] = field(default_factory=list)

    def to_row(self) -> dict:
        return {
            "condition": self.condition,
            "sample_variant": self.sample_variant,
            "detection_precision": self.detection.precision if self.detection else None,
            "detection_recall": self.detection.recall if self.detection else None,
            "operation_recall": self.operation_recall.recall if self.operation_recall else None,
            "documentation_retrieval_relevant": self.documentation_retrieval_relevant,
            "compilation_success": self.compilation_success,
            "test_pass_rate": self.test_pass_rate,
            "repair_attempts_used": self.repair_attempts_used,
            "self_repair_succeeded": self.self_repair_succeeded,
            "notes": "; ".join(self.notes),
        }
