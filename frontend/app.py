"""PayShift AI -- Streamlit dashboard (Phase 13).

Every screen here calls the real backend: the java-analyzer subprocess, the
live RAG pipeline, and the actual LangGraph StateGraph (streamed node by
node, not run silently and summarized after the fact). When no LLM provider
is configured, the pipeline still runs end to end and genuinely reports
itself as blocked at the first reasoning step -- this UI never fabricates
a plan, generated code, or test results to paper over that.
"""
import json
import os
import shutil
import sys
import uuid
import zipfile
from pathlib import Path

import streamlit as st

AI_ENGINE_ROOT = Path(__file__).resolve().parent.parent / "ai-engine"
REPO_ROOT = AI_ENGINE_ROOT.parent
sys.path.insert(0, str(AI_ENGINE_ROOT))

st.set_page_config(page_title="PayShift AI", layout="wide")

# Streamlit Cloud secrets (set in the app's Secrets panel, TOML format) don't
# become OS env vars on their own -- promote them so the existing env-var-based
# config (get_llm_client, storage/db.py's DATABASE_URL) works unchanged, locally
# or deployed, with no code branching on "am I on Cloud". Must run after
# set_page_config: touching st.secrets with none configured (plain local dev)
# enqueues a Streamlit notice, which errors if it's the first command.
try:
    for _k, _v in st.secrets.items():
        os.environ.setdefault(_k, str(_v))
except Exception:
    pass

from agent.graph import build_graph  # noqa: E402
from llm.client import NullLLMClient, get_llm_client  # noqa: E402
from storage.db import backend_label, list_runs, save_run_report  # noqa: E402
from tools.repository_tools import RepositoryAnalysisError, analyze_repository  # noqa: E402

SAMPLE_APP = REPO_ROOT / "sample-apps" / "merchant-app"
UPLOADS_DIR = REPO_ROOT / "workspaces" / "uploads"
MAX_ZIP_UNCOMPRESSED_BYTES = 100 * 1024 * 1024

if "step" not in st.session_state:
    st.session_state.step = 1
    st.session_state.repo_path = None
    st.session_state.operation_mode = None
    st.session_state.existing_provider_hint = None
    st.session_state.target_provider = None
    st.session_state.target_provider_doc_url = None
    st.session_state.analysis = None
    st.session_state.final_state = None
    st.session_state.run_log = []


def goto(step: int):
    st.session_state.step = step


def safe_extract_zip(uploaded_file) -> Path:
    dest = UPLOADS_DIR / uuid.uuid4().hex[:12]
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(uploaded_file) as zf:
        total_size = 0
        for info in zf.infolist():
            name = info.filename
            if name.startswith("/") or ".." in Path(name).parts:
                raise ValueError(f"Refusing unsafe zip entry: {name}")
            total_size += info.file_size
            if total_size > MAX_ZIP_UNCOMPRESSED_BYTES:
                raise ValueError("Archive exceeds the 100MB uncompressed size limit")
        zf.extractall(dest)
    # If the zip has one top-level directory, treat that as the project root.
    children = list(dest.iterdir())
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    return dest


st.title("PayShift AI")
st.caption("Provider-agnostic agentic payment integration & migration platform")

with st.sidebar:
    st.subheader("Run history")
    st.caption(f"Data backend: **{backend_label()}**")
    past_runs = list_runs(limit=20)
    if not past_runs:
        st.caption("No runs recorded yet.")
    for r in past_runs:
        icon = {"VERIFIED": "✅", "UNRESOLVED_FAILURE": "❌"}.get(r["final_status"], "⚠️")
        st.caption(f"{icon} `{r['run_id']}` — {r['operation_mode']} → {r['target_provider']}")

steps = ["1. Upload", "2. Mode", "3. Providers", "4. Target", "5. Analysis", "6. Plan", "7. Execution", "8. Results"]
st.progress((st.session_state.step - 1) / (len(steps) - 1), text=steps[st.session_state.step - 1])

