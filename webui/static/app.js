/* j0b web UI logic */
"use strict";

const $ = (sel) => document.querySelector(sel);

let currentJobs = [];
let selectedJob = null;
let selectedJobId = null;

function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(t._timer);
  t._timer = setTimeout(() => (t.hidden = true), 2600);
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
  return data;
}

// ---------------------------------------------------------------- boot
async function loadConfig() {
  try {
    const d = await api("/api/config");
    const c = d.candidate || {};
    const s = d.search || {};
    $("#cand-name").value = c.name || "";
    $("#cand-email").value = c.email || "";
    $("#cand-headline").value = c.headline || "";
    $("#cand-linkedin").value = c.linkedin || "";
    $("#cand-summary").value = c.summary || "";
    $("#cand-skills").value = (c.skills || []).join(", ");
    $("#f-keywords").value = (s.keywords || []).join(", ");
    $("#f-locations").value = (s.locations || []).join(", ");
    $("#f-limit").value = s.limit || 40;
    const src = d.sources || {};
    $("#f-remotive").checked = src.remotive ? src.remotive.enabled !== false : true;
    $("#f-jobicy").checked = src.jobicy ? src.jobicy.enabled !== false : true;

    const ollama = d.ollama || {};
    const base = ollama.base_url || "http://localhost:11434";
    const pill = $("#ollama-pill");
    try {
      const r = await fetch(base + "/api/tags", { signal: AbortSignal.timeout(2500) });
      const tags = await r.json();
      const names = (tags.models || []).map((m) => m.name);
      const has = names.includes(ollama.model) || names.length > 0;
      pill.textContent = has
        ? "ollama ok (" + (ollama.model || names[0] || "?") + ")"
        : "ollama: model missing";
      pill.style.borderColor = has ? "#238636" : "#d29922";
    } catch (e) {
      pill.textContent = "ollama: offline (template mode)";
      pill.style.borderColor = "#f85149";
    }

    const r = await api("/api/resume");
    if (r.has_resume) {
      $("#resume-status").textContent = "✓ " + r.path.split(/[\\/]/).pop();
      $("#resume-info").hidden = false;
      $("#resume-skills").textContent = (r.skills || []).join(", ") || "none detected";
    }
  } catch (e) {
    toast("config load failed: " + e.message);
  }
}

// ---------------------------------------------------------------- profile
$("#btn-save-profile").addEventListener("click", async () => {
  const skills = $("#cand-skills").value.split(",").map((s) => s.trim()).filter(Boolean);
  try {
    await api("/api/config", {
      method: "POST",
      body: JSON.stringify({
        candidate: {
          name: $("#cand-name").value.trim(),
          email: $("#cand-email").value.trim(),
          headline: $("#cand-headline").value.trim(),
          linkedin: $("#cand-linkedin").value.trim(),
          summary: $("#cand-summary").value.trim(),
          skills,
        },
      }),
    });
    toast("profile saved ✓");
  } catch (e) {
    toast("save failed: " + e.message);
  }
});

$("#resume-file").addEventListener("change", async (ev) => {
  const f = ev.target.files[0];
  if (!f) return;
  const fd = new FormData();
  fd.append("file", f);
  try {
    const res = await fetch("/api/resume", { method: "POST", body: fd });
    const d = await res.json();
    if (!res.ok || !d.ok) throw new Error(d.error || "upload failed");
    $("#resume-status").textContent = "✓ " + (d.path || "").split(/[\\/]/).pop();
    $("#resume-info").hidden = false;
    $("#resume-skills").textContent = (d.skills || []).join(", ") || "none detected";
    if (d.email_found) $("#cand-email").value = d.email_found;
    toast(`resume parsed: ${d.text_len} chars, ${(d.skills || []).length} skills`);
  } catch (e) {
    toast("upload failed: " + e.message);
  }
});

