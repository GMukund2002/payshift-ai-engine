// PayShift AI dashboard -- plain JS, no build step. Talks to the FastAPI
// backend (backend/main.py), which wraps the real agent pipeline. Nothing
// here fabricates a result: every number/status shown comes straight from
// an API response.
//
// Every value that reaches innerHTML goes through esc(): provider ids, node
// names, blocker reasons and run history all originate from user input or
// LLM output, and run history is shared across every visitor of a deploy.

const state = {
  repoPath: null,
  analysis: null,
  lastReport: null,
};

function $(id) { return document.getElementById(id); }

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}

function safeHttpsUrl(value) {
  try {
    const u = new URL(value);
    return u.protocol === "https:" ? u.href : null;
  } catch (e) { return null; }
}

function statusPillClass(status) {
  if (status === "VERIFIED") return "pill-success";
  if (status === "UNRESOLVED_FAILURE" || (status || "").startsWith("CRASHED")) return "pill-danger";
  return "pill-warn";
}

// ---------------------------------------------------------------- access key

function getDemoKey() {
  try { return localStorage.getItem("payshift_demo_key") || null; }
  catch (e) { return null; } // private browsing / blocked storage
}
function setDemoKey(key) {
  try { key ? localStorage.setItem("payshift_demo_key", key) : localStorage.removeItem("payshift_demo_key"); }
  catch (e) { /* storage unavailable -- key just won't be remembered */ }
}

// fetch() for endpoints gated by DEMO_ACCESS_KEY: attaches the remembered key,
// and on a 401 asks for it once, remembers it, and retries.
async function protectedFetch(url, options = {}) {
  const withKey = (key) => {
    const headers = new Headers(options.headers || {});
    if (key) headers.set("X-Demo-Key", key);
    return fetch(url, { ...options, headers });
  };
  let res = await withKey(getDemoKey());
  if (res.status !== 401) return res;

  const entered = prompt("This deployment requires an access key (ask whoever deployed it). Enter it:");
  if (!entered) return res;
  res = await withKey(entered);
  if (res.status === 401) {
    setDemoKey(null);
    alert("That key was rejected. Double-check the DEMO_ACCESS_KEY set on the deployment.");
  } else {
    setDemoKey(entered);
  }
  return res;
}

async function errorText(res) {
  try {
    const body = await res.json();
    if (typeof body.detail === "string") return body.detail;
    return JSON.stringify(body.detail ?? body);
  } catch (e) { return `HTTP ${res.status}`; }
}

// ---------------------------------------------------------------- boot

async function waitForBackend() {
  const msg = $("boot-message");
  const started = Date.now();
  for (;;) {
    try {
      const res = await fetch("/api/health", { cache: "no-store" });
      if (res.ok) {
        const data = await res.json();
        $("data-backend-badge").textContent = `data: ${data.data_backend}`;
        $("llm-badge").textContent = data.llm_configured ? "llm: configured" : "llm: not configured";
        $("llm-badge").className = "pill " + (data.llm_configured ? "pill-success" : "pill-warn");
        $("boot-overlay").classList.add("hidden");
        $("app").classList.remove("hidden");
        return;
      }
    } catch (e) { /* server still asleep */ }
    const elapsed = Math.round((Date.now() - started) / 1000);
    msg.textContent = elapsed < 10 ? "Connecting…" : `Still waking up (${elapsed}s)… free tier can take up to a minute.`;
    await new Promise((r) => setTimeout(r, 2000));
  }
}

function setupNav() {
  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".nav-item").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      document.querySelectorAll(".view").forEach((v) => v.classList.add("hidden"));
      $("view-" + btn.dataset.view).classList.remove("hidden");
      if (btn.dataset.view === "history") loadHistory();
    });
  });
}

// ---------------------------------------------------------------- run flow

