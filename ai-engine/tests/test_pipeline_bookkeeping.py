"""Bookkeeping regressions found running the real pipeline against a real LLM
(live run 3fe329852a5d and README runs 1-6):

- a repair used to REPLACE generated_files with just its own patch, so later
  diagnosis lost sight of the original generation and the diff/report only
  showed the last repair;
- the report listed what the plan said, not what was written to disk;
- a planner CREATE on an existing path silently overwrote that file, and a
  repair could rewrite an existing test or any unrelated production file;
- a repair whose every file was rejected still triggered a full recompile
  and retest of an unchanged workspace;
- VERIFIED could be reported with no test run at all.
"""
import json
import uuid
from pathlib import Path

import pytest

from agent.apply_patch import apply_patch
from agent.graph import _route_after_repair
from agent.state import MAX_REPAIR_ATTEMPTS
from agent.planning import _normalize_file_changes
from agent.repair import diagnose_failures, repair_code
from agent.reporting import generate_report
from llm.client import parse_json_object
from tests.fakes import FakeLLMClient

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MERCHANT_APP = REPO_ROOT / "sample-apps" / "merchant-app"
NEW_FILE = "src/main/java/com/payshift/merchant/provider/NewGateway.java"
EXISTING_MAIN = "src/main/java/com/payshift/merchant/service/PaymentService.java"
EXISTING_TEST = "src/test/java/com/payshift/merchant/PaymentFlowIntegrationTest.java"
STRIPE_PORT = "src/main/java/com/payshift/merchant/provider/StripePaymentGateway.java"


def _base_state(**extra):
    state = {"repository_path": str(MERCHANT_APP), "run_id": "bk-" + uuid.uuid4().hex[:8],
             "target_provider": "razorpay"}
    state.update(extra)
    return state


# ---------------------------------------------------------------- apply_patch

def test_apply_patch_accumulates_across_passes_and_reports_from_disk():
    state = _base_state(pending_patch=[{"path": NEW_FILE, "content": "class A {}\n"}])
    state.update(apply_patch(state))
    original_service = (MERCHANT_APP / EXISTING_MAIN).read_text()

    # Second pass (a repair) touches a different file only.
    state["pending_patch"] = [{"path": EXISTING_MAIN, "content": original_service + "// edited\n"}]
    state.update(apply_patch(state))

    assert state["applied_changes"] == {"created": [NEW_FILE], "modified": [EXISTING_MAIN]}
    assert {f["path"] for f in state["generated_files"]} == {NEW_FILE, EXISTING_MAIN}
    # The diff is cumulative against the original, not just the last patch.
    assert NEW_FILE in state["changes_diff"] and EXISTING_MAIN in state["changes_diff"]
    assert state["pending_patch"] is None


def test_apply_patch_never_overwrites_an_existing_test_file():
    state = _base_state(pending_patch=[{"path": EXISTING_TEST, "content": "// gutted"}])
    result = apply_patch(state)
    assert Path(result["workspace_path"], EXISTING_TEST).read_text() == (MERCHANT_APP / EXISTING_TEST).read_text()
    assert result["rejected_patch_files"][0]["path"] == EXISTING_TEST
    assert result["applied_changes"] == {"created": [], "modified": []}


def test_apply_patch_rewriting_a_file_back_to_original_is_not_a_change():
    original = (MERCHANT_APP / EXISTING_MAIN).read_text()
    result = apply_patch(_base_state(pending_patch=[{"path": EXISTING_MAIN, "content": original}]))
    assert result["applied_changes"] == {"created": [], "modified": []}


# ---------------------------------------------------------------- planning

def test_create_on_existing_file_becomes_modify_and_existing_tests_are_dropped():
    creates, modifies = _normalize_file_changes(
        [{"path": NEW_FILE, "reason": "new", "change_type": "CREATE"},
         {"path": EXISTING_MAIN, "reason": "oops, exists", "change_type": "CREATE"},
         {"path": EXISTING_TEST, "reason": "overwrite test", "change_type": "CREATE"},
         {"path": "src/test/java/com/payshift/merchant/NewProviderTest.java", "reason": "new test", "change_type": "CREATE"}],
        [{"path": NEW_FILE, "reason": "duplicate", "change_type": "MODIFY"}],
        str(MERCHANT_APP),
    )
    assert [c.path for c in creates] == [NEW_FILE, "src/test/java/com/payshift/merchant/NewProviderTest.java"]
    assert [m.path for m in modifies] == [EXISTING_MAIN]
    assert all(m.change_type == "MODIFY" for m in modifies)


# ---------------------------------------------------------------- repair scope

def _repair_state():
    state = _base_state(
        integration_plan={"files_to_create": [{"path": NEW_FILE}], "files_to_modify": []},
        pending_patch=[{"path": NEW_FILE, "content": "class A {}\n"}],
        compilation_result={"success": False, "raw_output_tail": "boom", "duration_seconds": 1.0},
        diagnosis={"diagnosis_summary": "missing bean", "files_to_inspect": [], "doc_query": None},
    )
    state.update(apply_patch(state))
    return state