// ---------------------------------------------------------------- search
function collectFilters() {
  const kw = $("#f-keywords").value.split(",").map((s) => s.trim()).filter(Boolean);
  const loc = $("#f-locations").value.split(",").map((s) => s.trim()).filter(Boolean);
  return {
    keywords: kw,
    locations: loc,
    limit: parseInt($("#f-limit").value, 10) || 40,
    sources: {
      remotive: $("#f-remotive").checked,
      jobicy: $("#f-jobicy").checked,
    },
    startup_only: $("#f-startup").checked,
    salary_min: parseInt($("#f-sal-min").value, 10) || null,
    salary_max: parseInt($("#f-sal-max").value, 10) || null,
  };
}

$("#btn-search").addEventListener("click", async () => {
  const btn = $("#btn-search");
  btn.disabled = true;
  $("#search-status").textContent = "searching job feeds...";
  try {
    const d = await api("/api/search", { method: "POST", body: JSON.stringify(collectFilters()) });
    currentJobs = d.jobs || [];
    const salMin = $("#f-sal-min").value, salMax = $("#f-sal-max").value;
    const salHint = (salMin || salMax)
      ? " (salary filter: jobs without a listed salary were excluded)"
      : "";
    $("#search-status").textContent =
      `${d.count} jobs matched your filters. Click "Score vs resume" to rank them.` + salHint;
    $("#btn-match").disabled = false;
    renderJobs();
    $("#results-card").hidden = false;
    toast(`${d.count} jobs found`);
  } catch (e) {
    $("#search-status").textContent = "search failed: " + e.message;
    toast("search failed");
  } finally {
    btn.disabled = false;
  }
});

$("#btn-match").addEventListener("click", async () => {
  const btn = $("#btn-match");
  btn.disabled = true;
  $("#search-status").textContent = "scoring jobs against your resume (keyword mode)...";
  try {
    const d = await api("/api/match", { method: "POST", body: JSON.stringify({ mode: "keywords" }) });
    $("#search-status").textContent = `scored ${d.count} jobs. Use AI mode in CLI for deeper scoring.`;
    // merge scores into current view
    const byId = {};
    (d.matches || []).forEach((m) => (byId[m.id] = m.match_score));
    currentJobs.forEach((j) => (j.match_score = byId[j.id]));
    renderJobs();
    toast(`${d.count} jobs scored`);
  } catch (e) {
    $("#search-status").textContent = "match failed: " + e.message;
  } finally {
    btn.disabled = false;
  }
});

$("#btn-reset").addEventListener("click", () => {
  currentJobs = [];
  $("#results-card").hidden = true;
  $("#search-status").textContent = "";
  $("#btn-match").disabled = true;
});

$("#f-startup-only-view").addEventListener("change", renderJobs);
$("#f-scored").addEventListener("change", renderJobs);

// ---------------------------------------------------------------- render
function scoreClass(s) {
  if (s == null) return "";
  if (s >= 55) return "high";
  if (s >= 40) return "mid";
  return "low";
}