function setupRunFlow() {
  $("use-sample-btn").addEventListener("click", async () => {
    const res = await fetch("/api/sample-app");
    const data = await res.json();
    state.repoPath = data.repo_path;
    $("repo-status").textContent = `Using bundled sample app: ${data.repo_path}`;
    $("mode-card").style.display = "";
  });

  $("zip-input").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    $("repo-status").textContent = "Uploading…";
    const form = new FormData();
    form.append("file", file);
    const res = await protectedFetch("/api/upload", { method: "POST", body: form });
    if (!res.ok) {
      $("repo-status").textContent = "Upload failed: " + (await errorText(res));
      return;
    }
    const data = await res.json();
    state.repoPath = data.repo_path;
    $("repo-status").textContent = `Extracted to ${data.repo_path}`;
    $("mode-card").style.display = "";
  });

  $("analyze-btn").addEventListener("click", async () => {
    $("analyze-btn").disabled = true;
    $("analyze-btn").textContent = "Analyzing…";
    try {
      const res = await protectedFetch("/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo_path: state.repoPath }),
      });
      if (!res.ok) throw new Error(await errorText(res));
      const analysis = await res.json();
      state.analysis = analysis;
      renderAnalysis(analysis);
      $("analysis-card").style.display = "";
    } catch (err) {
      alert("Analysis failed: " + err.message);
    } finally {
      $("analyze-btn").disabled = false;
      $("analyze-btn").textContent = "Analyze repository";
    }
  });

  $("run-btn").addEventListener("click", runPipeline);
  $("download-report-btn").addEventListener("click", () => {
    if (!state.lastReport) return;
    const blob = new Blob([JSON.stringify(state.lastReport, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = "report.json"; a.click();
    URL.revokeObjectURL(url);
  });
}

function renderAnalysis(analysis) {
  const providers = analysis.detectedProviders || [];
  $("analysis-summary").innerHTML = `
    <div class="stat"><div class="num">${(analysis.paymentClasses || []).length}</div><div class="label">Payment classes</div></div>
    <div class="stat"><div class="num">${(analysis.paymentOperations || []).length}</div><div class="label">Payment operations</div></div>
    <div class="stat"><div class="num">${providers.length}</div><div class="label">Detected providers</div></div>
  `;
  $("analysis-providers").innerHTML = providers
    .map((p) => `<span class="pill pill-success">${esc(p.name)} · ${esc(p.confidence)}</span>`)
    .join(" ") || '<span class="subtle small">No existing provider detected (greenfield).</span>';
}

async function runPipeline() {
  const mode = $("mode-select").value;
  const target = $("target-provider").value.trim().toLowerCase();
  if (!/^[a-z0-9][a-z0-9_-]{0,39}$/.test(target)) {
    alert("Enter a target provider id: lowercase letters, digits, '-' or '_' (e.g. razorpay).");
    return;
  }
  const docUrl = $("doc-url").value.trim() || null;

  $("run-btn").disabled = true;
  $("progress-card").style.display = "";
  $("results-card").style.display = "none";
  $("node-list").innerHTML = "";

  try {
    const res = await protectedFetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ repo_path: state.repoPath, operation_mode: mode, target_provider: target, target_provider_doc_url: docUrl }),
    });
    if (!res.ok) {
      alert("Could not start the run: " + (await errorText(res)));
      $("progress-card").style.display = "none";
      return;
    }
    const { run_id } = await res.json();
    await pollRun(run_id);
  } finally {
    $("run-btn").disabled = false;
  }
}

// Polls instead of reading a long-lived stream -- see backend/main.py's
// module docstring for why: a free-tier container can crash mid-run, and
// polling degrades gracefully (a few failed checks, then recovery) instead
// of hanging on a connection nothing will ever write to again.
async function pollRun(runId) {
  let shown = 0;
  let consecutiveFailures = 0;
  const MAX_CONSECUTIVE_FAILURES = 6; // ~30s of failures, tolerating a crash+restart cycle

  for (;;) {
    await new Promise((r) => setTimeout(r, 3000));
    let data;
    try {
      const res = await fetch(`/api/runs/${encodeURIComponent(runId)}/status`, { cache: "no-store" });
      if (!res.ok) throw new Error(`status ${res.status}`);
      data = await res.json();
      consecutiveFailures = 0;
    } catch (e) {
      consecutiveFailures++;
      if (consecutiveFailures >= MAX_CONSECUTIVE_FAILURES) {
        alert("Lost contact with the server while this run was in progress (it may have crashed and is restarting). Check Run History in a minute -- the run may still complete and show up there.");
        return;
      }
      continue;
    }

    for (; shown < data.progress.length; shown++) {
      const n = data.progress[shown];
      const li = document.createElement("li");
      if (n.blocked) li.classList.add("blocked");
      li.innerHTML = `<span class="node-dot"></span><span>${esc(n.node)}</span>` +
        (n.blocked ? `<span class="subtle small">— blocked: ${esc(n.blocker_reason)}</span>` : "");
      $("node-list").appendChild(li);
    }

    if (data.status && data.status !== "RUNNING") {
      renderResults(data);
      return;
    }
  }
}