llm = get_llm_client()
if isinstance(llm, NullLLMClient):
    st.warning(
        "No LLM provider is configured (OPENAI_API_KEY / ANTHROPIC_API_KEY not set). "
        "Repository analysis and documentation retrieval below are fully real and will run; "
        "the reasoning steps (architecture understanding, planning, code generation) will "
        "genuinely report themselves as blocked rather than fabricating output.",
        icon="⚠️",
    )

# ---------------------------------------------------------------- Screen 1
if st.session_state.step == 1:
    st.header("Screen 1 — Repository Upload")
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Use the bundled sample app")
        st.write("A real Spring Boot merchant app with an existing Stripe integration.")
        if st.button("Use sample-apps/merchant-app", type="primary"):
            st.session_state.repo_path = str(SAMPLE_APP)
            goto(2)
            st.rerun()
    with col2:
        st.subheader("Upload a Java Spring Boot project (.zip)")
        uploaded = st.file_uploader("ZIP archive", type=["zip"])
        if uploaded and st.button("Extract and continue"):
            try:
                extracted = safe_extract_zip(uploaded)
                st.session_state.repo_path = str(extracted)
                goto(2)
                st.rerun()
            except (ValueError, zipfile.BadZipFile) as e:
                st.error(f"Could not accept this archive: {e}")

# ---------------------------------------------------------------- Screen 2
elif st.session_state.step == 2:
    st.header("Screen 2 — Operation Selection")
    st.write(f"Repository: `{st.session_state.repo_path}`")
    mode = st.radio("Operation mode", ["ADD_PSP", "MIGRATE_PSP"], format_func=lambda m: {
        "ADD_PSP": "ADD_PSP — add a new PSP alongside existing ones",
        "MIGRATE_PSP": "MIGRATE_PSP — migrate future payments to a new PSP",
    }[m])
    if st.button("Continue", type="primary"):
        st.session_state.operation_mode = mode
        goto(3)
        st.rerun()
    if st.button("← Back"):
        goto(1)
        st.rerun()

# ---------------------------------------------------------------- Screen 3
elif st.session_state.step == 3:
    st.header("Screen 3 — Provider Discovery")
    with st.spinner("Running the JavaParser-based repository analyzer..."):
        try:
            analysis = analyze_repository(st.session_state.repo_path)
            st.session_state.analysis = analysis.model_dump(by_alias=True)
        except RepositoryAnalysisError as e:
            st.error(f"Analysis failed: {e}")
            st.stop()

    providers = st.session_state.analysis["detectedProviders"]
    if providers:
        st.success(f"Detected {len(providers)} provider(s):")
        for p in providers:
            with st.expander(f"{p['name']} — confidence: {p['confidence']}"):
                for e in p["evidence"]:
                    st.code(e, language=None)
    else:
        st.info("No existing provider detected with confidence (greenfield integration).")

    if st.button("Continue", type="primary"):
        goto(4)
        st.rerun()
    if st.button("← Back"):
        goto(2)
        st.rerun()

# ---------------------------------------------------------------- Screen 4
elif st.session_state.step == 4:
    st.header("Screen 4 — Target Provider")
    target = st.text_input("Target provider id (e.g. razorpay, adyen, paypal, cashfree, stripe, or any other)")
    doc_url = st.text_input("Official documentation URL (optional — required if the provider isn't pre-registered)")
    if st.button("Continue", type="primary", disabled=not target):
        st.session_state.target_provider = target.strip().lower()
        st.session_state.target_provider_doc_url = doc_url.strip() or None
        goto(5)
        st.rerun()
    if st.button("← Back"):
        goto(3)
        st.rerun()

# ---------------------------------------------------------------- Screen 5
elif st.session_state.step == 5:
    st.header("Screen 5 — Repository Analysis")
    analysis = st.session_state.analysis
    arch = analysis["architecture"]

    c1, c2, c3 = st.columns(3)
    c1.metric("Payment classes", len(analysis["paymentClasses"]))
    c2.metric("Payment operations", len(analysis["paymentOperations"]))
    c3.metric("Provider abstraction exists", "Yes" if arch["providerAbstractionExists"] else "No")

    if arch["warnings"]:
        for w in arch["warnings"]:
            st.warning(w)

    st.subheader("Payment classes")
    st.dataframe(analysis["paymentClasses"], use_container_width=True)
    st.subheader("Payment operations")
    st.dataframe(analysis["paymentOperations"], use_container_width=True)

    if st.button("Continue to planning & execution", type="primary"):
        goto(6)
        st.rerun()
    if st.button("← Back"):
        goto(4)
        st.rerun()

