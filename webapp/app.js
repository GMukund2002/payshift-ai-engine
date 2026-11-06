// PayShift AI dashboard -- plain JS, no build step. Talks to the FastAPI
// backend (backend/main.py), which wraps the real agent pipeline. Nothing
// here fabricates a result: every number/status shown comes straight from
// an API response.

const state = {
  repoPath: null,
  analysis: null,
  lastReport: null,
};

function $(id) { return document.getElementById(id); }

function getDemoKey() {
  try { return localStorage.getItem("payshift_demo_key") || null; }
  catch (e) { return null; } // private browsing / blocked storage -- fall through to the 401 prompt
}

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
    const res = await fetch("/api/upload", { method: "POST", body: form });
    if (!res.ok) {
      $("repo-status").textContent = "Upload failed: " + (await res.text());
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
      const res = await fetch("/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo_path: state.repoPath }),
      });
      if (!res.ok) throw new Error(await res.text());
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
    .map((p) => `<span class="pill pill-success">${p.name} · ${p.confidence}</span>`)
    .join(" ") || '<span class="subtle small">No existing provider detected (greenfield).</span>';
}

async function runPipeline() {
  const mode = $("mode-select").value;
  const target = $("target-provider").value.trim().toLowerCase();
  if (!target) { alert("Enter a target provider id."); return; }
  const docUrl = $("doc-url").value.trim() || null;

  $("run-btn").disabled = true;
  $("progress-card").style.display = "";
  $("results-card").style.display = "none";
  $("node-list").innerHTML = "";

  const headers = { "Content-Type": "application/json" };
  const demoKey = getDemoKey();
  if (demoKey) headers["X-Demo-Key"] = demoKey;
  const body = JSON.stringify({ repo_path: state.repoPath, operation_mode: mode, target_provider: target, target_provider_doc_url: docUrl });

  let res = await fetch("/api/run", { method: "POST", headers, body });

  if (res.status === 401) {
    // This deploy requires a demo access key (set via DEMO_ACCESS_KEY) that
    // we either don't have yet or got wrong -- ask once, remember it for
    // next time, and retry rather than failing silently.
    const entered = prompt("This deployment requires a demo access key to run the pipeline (ask whoever deployed it). Enter it:");
    if (!entered) { $("run-btn").disabled = false; $("progress-card").style.display = "none"; return; }
    localStorage.setItem("payshift_demo_key", entered);
    headers["X-Demo-Key"] = entered;
    res = await fetch("/api/run", { method: "POST", headers, body });
    if (res.status === 401) {
      alert("That key was rejected too. Double-check the DEMO_ACCESS_KEY value set on the deployment.");
      localStorage.removeItem("payshift_demo_key");
      $("run-btn").disabled = false;
      $("progress-card").style.display = "none";
      return;
    }
  }

  if (!res.ok) {
    alert("Could not start the run: " + (await res.text()));
    $("run-btn").disabled = false;
    $("progress-card").style.display = "none";
    return;
  }

  const { run_id } = await res.json();
  await pollRun(run_id);
  $("run-btn").disabled = false;
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
      const res = await fetch(`/api/runs/${runId}/status`, { cache: "no-store" });
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
      li.innerHTML = `<span class="node-dot"></span><span>${n.node}</span>` +
        (n.blocked ? `<span class="subtle small">— blocked: ${n.blocker_reason}</span>` : "");
      $("node-list").appendChild(li);
    }

    if (data.status && data.status !== "RUNNING") {
      const crashed = typeof data.status === "string" && data.status.startsWith("CRASHED");
      renderResults({ report: data.report, blocker_reason: crashed ? data.status : null });
      return;
    }
  }
}

function renderResults(payload) {
  $("results-card").style.display = "";
  state.lastReport = payload.report;

  const statusEl = $("result-status");
  if (!payload.report) {
    statusEl.innerHTML = `<span class="pill pill-danger">Blocked before a report could be produced</span><p class="subtle small">${payload.blocker_reason || ""}</p>`;
    $("files-created").textContent = "";
    $("files-modified").textContent = "";
    $("test-results").textContent = "";
    $("unsupported").textContent = "";
    $("doc-citations").innerHTML = "";
    return;
  }
  const report = payload.report;
  const finalStatus = report.verification?.final_status || "UNKNOWN";
  const pillClass = finalStatus === "VERIFIED" ? "pill-success" : finalStatus === "UNRESOLVED_FAILURE" ? "pill-danger" : "pill-warn";
  statusEl.innerHTML = `<span class="pill ${pillClass}">${finalStatus}</span>`;

  $("files-created").textContent = JSON.stringify(report.files_created || [], null, 2);
  $("files-modified").textContent = JSON.stringify(report.files_modified || [], null, 2);
  $("test-results").textContent = JSON.stringify(report.verification?.tests || {}, null, 2);
  $("unsupported").textContent = JSON.stringify(report.unsupported_functionality || [], null, 2);
  $("doc-citations").innerHTML = (report.documentation_citations || [])
    .map((u) => `<li><a href="${u}" target="_blank" rel="noopener">${u}</a></li>`).join("");
}

async function loadHistory() {
  const res = await fetch("/api/runs?limit=30");
  const runsList = await res.json();
  const healthRes = await fetch("/api/health");
  const health = await healthRes.json();
  $("history-backend-note").textContent = `Backed by: ${health.data_backend}`;

  $("history-body").innerHTML = runsList.map((r) => {
    const cls = r.final_status === "VERIFIED" ? "pill-success" : r.final_status === "UNRESOLVED_FAILURE" ? "pill-danger" : "pill-warn";
    return `<tr data-run-id="${r.run_id}">
      <td>${r.run_id}</td><td>${r.operation_mode}</td><td>${r.target_provider}</td>
      <td><span class="pill ${cls}">${r.final_status || "—"}</span></td>
      <td>${new Date(r.created_at).toLocaleString()}</td>
    </tr>`;
  }).join("") || `<tr><td colspan="5" class="subtle small">No runs recorded yet.</td></tr>`;

  document.querySelectorAll("#history-body tr[data-run-id]").forEach((tr) => {
    tr.addEventListener("click", async () => {
      const res = await fetch(`/api/runs/${tr.dataset.runId}`);
      if (!res.ok) { $("history-detail").textContent = "No stored report for this run."; }
      else { $("history-detail").textContent = JSON.stringify(await res.json(), null, 2); }
      $("history-detail-card").style.display = "";
    });
  });
}

setupNav();
setupRunFlow();
waitForBackend();