function blockerReasonFrom(data) {
  const blockedNode = (data.progress || []).find((n) => n.blocked);
  if (blockedNode && blockedNode.blocker_reason) return blockedNode.blocker_reason;
  const limitation = (data.report?.known_limitations || []).find((l) => l.startsWith("Run blocked:"));
  if (limitation) return limitation.replace(/^Run blocked:\s*/, "");
  return (data.status || "").startsWith("CRASHED") ? data.status : null;
}

function renderResults(data) {
  $("results-card").style.display = "";
  const report = data.report;
  state.lastReport = report;

  // data.status is the run's real terminal status as persisted by the backend
  // (VERIFIED / UNRESOLVED_FAILURE / BLOCKED / CRASHED: ...). A blocked run has
  // a report but no verification section, so it must not be derived from that.
  const finalStatus = data.status || report?.verification?.final_status || "UNKNOWN";
  const reason = finalStatus === "VERIFIED" ? null : blockerReasonFrom(data);
  $("result-status").innerHTML =
    `<span class="pill ${statusPillClass(finalStatus)}">${esc(finalStatus)}</span>` +
    (reason ? `<p class="subtle small">${esc(reason)}</p>` : "");

  if (!report) {
    ["files-created", "files-modified", "test-results", "unsupported", "repair-attempts"].forEach((id) => { $(id).textContent = ""; });
    $("doc-citations").innerHTML = "";
    return;
  }

  $("files-created").textContent = JSON.stringify(report.files_created || [], null, 2);
  $("files-modified").textContent = JSON.stringify(report.files_modified || [], null, 2);
  $("test-results").textContent = JSON.stringify(summarizeTests(report.verification?.tests), null, 2);
  $("unsupported").textContent = JSON.stringify(
    [...(report.unsupported_functionality || []), ...(report.manual_review_items || [])], null, 2);
  $("repair-attempts").textContent = JSON.stringify(
    (report.verification?.repair_attempts || []).map((a) => ({
      attempt: a.attempt_number, diagnosis: a.diagnosis, patch: a.patch_description,
      files_touched: a.files_touched, recompiled_ok: a.recompile_success, tests_ok: a.retest_success,
    })), null, 2);
  $("doc-citations").innerHTML = (report.documentation_citations || [])
    .map((u) => {
      const href = safeHttpsUrl(u);
      return href
        ? `<li><a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${esc(u)}</a></li>`
        : `<li>${esc(u)}</li>`;
    }).join("");
}

function summarizeTests(tests) {
  if (!tests) return {};
  return {
    success: tests.success, tests_run: tests.tests_run, failures: tests.failures,
    errors: tests.errors, skipped: tests.skipped,
    not_passing: (tests.cases || []).filter((c) => c.status !== "PASSED")
      .map((c) => ({ name: c.name, status: c.status, message: (c.message || "").slice(0, 300) })),
  };
}

// ---------------------------------------------------------------- history

async function loadHistory() {
  const [runsRes, healthRes] = await Promise.all([fetch("/api/runs?limit=30"), fetch("/api/health")]);
  const runsList = runsRes.ok ? await runsRes.json() : [];
  const health = healthRes.ok ? await healthRes.json() : {};
  $("history-backend-note").textContent = `Backed by: ${health.data_backend || "unknown"}`;

  $("history-body").innerHTML = runsList.map((r) => `
    <tr data-run-id="${esc(r.run_id)}">
      <td>${esc(r.run_id)}</td><td>${esc(r.operation_mode)}</td><td>${esc(r.target_provider)}</td>
      <td><span class="pill ${statusPillClass(r.final_status)}">${esc(r.final_status || "—")}</span></td>
      <td>${esc(new Date(r.created_at).toLocaleString())}</td>
    </tr>`).join("") || `<tr><td colspan="5" class="subtle small">No runs recorded yet.</td></tr>`;

  document.querySelectorAll("#history-body tr[data-run-id]").forEach((tr) => {
    tr.addEventListener("click", async () => {
      const res = await fetch(`/api/runs/${encodeURIComponent(tr.dataset.runId)}`);
      $("history-detail").textContent = res.ok ? JSON.stringify(await res.json(), null, 2) : "No stored report for this run.";
      $("history-detail-card").style.display = "";
    });
  });
}

setupNav();
setupRunFlow();
waitForBackend();