# ---------------------------------------------------------------- Screen 6 + 7
elif st.session_state.step in (6, 7):
    st.header("Screen 6/7 — Integration Plan & Agent Execution")
    st.write(
        f"Mode: **{st.session_state.operation_mode}** · Target provider: **{st.session_state.target_provider}**"
    )

    if st.button("Run the agent pipeline", type="primary"):
        run_id = uuid.uuid4().hex[:12]
        initial_state = {
            "repository_path": st.session_state.repo_path,
            "operation_mode": st.session_state.operation_mode,
            "target_provider": st.session_state.target_provider,
            "target_provider_doc_url": st.session_state.target_provider_doc_url,
            "run_id": run_id,
        }
        graph = build_graph(llm)
        log_box = st.container()
        accumulated = dict(initial_state)
        with st.spinner("Running LangGraph pipeline..."):
            for event in graph.stream(initial_state, config={"recursion_limit": 50}):
                for node_name, update in event.items():
                    accumulated.update(update)
                    with log_box:
                        st.write(f"**{node_name}** completed")
                        if update.get("blocked"):
                            st.error(f"Blocked: {update.get('blocker_reason')}")
        st.session_state.final_state = accumulated
        save_run_report(
            run_id=run_id,
            operation_mode=st.session_state.operation_mode,
            target_provider=st.session_state.target_provider,
            existing_providers=accumulated.get("existing_providers", []),
            final_status=accumulated.get("final_status") or accumulated.get("blocker_reason"),
            report=accumulated.get("report"),
        )
        goto(8)
        st.rerun()

    if st.button("← Back"):
        goto(5)
        st.rerun()

# ---------------------------------------------------------------- Screen 8
elif st.session_state.step == 8:
    st.header("Screen 8 — Results")
    final_state = st.session_state.final_state or {}
    report = final_state.get("report")

    if final_state.get("blocked") and not report:
        st.error(f"Run blocked before a report could be produced: {final_state.get('blocker_reason')}")
    elif report:
        status = report["verification"]["final_status"] if report.get("verification") else final_state.get("final_status")
        {"VERIFIED": st.success, "UNRESOLVED_FAILURE": st.error}.get(status, st.warning)(f"Final status: {status}")

        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Files created")
            st.json(report["files_created"])
            st.subheader("Files modified")
            st.json(report["files_modified"])
        with col2:
            st.subheader("Unsupported / manual review")
            st.json(report["unsupported_functionality"])
            st.json(report["manual_review_items"])

        if report.get("verification"):
            st.subheader("Test results")
            st.json(report["verification"]["tests"] if report["verification"]["tests"] else {})
            if report["verification"]["repair_attempts"]:
                st.subheader("Repair attempts")
                st.json(report["verification"]["repair_attempts"])

        if final_state.get("changes_diff"):
            st.subheader("Code diff")
            st.code(final_state["changes_diff"], language="diff")

        st.subheader("Documentation citations")
        for url in report["documentation_citations"]:
            st.write(f"- {url}")

        workspace_path = final_state.get("workspace_path")
        if workspace_path and Path(workspace_path).is_dir():
            zip_base = Path(workspace_path).parent / "modified_project"
            archive_path = shutil.make_archive(str(zip_base), "zip", workspace_path)
            with open(archive_path, "rb") as f:
                st.download_button("Download modified project (.zip)", f, file_name="modified_project.zip")
        st.download_button("Download integration report (.json)", json.dumps(report, indent=2),
                            file_name="report.json")
    else:
        st.info("No report was produced yet. Run the pipeline from the previous screen.")

    if st.button("Start a new run"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()