function renderJobs() {
  const onlyStartup = $("#f-startup-only-view").checked;
  const onlyScored = $("#f-scored").checked;
  const list = $("#job-list");
  list.innerHTML = "";

  let jobs = currentJobs;
  if (onlyStartup) jobs = jobs.filter((j) => j.startup);
  if (onlyScored) jobs = jobs.filter((j) => j.match_score != null);
  $("#result-count").textContent = `(${jobs.length})`;

  if (!jobs.length) {
    list.innerHTML = '<p class="hint">No jobs match the current view filters.</p>';
    return;
  }

  jobs.forEach((j) => {
    const el = document.createElement("div");
    el.className = "job";
    const score = j.match_score != null ? j.match_score : "–";
    const startupBadge = j.startup
      ? '<span class="badge startup">startup</span>'
      : "";
    el.innerHTML = `
      <div class="score ${scoreClass(j.match_score)}">${score}</div>
      <div class="meta">
        <p class="title">${esc(j.title)} ${startupBadge}
          <span class="badge src">${esc(j.source)}</span></p>
        <div class="sub">${esc(j.company)} · ${esc(j.location)}</div>
      </div>
      <div class="salary">${j.salary_display ? esc(j.salary_display) : ""}</div>
      <div class="actions">
        <button class="btn" data-act="tailor" data-id="${j.id}">✍ Tailor</button>
        <button class="btn ghost" data-act="open" data-url="${escAttr(j.url)}">Open</button>
      </div>`;
    list.appendChild(el);
  });
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}
function escAttr(s) {
  return esc(s).replace(/"/g, "&quot;");
}

$("#job-list").addEventListener("click", async (ev) => {
  const btn = ev.target.closest("button[data-act]");
  if (!btn) return;
  const act = btn.dataset.act;
  const id = btn.dataset.id;
  const url = btn.dataset.url;

  if (act === "open" && url) {
    window.open(url, "_blank");
    return;
  }
  if (act === "tailor" && id) {
    await openTailor(id);
  }
});

// ---------------------------------------------------------------- tailor modal
async function openTailor(jobId) {
  selectedJob = null;
  $("#tailor-modal").hidden = false;
  $("#tailor-title").textContent = "Job selected";
  $("#tailor-cover").textContent = "(click Generate docs)";
  $("#tailor-summary").textContent = "";
  $("#tailor-file").textContent = "";
  selectedJobId = jobId;
}

$("#btn-generate").addEventListener("click", async () => {
  if (!selectedJobId) return;
  const useAi = !$("#tailor-template").checked;
  $("#tailor-title").textContent = useAi
    ? "Tailoring with Ollama... (~80s)"
    : "Tailoring (template)...";
  $("#tailor-cover").textContent = "(generating...)";
  try {
    const d = await api("/api/tailor", {
      method: "POST",
      body: JSON.stringify({ job_id: selectedJobId, use_ai: useAi }),
    });
    selectedJob = d.job;
    $("#tailor-title").textContent = `${d.job.title} @ ${d.job.company}`;
    $("#tailor-cover").textContent = d.doc.cover_letter || "(none)";
    $("#tailor-summary").textContent = d.doc.resume_summary || "(none)";
    $("#tailor-file").textContent = d.doc.file ? "saved: " + d.doc.file : "";
  } catch (e) {
    $("#tailor-title").textContent = "tailor failed: " + e.message;
  }
});

$("#btn-close-modal").addEventListener("click", () => {
  $("#tailor-modal").hidden = true;
});

$("#btn-open-job").addEventListener("click", () => {
  if (selectedJob && selectedJob.url) window.open(selectedJob.url, "_blank");
});

document.querySelectorAll("[data-log]").forEach((btn) => {
  btn.addEventListener("click", async () => {
    if (!selectedJob) return;
    try {
      await api("/api/log", {
        method: "POST",
        body: JSON.stringify({ job: selectedJob, status: btn.dataset.log }),
      });
      toast(`logged: ${btn.dataset.log}`);
      $("#tailor-modal").hidden = true;
      loadTracker();
    } catch (e) {
      toast("log failed: " + e.message);
    }
  });
});

// ---------------------------------------------------------------- tracker
async function loadTracker() {
  try {
    const d = await api("/api/status");
    if (!(d.rows || []).length) {
      $("#tracker-card").hidden = true;
      return;
    }
    $("#tracker-card").hidden = false;
    const list = $("#tracker-list");
    list.innerHTML = "";
    [...(d.rows || [])].reverse().slice(0, 50).forEach((r) => {
      const el = document.createElement("div");
      el.className = "tracker-row";
      el.innerHTML = `
        <span class="st ${esc(r.status)}">${esc(r.status)}</span>
        <span>${esc(r.title)}</span>
        <span class="hint">@ ${esc(r.company)} · ${esc(r.date)}</span>`;
      list.appendChild(el);
    });
  } catch (e) {
    /* silent */
  }
}

// ---------------------------------------------------------------- init
loadConfig();
loadTracker();