def test_repair_scope_accepts_planned_new_and_config_files_rejects_the_rest():
    state = _repair_state()
    llm = FakeLLMClient(responses=[json.dumps({"patch_description": "fix", "files": [
        {"path": NEW_FILE, "content": "class A { int x; }\n"},                                  # generated -> ok
        {"path": "src/main/java/com/payshift/merchant/config/HttpConfig.java", "content": "class C {}"},  # new -> ok
        {"path": "src/main/resources/application.yml", "content": "a: 1\n"},                    # main config -> ok
        {"path": STRIPE_PORT, "content": "// rewritten"},                                       # existing, unplanned -> no
        {"path": EXISTING_TEST, "content": "// gutted"},                                        # protected -> no
    ]})])
    result = repair_code(state, llm)

    accepted = {f["path"] for f in result["pending_patch"]}
    assert accepted == {NEW_FILE, "src/main/java/com/payshift/merchant/config/HttpConfig.java",
                        "src/main/resources/application.yml"}
    rejected = {r["path"]: r["reason"] for r in result["repair_attempts"][-1]["files_rejected"]}
    assert set(rejected) == {STRIPE_PORT, EXISTING_TEST}
    assert "protected" in rejected[EXISTING_TEST]


def test_noop_repair_is_recorded_and_skips_recompile():
    state = _repair_state()
    llm = FakeLLMClient(responses=[json.dumps({"patch_description": "edit the test instead",
                                               "files": [{"path": EXISTING_TEST, "content": "// gutted"}]})])
    result = repair_code(state, llm)
    attempt = result["repair_attempts"][-1]
    assert result["pending_patch"] == []
    assert attempt["patch_applied"] is False and attempt["recompiled"] is False

    state.update(result)
    assert _route_after_repair(state) == "diagnose_failures"   # budget left: re-diagnose, don't recompile
    state["repair_count"] = MAX_REPAIR_ATTEMPTS
    assert _route_after_repair(state) == "generate_report"     # budget gone: stop


def test_next_diagnosis_is_told_what_was_already_tried_and_rejected():
    state = _repair_state()
    state.update(repair_code(state, FakeLLMClient(responses=[json.dumps({
        "patch_description": "edit the test instead", "files": [{"path": EXISTING_TEST, "content": "x"}]})])))

    llm = FakeLLMClient(responses=[json.dumps({"diagnosis_summary": "s", "likely_cause": "c", "confidence": "LOW",
                                               "files_to_inspect": [], "doc_query": None})])
    diagnose_failures(state, llm)
    prompt = llm.calls[0][1]
    assert "PREVIOUS REPAIR ATTEMPTS" in prompt and "edit the test instead" in prompt
    assert "existing tests are protected" in prompt


# ---------------------------------------------------------------- report

def _passing_tests(tests_run=11):
    return {"success": True, "tests_run": tests_run, "failures": 0, "errors": 0, "skipped": 0,
            "cases": [], "raw_output_tail": "", "duration_seconds": 1.0}


def test_report_lists_files_from_disk_and_includes_llm_usage():
    llm = FakeLLMClient(responses=['{"a": 1}'])
    llm.complete_json("sys", "user", step="create_plan")
    state = _base_state(
        operation_mode="ADD_PSP",
        integration_plan={"files_to_create": [{"path": "Planned.java"}], "files_to_modify": [],
                          "capability_model": {"capabilities": []}},
        applied_changes={"created": ["Actual.java"], "modified": []},
        compilation_result={"success": True, "raw_output_tail": "", "duration_seconds": 1.0},
        test_result=_passing_tests(),
    )
    report = generate_report(state, llm=llm)["report"]
    assert report["files_created"] == ["Actual.java"]
    assert report["planned_files_to_create"] == ["Planned.java"]
    assert report["final_status"] == "VERIFIED"
    assert report["llm_usage"]["calls"] == 1 and "create_plan" in report["llm_usage"]["by_step"]


@pytest.mark.parametrize("override", [
    {"test_result": None},                                   # compiled, never tested
    {"test_result": _passing_tests(tests_run=0)},             # "passed" with nothing run
    {"static_check_result": {"passed": False, "findings": []}},
    {"blocked": True, "blocker_reason": "diagnosis failed"},
])
def test_verified_requires_every_gate(override):
    state = _base_state(
        operation_mode="ADD_PSP", integration_plan={"capability_model": {"capabilities": []}},
        compilation_result={"success": True, "raw_output_tail": "", "duration_seconds": 1.0},
        test_result=_passing_tests(),
    )
    state.update(override)
    assert generate_report(state)["final_status"] == "UNRESOLVED_FAILURE"


def test_blocked_before_any_code_reports_blocked_with_reason():
    out = generate_report(_base_state(operation_mode="ADD_PSP", blocked=True, blocker_reason="no docs"))
    assert out["final_status"] == "BLOCKED"
    assert out["report"]["blocker_reason"] == "no docs"


# ---------------------------------------------------------------- llm parsing

@pytest.mark.parametrize("raw", [
    '{"a": 1}',
    '```json\n{"a": 1}\n```',
    'Sure! Here is the JSON:\n{"a": 1}\nHope that helps.',
])
def test_parse_json_object_tolerates_fences_and_prose(raw):
    assert parse_json_object(raw) == {"a": 1}


@pytest.mark.parametrize("raw", ["not json", "[1, 2]", '{"a": '])
def test_parse_json_object_rejects_non_objects(raw):
    with pytest.raises(ValueError):
        parse_json_object(raw)
