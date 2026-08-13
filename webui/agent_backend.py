"""AI agent backend for the j0b web UI.

Stack
-----
* **opencode** drives the agent ("the brain"). We talk to an opencode
  server over its HTTP API from Python (the JS SDK is frontend-only; the
  server itself is language agnostic). If no server is running we try to
  start ``opencode serve`` on the same box.
* **Composio** supplies the authenticated tools the agent can use
  (e.g. Gmail). Wired via the Python ``composio`` package. When Composio
  is not configured the agent still works in a read-only/template mode.
* **Ollama** is the local fallback engine when opencode is unreachable.

Safety model
------------
The only outbound action this backend can perform is *creating a Gmail
draft* (Composio's ``GMAIL_CREATE_EMAIL_DRAFT`` action). It never sends
email and never submits applications -- matching the rest of j0b.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import requests

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

DEFAULT_OPENCODE_URL = os.environ.get("OPENCODE_BASE_URL", "http://127.0.0.1:4096")
DEFAULT_COMPOSIO_KEY = os.environ.get("COMPOSIO_API_KEY", "")

SYSTEM_PROMPT = """\
You are the job-hunting agent inside j0b (a local, private job application toolkit).

You help the candidate:
- summarize / analyze a job posting
- score fit against the candidate's resume and skills
- write tailored cover letters and resume summaries
- write polite, professional follow-up or cold outreach emails

You have access to authenticated tools (via Composio) such as Gmail. The ONLY
action you may take is CREATING A GMAIL DRAFT. You must never send email and
never submit applications. If the user asks you to send something, decline and
offer to create a draft instead.

