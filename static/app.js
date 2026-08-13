/* j0b unified web UI logic */
"use strict";

const $ = (sel) => document.querySelector(sel);

let currentJobs = [];
let selectedJob = null;
let selectedJobIdVar = null;
let currentEmail = null; // { jobId, company } for the cold-email panel

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
    $("#cand-roles").value = (c.roles || []).join(", ");
    $("#cand-years").value = c.years_of_exp || "";
    $("#cand-sal-min").value = c.desired_salary_min || "";
    $("#cand-sal-max").value = c.desired_salary_max || "";
    $("#cand-locations").value = (c.preferred_locations || []).join(", ");
    $("#cand-languages").value = (c.languages || []).join("\n");
    $("#cand-dealbreakers").value = (c.deal_breakers || []).join(", ");
    $("#cand-education").value = c.education || "";
    $("#cand-star").value = (c.star_examples || []).join("\n");
    $("#f-keywords").value = (s.keywords || []).join(", ");
    $("#f-locations").value = (s.locations || []).join(", ");
    $("#f-limit").value = s.limit || 40;
    $("#f-exp-min").value = s.exp_min || "";
    $("#f-exp-max").value = s.exp_max || "";
    const src = d.sources || {};
    $("#f-remotive").checked = src.remotive ? src.remotive.enabled !== false : true;
    $("#f-jobicy").checked = src.jobicy ? src.jobicy.enabled !== false : true;
    $("#f-freehire").checked = src.freehire ? src.freehire.enabled !== false : true;

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
  const num = (sel) => {
    const v = $(sel).value.trim();
    return v === "" ? null : parseInt(v, 10) || null;
  };
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
          roles: $("#cand-roles").value.split(",").map((s) => s.trim()).filter(Boolean),
          years_of_exp: num("#cand-years"),
          desired_salary_min: num("#cand-sal-min"),
          desired_salary_max: num("#cand-sal-max"),
          preferred_locations: $("#cand-locations").value.split(",").map((s) => s.trim()).filter(Boolean),
          languages: $("#cand-languages").value.split(/[\n,]/).map((s) => s.trim()).filter(Boolean),
          deal_breakers: $("#cand-dealbreakers").value.split(",").map((s) => s.trim()).filter(Boolean),
          education: $("#cand-education").value.trim(),
          star_examples: $("#cand-star").value.split(/\n/).map((s) => s.trim()).filter(Boolean),
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
  const expMin = $("#f-exp-min").value.trim();
  const expMax = $("#f-exp-max").value.trim();
  return {
    keywords: kw,
    locations: loc,
    limit: parseInt($("#f-limit").value, 10) || 40,
    exp_min: expMin === "" ? null : parseInt(expMin, 10) || null,
    exp_max: expMax === "" ? null : parseInt(expMax, 10) || null,
    sources: {
      remotive: $("#f-remotive").checked,
      jobicy: $("#f-jobicy").checked,
      freehire: $("#f-freehire").checked,
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
    refreshJobOptions();
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
  $("#email-card").hidden = true;
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
    const verdict = j.verdict ? `<span class="badge verdict">${esc(j.verdict)}</span>` : "";
    const exp = j.exp_display ? `<span class="badge exp">${esc(j.exp_display)}</span>` : "";
    el.innerHTML = `
      <div class="score ${scoreClass(j.match_score)}">${score}</div>
      <div class="meta">
        <p class="title">${esc(j.title)} ${startupBadge} ${verdict}
          <span class="badge src">${esc(j.source)}</span></p>
        <div class="sub">${esc(j.company)} · ${esc(j.location)} ${exp}</div>
      </div>
      <div class="salary">${j.salary_display ? esc(j.salary_display) : ""}</div>
      <div class="actions">
        <button class="btn" data-act="tailor" data-id="${j.id}">✍ Tailor</button>
        <button class="btn" data-act="email" data-id="${j.id}">✉ Cold email</button>
        <button class="btn" data-act="apply" data-id="${j.id}">💻 Apply</button>
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
  if (act === "email" && id) {
    await openEmail(id);
  }
  if (act === "apply" && id) {
    await prefillApply(id);
  }
});

// ---------------------------------------------------------------- cold email -> Gmail
async function openEmail(jobId) {
  $("#email-card").hidden = false;
  $("#email-draft-status").textContent = "";
  $("#email-job-line").textContent = "Generating cold application email…";
  try {
    // template body (instant) — the AI agent "Cold outreach" button writes
    // a personalized variant into this same panel when you want one
    const d = await api("/api/email", {
      method: "POST",
      body: JSON.stringify({ job_id: jobId, resolve: true, use_ai: false }),
    });
    currentEmail = { jobId, company: d.company || "" };
    $("#email-to").value = d.to || "";
    $("#email-subject").value = d.subject || "";
    $("#email-body").value = d.body || "";
    const src = d.recipient_source === "site"
      ? "recipient found on the company site"
      : d.recipient_source === "guess"
        ? "recipient guessed (hello@domain) — verify it"
        : "no recipient found — enter the company email manually";
    $("#email-job-line").textContent = `${d.company || ""}: ${src}. Fast template body — edit freely, or use AI agent → "Cold outreach" for a personalized draft.`;
    $("#email-card").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) {
    $("#email-job-line").textContent = "cold email failed: " + e.message;
    toast("cold email failed");
  }
}

$("#btn-email-draft-browser").addEventListener("click", async () => {
  const to = $("#email-to").value.trim();
  const subject = $("#email-subject").value.trim();
  const body = $("#email-body").value.trim();
  const company = currentEmail ? currentEmail.company : "";
  if (!(to && subject && body)) { toast("fill To / Subject / Body first"); return; }
  const status = $("#email-draft-status");
  status.textContent = "opening Gmail in your browser — if it asks you to sign in, use your Gmail account (once); creating the draft takes ~10s…";
  try {
    const d = await api("/api/email/draft", {
      method: "POST",
      body: JSON.stringify({
        job_id: currentEmail ? currentEmail.jobId : "",
        to, subject, body, company,
      }),
    });
    status.textContent = d.ok
      ? "✓ Gmail draft created — review it in Gmail's Drafts, then send it yourself"
      : "draft failed: " + (d.error || "sign in to Gmail in the window that opened, then retry");
    if (d.ok) {
      toast("draft saved to Gmail");
      loadTracker();
    }
  } catch (e) {
    status.textContent = "draft failed: " + e.message;
  }
});

$("#btn-email-draft-composio").addEventListener("click", async () => {
  const to = $("#email-to").value.trim();
  const subject = $("#email-subject").value.trim();
  const body = $("#email-body").value.trim();
  if (!(to && subject && body)) { toast("fill To / Subject / Body first"); return; }
  const status = $("#email-draft-status");
  status.textContent = "creating draft via Composio…";
  try {
    const d = await api("/api/agent/draft", {
      method: "POST",
      body: JSON.stringify({ to, subject, body }),
    });
    status.textContent = d.ok
      ? "✓ Gmail draft created — review it in Gmail's Drafts"
      : "composio draft failed: " + (d.error || "connect Gmail under the AI agent panel");
  } catch (e) {
    status.textContent = "draft failed: " + e.message;
  }
});

$("#btn-gmail-login").addEventListener("click", async () => {
  try {
    const d = await api("/api/email/gmail-login", { method: "POST" });
    $("#email-draft-status").textContent = d.msg;
    toast("Gmail login window opened");
  } catch (e) {
    $("#email-draft-status").textContent = "login failed: " + e.message;
  }
});

// ---------------------------------------------------------------- semi-auto apply
async function prefillApply(jobId) {
  try {
    const d = await api("/api/apply/prefill", {
      method: "POST",
      body: JSON.stringify({ job_id: jobId }),
    });
    toast(d.msg || "browser opened");
    $("#search-status").textContent =
      (d.msg || "Browser opened.") + " Log the outcome with the Tailor button → status buttons.";
  } catch (e) {
    toast("apply failed: " + e.message);
  }
}

// ---------------------------------------------------------------- tailor modal
async function openTailor(jobId) {
  selectedJob = null;
  $("#tailor-modal").hidden = false;
  $("#tailor-title").textContent = "Job selected";
  $("#tailor-cover").textContent = "(click Generate docs)";
  $("#tailor-summary").textContent = "";
  $("#tailor-file").textContent = "";
  selectedJobIdVar = jobId;
}

$("#btn-generate").addEventListener("click", async () => {
  if (!selectedJobIdVar) return;
  const useAi = !$("#tailor-template").checked;
  $("#tailor-title").textContent = useAi
    ? "Tailoring with Ollama... (~80s)"
    : "Tailoring (template)...";
  $("#tailor-cover").textContent = "(generating...)";
  try {
    const d = await api("/api/tailor", {
      method: "POST",
      body: JSON.stringify({ job_id: selectedJobIdVar, use_ai: useAi }),
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

$("#btn-cv-pdf").addEventListener("click", async () => {
  if (!selectedJobIdVar) return;
  const btn = $("#btn-cv-pdf");
  const status = $("#cv-status");
  btn.disabled = true;
  status.textContent = "generating LaTeX + compiling (needs LaTeX installed)...";
  try {
    const useAi = !$("#tailor-template").checked;
    const d = await api("/api/cv", {
      method: "POST",
      body: JSON.stringify({ job_id: selectedJobIdVar, use_ai: useAi }),
    });
    const links = [];
    if (d.cv_pdf) links.push(`<a href="/cv/${esc(rel(d.cv_pdf))}" target="_blank">cv.pdf (${esc(d.cv_pages)} pages)</a>`);
    if (d.cover_pdf) links.push(`<a href="/cv/${esc(rel(d.cover_pdf))}" target="_blank">cover.pdf (${esc(d.cover_pages)} pages)</a>`);
    const warnings = (d.warnings || []).map((w) => esc(w)).join(" · ");
    status.innerHTML = links.length
      ? "PDFs: " + links.join(" · ") + (warnings ? " · ⚠ " + warnings : "")
      : "no LaTeX engine found — sources written: " + esc(rel(d.cv_tex)) + " · install TeX Live/MiKTeX and re-run";
  } catch (e) {
    status.textContent = "cv failed: " + e.message;
  } finally {
    btn.disabled = false;
  }
});

function rel(p) {
  const i = p.indexOf("data/cv/");
  return i >= 0 ? p.slice(i + "data/cv/".length) : p.split(/[\\/]/).pop();
}

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

// ---------------------------------------------------------------- report
$("#btn-report").addEventListener("click", async () => {
  const btn = $("#btn-report");
  btn.disabled = true;
  try {
    const d = await api("/api/report", { method: "POST" });
    window.open("/tracker-report.html", "_blank");
    const st = d.stats || {};
    toast(`report: ${st.total} applications · ${st.interview_rate}% past resume screen`);
  } catch (e) {
    toast("report failed: " + e.message);
  } finally {
    btn.disabled = false;
  }
});

// ---------------------------------------------------------------- init
loadConfig();
loadTracker();

// ---------------------------------------------------------------- AI agent
let agentBusy = false;

function agentPill(s) {
  const pill = $("#agent-pill");
  const ok = s.opencode && s.opencode.ok;
  const gmail = s.gmail_draft_ready;
  pill.textContent = ok ? (gmail ? "agent: ready + gmail" : "agent: ready")
                        : "agent: fallback / offline";
  pill.style.borderColor = ok ? "#238636" : (s.fallback && s.fallback.ok ? "#d29922" : "#f85149");
  $("#agent-status-line").textContent =
    `opencode: ${(s.opencode || {}).msg || "?"} · ` +
    `composio: ${(s.composio || {}).msg || "?"} · ` +
    `fallback: ${(s.fallback || {}).msg || "?"}`;
}

async function loadAgentStatus() {
  try {
    const d = await api("/api/agent/status");
    agentPill(d.status || {});
  } catch (e) {
    $("#agent-status-line").textContent = "agent status failed: " + e.message;
  }
}

function agentMsg(role, text) {
  const log = $("#agent-log");
  const el = document.createElement("div");
  el.className = "agent-msg " + role;
  el.textContent = text;
  log.appendChild(el);
  log.scrollTop = log.scrollHeight;
  return el;
}

function selectedJobId() {
  return $("#agent-job").value;
}

function refreshJobOptions() {
  const sel = $("#agent-job");
  const prev = sel.value;
  sel.innerHTML = '<option value="">(no job context)</option>';
  currentJobs.forEach((j) => {
    const opt = document.createElement("option");
    opt.value = j.id;
    opt.textContent = `${j.company} — ${j.title}`;
    sel.appendChild(opt);
  });
  if (prev) sel.value = prev;
}

async function agentSend(text) {
  if (agentBusy) return;
  if (!text) { toast("enter a message first"); return; }
  agentBusy = true;
  const btn = $("#btn-agent-send");
  btn.disabled = true;
  agentMsg("user", text);
  const status = agentMsg("bot", "(thinking…)");
  try {
    const d = await api("/api/agent/chat", {
      method: "POST",
      body: JSON.stringify({ message: text, job_id: selectedJobId() }),
    });
    status.textContent = d.reply || "(empty reply)";
    status.className = "agent-msg bot";
    $("#agent-input").value = "";
  } catch (e) {
    status.textContent = "agent error: " + e.message;
  } finally {
    agentBusy = false;
    btn.disabled = false;
  }
}

async function agentCompose(kind) {
  if (agentBusy) return;
  agentBusy = true;
  const status = agentMsg("bot", "(composing…)");
  try {
    const d = await api("/api/agent/compose", {
      method: "POST",
      body: JSON.stringify({ kind, job_id: selectedJobId() }),
    });
    const text = d.reply || "(empty)";
    status.textContent = text;
    status.className = "agent-msg bot";
    if (text) {
      $("#email-card").hidden = false;
      $("#email-body").value = text;
      if (!$("#email-subject").value) {
        $("#email-subject").value = kind === "cold"
          ? "Exploring opportunities at your company"
          : "Application follow-up";
      }
    }
  } catch (e) {
    status.textContent = "compose error: " + e.message;
  } finally {
    agentBusy = false;
  }
}

$("#btn-agent-send").addEventListener("click", () => agentSend($("#agent-input").value.trim()));
$("#agent-input").addEventListener("keydown", (ev) => {
  if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) {
    ev.preventDefault();
    agentSend($("#agent-input").value.trim());
  }
});
document.querySelectorAll("[data-compose]").forEach((b) =>
  b.addEventListener("click", () => agentCompose(b.dataset.compose)));

async function agentInterview(mode) {
  if (agentBusy) return;
  agentBusy = true;
  const status = agentMsg("bot", mode === "mock" ? "(starting mock interview…)" : "(building prep pack…)");
  try {
    const d = await api("/api/agent/interview", {
      method: "POST",
      body: JSON.stringify({ mode, job_id: selectedJobId() }),
    });
    const text = d.reply || "(empty)";
    status.textContent = text;
    status.className = "agent-msg bot";
    if (mode === "mock") {
      toast("Mock started — answer in the chat box · type \"end mock\" to stop");
      $("#agent-input").value = "";
      $("#agent-input").focus();
    }
  } catch (e) {
    status.textContent = "interview error: " + e.message;
  } finally {
    agentBusy = false;
  }
}

$("#btn-interview-prep").addEventListener("click", () => agentInterview("prep"));
$("#btn-interview-mock").addEventListener("click", () => agentInterview("mock"));

$("#btn-agent-refresh").addEventListener("click", loadAgentStatus);

$("#btn-agent-connect").addEventListener("click", async () => {
  try {
    const d = await api("/api/agent/connect", { method: "POST", body: JSON.stringify({ app: "gmail" }) });
    $("#agent-status-line").textContent = d.instructions;
    toast("Gmail connect instructions shown");
  } catch (e) {
    toast("connect failed: " + e.message);
  }
});

loadAgentStatus();