Keep replies concise and usable. Output plain text or light markdown.
When you create a Gmail draft, report the draft details so the user can review
it in Gmail and hit send themselves.
"""


def _pick_text(data: Any) -> str:
    """Extract plain-text parts from an opencode prompt response (defensive)."""
    # accept both the bare response and a {data: ...} wrapper
    if isinstance(data, dict) and "data" in data:
        data = data["data"]
    if isinstance(data, dict):
        parts = data.get("parts") or data.get("messages") or []
        text, reasoning = [], []
        for p in parts:
            if isinstance(p, dict) and p.get("text"):
                if p.get("type") in (None, "text"):
                    text.append(p["text"])
                elif p.get("type") == "reasoning":
                    reasoning.append(p["text"])
        if text:
            return "\n".join(text)
        if reasoning:
            return "\n".join(reasoning)
        info = data.get("info") or data.get("message") or {}
        if isinstance(info, dict) and info.get("text"):
            return info["text"]
        if info.get("content"):
            return str(info["content"])
    if isinstance(data, str):
        return data
    return ""


def _format_exc(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


# --------------------------------------------------------------------------
# opencode server client
# --------------------------------------------------------------------------
class OpenCodeClient:
    """Thin HTTP client for an opencode server.

    Docs: https://opencode.ai/docs/sdk  (HTTP endpoints mirror the JS SDK)
    """

    def __init__(self, base_url: str = DEFAULT_OPENCODE_URL,
                 binary: str = "opencode", timeout: int = 180,
                 spawn: bool = True) -> None:
        self.base_url = base_url.rstrip("/")
        self.binary = binary
        self.timeout = timeout
        self.spawn = spawn
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    # -- lifecycle ---------------------------------------------------------
    def available(self) -> tuple[bool, str]:
        """Check server health; optionally start ``opencode serve``."""
        try:
            r = requests.get(f"{self.base_url}/global/health", timeout=3)
            if r.ok:
                payload = (r.json() or {})
                if payload.get("healthy"):
                    return True, f"opencode server ok (v{payload.get('version', '?')})"
                return True, "opencode server ok"
        except Exception as exc:  # noqa: BLE001
            pass
        if not self.spawn:
            return False, "opencode server not reachable at " + self.base_url
        with self._lock:
            if self._proc and self._proc.poll() is None:
                return True, "opencode server ok (spawned)"
            try:
                exe = shutil.which(self.binary) or self.binary
                args = [exe, "serve", "--port", str(self._port())]
                # npm shims on Windows are .cmd/.ps1 wrappers -> need a shell
                shell = os.name == "nt" and exe.lower().endswith((".cmd", ".bat"))
                self._proc = subprocess.Popen(
                    args,
                    shell=shell,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                for _ in range(30):
                    try:
                        r = requests.get(f"{self.base_url}/global/health", timeout=2)
                        if r.ok and (r.json() or {}).get("healthy"):
                            return True, "opencode server ok (spawned)"
                    except Exception:  # noqa: BLE001
                        time.sleep(0.5)
                return False, "opencode server failed to start"
            except Exception as exc:  # noqa: BLE001
                return False, f"could not start opencode serve: {_format_exc(exc)}"

    def _port(self) -> int:
        try:
            return int(self.base_url.rsplit(":", 1)[1])
        except Exception:  # noqa: BLE001
            return 4096

    # -- HTTP --------------------------------------------------------------
    def _req(self, method: str, path: str, **kw) -> Any:
        kw.setdefault("timeout", self.timeout)
        kw.setdefault("headers", {"Content-Type": "application/json"})
        r = requests.request(method, self.base_url + path, **kw)
        if not r.ok:
            raise RuntimeError(f"opencode {method} {path} -> HTTP {r.status_code}: {r.text[:200]}")
        try:
            return r.json()
        except ValueError:
            return r.text

    def create_session(self, title: str = "j0b agent",
                       tools: list | None = None) -> str:
        body: dict[str, Any] = {"title": title}
        if tools is not None:
            body["tools"] = tools   # [] = the agent gets NO tools at all
        data = self._req("POST", "/session", json=body)
        if isinstance(data, dict):
            return str(data.get("id") or data.get("data", {}).get("id", ""))
        return str(data)

    def prompt(self, session_id: str, text: str, system: str | None = None,
               no_reply: bool = False) -> str:
        body: dict[str, Any] = {"parts": [{"type": "text", "text": text}]}
        if system:
            body["system"] = system
        if no_reply:
            body["noReply"] = True
        data = self._req("POST", f"/session/{session_id}/message", json=body)
        return _pick_text(data)

    def chat(self, text: str, system: str = SYSTEM_PROMPT) -> str:
        ok, msg = self.available()
        if not ok:
            raise RuntimeError(msg)
        sid = self.create_session()
        return self.prompt(sid, text, system=system)


# --------------------------------------------------------------------------
# ollama fallback (no-tool local engine)
# --------------------------------------------------------------------------
class OllamaFallback:
    """Local chat fallback when opencode is unreachable. No external tools."""

    def __init__(self, base_url: str = "http://localhost:11434",
                 model: str = "deepseek-r1:8b", timeout: int = 180) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def available(self) -> tuple[bool, str]:
        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=3)
            if r.ok:
                return True, f"ollama fallback ok ({self.model})"
        except Exception:  # noqa: BLE001
            pass
        return False, "ollama not reachable at " + self.base_url

    def chat(self, text: str, system: str = SYSTEM_PROMPT) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": text},
            ],
            "stream": False,
        }
        r = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=self.timeout)
        if not r.ok:
            raise RuntimeError(f"ollama /api/chat -> HTTP {r.status_code}")
        data = r.json()
        return data.get("message", {}).get("content", "").strip()


# --------------------------------------------------------------------------
# composio bridge (authenticated tools)
# --------------------------------------------------------------------------
try:  # optional dependency
    from composio import Action, ComposioToolSet  # noqa: F401  (old API)
    _HAS_COMPOSIO = True
    _COMPOSIO_IMPORT_ERR = ""
except Exception as exc:  # noqa: BLE001
    _HAS_COMPOSIO = False
    _COMPOSIO_IMPORT_ERR = _format_exc(exc)

GMAIL_DRAFT_ACTION = "GMAIL_CREATE_EMAIL_DRAFT"
CONNECT_URL = "https://dashboard.composio.dev"  # OAuth connections happen here


class ComposioBridge:
    """Thin, defensive wrapper around the Composio Python SDK.

    Only exposes *safe* actions (Gmail draft). The SDK is optional; every
    method degrades to a readable error when it is not installed/configured.
    """

    def __init__(self, api_key: str = "", apps: list[str] | None = None) -> None:
        self.api_key = api_key or DEFAULT_COMPOSIO_KEY
        self.apps = apps or ["gmail"]
        self._toolset: Any = None

    # -- state -------------------------------------------------------------
    def available(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "COMPOSIO_API_KEY not set"
        if not _HAS_COMPOSIO:
            return False, f"composio package missing: {_COMPOSIO_IMPORT_ERR}"
        try:
            self._toolset = ComposioToolSet(api_key=self.api_key)
            return True, f"composio ok (apps: {', '.join(self.apps)})"
        except Exception as exc:  # noqa: BLE001
            return False, f"composio init failed: {_format_exc(exc)}"

    def connected_accounts(self) -> list[dict]:
        ok, _ = self.available()
        if not ok:
            return []
        try:
            accounts = self._toolset.get_connected_accounts()
            out = []
            for a in accounts or []:
                out.append({"id": getattr(a, "id", str(a)),
                            "app": getattr(a, "app_unique_id",
                                           getattr(a, "app", ""))})
            return out
        except Exception as exc:  # noqa: BLE001
            return [{"error": _format_exc(exc)}]

    # -- safe action ---------------------------------------------------------
    def create_gmail_draft(self, to: str | list[str], subject: str,
                           body: str) -> dict:
        ok, msg = self.available()
        if not ok:
            return {"ok": False, "error": msg}
        to_list = [to] if isinstance(to, str) else list(to)
        params: dict[str, Any] = {"to": to_list, "subject": subject, "body": body}
        try:
            result = self._toolset.execute_action(
                Action(GMAIL_DRAFT_ACTION), params=params,
            )
            result = result.data if isinstance(result, dict) and "data" in result else result
            return {"ok": True, "action": GMAIL_DRAFT_ACTION,
                    "draft": result, "to": to_list, "subject": subject}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": _format_exc(exc),
                    "hint": f"create the Gmail connection at {CONNECT_URL} then retry"}

    def connect_instructions(self, app: str = "gmail") -> str:
        return (f"Connect {app} at {CONNECT_URL}/apps/{app} using your "
                f"Composio account, then return here and check status.")


# --------------------------------------------------------------------------
# orchestrator
# --------------------------------------------------------------------------
class AgentBackend:
    """Coordinates opencode (brain) + composio (tools) + ollama (fallback)."""

    def __init__(self, opencode: OpenCodeClient | None = None,
                 composio: ComposioBridge | None = None,
                 fallback: OllamaFallback | None = None,
                 system_prompt: str = SYSTEM_PROMPT) -> None:
        self.opencode = opencode or OpenCodeClient()
        self.composio = composio or ComposioBridge()
        self.fallback = fallback or OllamaFallback()
        self.system_prompt = system_prompt
        # in-progress mock interview (set by interview_prep(mode="mock"))
        self._mock: dict | None = None
        self._mock_lock = threading.Lock()

    # -- public -------------------------------------------------------------
    def status(self) -> dict:
        oc_ok, oc_msg = self.opencode.available()
        co_ok, co_msg = self.composio.available()
        fl_ok, fl_msg = self.fallback.available()
        return {
            "opencode": {"ok": oc_ok, "msg": oc_msg},
            "composio": {"ok": co_ok, "msg": co_msg,
                         "accounts": self.composio.connected_accounts()
                         if co_ok else []},
            "fallback": {"ok": fl_ok, "msg": fl_msg},
            "gmail_draft_ready": co_ok and self.composio.connected_accounts() != [],
        }

    def _generate(self, prompt: str, system: str | None = None) -> dict:
        """Core opencode -> ollama fallback. Never hijacked by mock state."""
        system = system or self.system_prompt
        oc_err = "opencode returned an empty reply"
        # 1) opencode
        try:
            reply = self.opencode.chat(prompt, system=system)
            if reply.strip():
                return {"ok": True, "reply": reply.strip(),
                        "engine": "opencode", "tools": []}
        except Exception as exc:  # noqa: BLE001
            oc_err = _format_exc(exc)
        # 2) local fallback
        try:
            reply = self.fallback.chat(prompt, system=system)
            if reply.strip():
                return {"ok": True, "reply": reply.strip(),
                        "engine": "ollama", "tools": [], "note": oc_err}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "reply": "",
                    "error": f"opencode: {oc_err}; fallback: {_format_exc(exc)}"}

    def chat(self, message: str, job: dict | None = None,
             candidate: dict | None = None) -> dict:
        """Public chat entry (used by the web UI).

        While a mock interview is active, plain user messages are treated as
        answers to the interviewer and continue that conversation.
        """
        with self._mock_lock:
            mock = self._mock
        if mock and mock.get("active"):
            return self._mock_turn(message, mock)
        context = self._context_block(job, candidate)
        prompt = (f"{context}\n\n---\n\nUser request:\n{message}" if context
                  else message)
        return self._generate(prompt)

    def _mock_turn(self, message: str, mock: dict) -> dict:
        """Continue an in-progress mock interview with the candidate's answer."""
        if (re.search(r"(?i)\bmock\b.*\b(end|stop|exit)\b", message)
                or re.search(r"(?i)\b(end|stop|exit)\b.*\bmock\b", message)
                or message.strip().lower() in ("end", "stop", "exit", "quit")):
            with self._mock_lock:
                self._mock = None
            return self._generate(
                "The candidate ended the mock interview. Wrap up in 2-3 sentences: "
                "their strongest areas and one thing to work on.",
                system=mock["system"])
        history = mock["history"][-10:]
        prompt = (
            f"{mock['context']}\n\nINTERVIEWER ROLE:\n{mock['system']}\n\n"
            f"Conversation so far:\n" + "\n".join("- " + h for h in history)
            + f"\n\nThe candidate just answered your last question:\n{message}\n\n"
            "Give 1-2 sentences of feedback (what worked, what to sharpen) and name "
            "the best STAR example if relevant. Then ask the NEXT question. Ask only "
            "ONE question. Keep it concise."
        )
        reply = self._generate(prompt, system=mock["system"])
        if reply.get("ok"):
            with self._mock_lock:
                mock["history"].append(f"Candidate: {message[:400]}")
                mock["history"].append(f"Interviewer: {reply['reply'][:600]}")
        return reply

    def compose_draft(self, job: dict | None, candidate: dict | None,
                      kind: str = "followup") -> dict:
        """Ask the agent to write an email draft body (nothing is sent)."""
        kind_desc = {
            "followup": "a short follow-up email for a job application",
            "cold": "a concise cold outreach email to a startup",
            "cover": "a cover-letter style intro email",
        }.get(kind, "an outreach email")
        prompt = (f"Write {kind_desc} for the candidate. Return ONLY the email "
                  f"body (no subject line, no preamble), ready to paste.\n\n"
                  f"Candidate context:\n{self._context_block(job, candidate)}")
        return self._generate(prompt)

    def interview_prep(self, job: dict | None, candidate: dict | None,
                       mode: str = "prep", stage: str = "") -> dict:
        """Interview preparation (ported from ai-job-search's /interview).

        mode="prep": build a stage-specific prep pack (likely questions, STAR
        answer sketches, questions to ask, honest gaps).
        mode="mock": run an interactive mock interview - the agent asks one
        question at a time and gives feedback mapped to the candidate's STAR
        examples (the user replies in a follow-up message).
        """
        context = self._context_block(job, candidate)
        stage_line = f"\nInterview stage: {stage}." if stage else ""
        if mode == "mock":
            system = (
                "You are the interviewer for the role below. Run a mock interview: "
                "start with a warm-up question, then role-specific technical "
                "questions, then 1-2 behavioral questions mapped to the candidate's "
                "STAR examples, then a curveball. Ask ONE question at a time and wait "
                "for the answer. After each answer give 1-2 sentences of feedback "
                "(what worked, what to sharpen) and name the STAR example that fits. "
                "Never invent candidate experience. The candidate can say 'end mock' "
                "to stop."
            )
            prompt = (f"{system}{stage_line}\n\n"
                      f"Candidate and job context:\n{context}\n\n"
                      "Start the interview now: ask your first (warm-up) question.")
            reply = self._generate(prompt, system=system)
            if reply.get("ok"):
                with self._mock_lock:
                    self._mock = {"active": True, "system": system,
                                  "context": context,
                                  "history": [f"Interviewer: {reply['reply']}"]}
            return reply
        prompt = (
            "Build an interview prep pack for this role. Include: "
            "1) Likely questions (role-specific + behavioral), "
            "2) a STAR answer sketch for each of the candidate's STAR "
            "examples mapped to likely questions, 3) good questions for the "
            "candidate to ask the interviewer, 4) honest gap areas and how "
            "to bridge them without inventing experience. Be concrete and "
            "specific to this posting."
            f"{stage_line}\n\n{context}")
        return self._generate(prompt)

    def draft_to_gmail(self, to: str, subject: str, body: str) -> dict:
        """Create a Gmail draft via Composio (never sends)."""
        return self.composio.create_gmail_draft(to=to, subject=subject, body=body)

    # -- internals -----------------------------------------------------------
    @staticmethod
    def _context_block(job: dict | None, candidate: dict | None) -> str:
        parts: list[str] = []
        cand = candidate or {}
        if cand:
            locs = cand.get("preferred_locations") or []
            sal = ""
            lo, hi = cand.get("desired_salary_min"), cand.get("desired_salary_max")
            if lo or hi:
                sal = f"\nDesired salary (annual): {lo or '?'} - {hi or '?'}"
            stars = cand.get("star_examples") or []
            languages = cand.get("languages") or []
            deal_breakers = cand.get("deal_breakers") or []
            parts.append(
                "CANDIDATE\n"
                f"Name: {cand.get('name', '')}\n"
                f"Headline: {cand.get('headline', '')}\n"
                f"Target roles: {', '.join(cand.get('roles') or []) or 'any'}\n"
                f"Years of experience: {cand.get('years_of_exp') or 'n/a'}"
                f"{sal}\n"
                f"Preferred locations: {', '.join(locs) or 'any'}\n"
                f"Languages: {', '.join(languages) or 'n/a'}\n"
                f"Deal-breakers: {', '.join(deal_breakers) or 'none'}\n"
                f"Summary: {cand.get('summary', '')}\n"
                f"Skills: {', '.join(cand.get('skills') or [])}\n"
                f"STAR examples:\n"
                + ("\n".join(f"- {s}" for s in stars) if stars
                   else "(none declared)")
            )
        if job:
            parts.append(
                "JOB POSTING\n"
                f"Title: {job.get('title', '')}\n"
                f"Company: {job.get('company', '')}\n"
                f"Location: {job.get('location', '')}\n"
                f"Description: {(job.get('description') or '')[:4000]}"
            )
        return "\n\n".join(parts)


# --------------------------------------------------------------------------
# factory (used by the Flask app)
# --------------------------------------------------------------------------
def backend_from_config(cfg: dict | None = None) -> AgentBackend:
    cfg = cfg or {}
    agent_cfg = cfg.get("agent", {})
    oc_cfg = agent_cfg.get("opencode", {})
    co_cfg = agent_cfg.get("composio", {})
    fl_cfg = agent_cfg.get("fallback", {})
    return AgentBackend(
        opencode=OpenCodeClient(
            base_url=oc_cfg.get("base_url", DEFAULT_OPENCODE_URL),
            binary=oc_cfg.get("bin", "opencode"),
            spawn=bool(oc_cfg.get("enabled", True)),
        ),
        composio=ComposioBridge(
            api_key=co_cfg.get("api_key", "") or DEFAULT_COMPOSIO_KEY,
            apps=co_cfg.get("apps") or ["gmail"],
        ),
        fallback=OllamaFallback(
            base_url=fl_cfg.get("base_url", "http://localhost:11434"),
            model=fl_cfg.get("model", "deepseek-r1:8b"),
        ),
    )
