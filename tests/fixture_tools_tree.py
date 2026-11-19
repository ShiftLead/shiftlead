"""A switched host's `tools` read in every login state, for the Tools page's login tree (design §4.2b, TD-1974)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

HOME = str(Path.home())


def login(name: str, account: str | None, state: str, **kw: Any) -> dict[str, Any]:
    return {"name": name, "label": None, "folder": f"{HOME}/.{name}", "account": account, "state": state,
            "mismatch": False, "warnings": [], "note": None, "pin": None, "version": "v", **kw}  # fmt: skip


def read() -> dict[str, Any]:
    claude = {
        "adapter": "claude-code", "label": "Claude Code", "binary": "/usr/bin/claude", "version": "2.1.327",
        "installed": True, "supported": True, "found": [],
        "accounts": [
            {"key": "claude-code:paul", "label": None, "plan": "Ultra", "billing": "subscription",
             "models": {"families": ["opus", "sonnet", "haiku"]}, "gauges": [], "version": "a"},
        ],
        "logins": [
            login("claude-paul", "claude-code:paul", "signed_in", label="work laptop"),
            login("claude-conformance", "claude-code:paul", "limited", note="conformance walks record here"),
            login("claude-heather", None, "not_signed_in"),
            login("claude-new", None, "name_account"),
        ],
    }  # fmt: skip
    gemini = {
        "adapter": "gemini", "label": "Gemini", "binary": "/usr/bin/gemini", "version": "0.66.0",
        "installed": True, "supported": True, "found": [{"folder": HOME, "own_home": False}],
        "accounts": [
            {"key": "gemini:paul-google", "label": "Paul's key", "plan": None, "billing": "metered",
             "models": {"families": ["flash-lite"]}, "gauges": [], "version": "b"},
        ],
        "logins": [
            login("gemini-paul", "gemini:paul-google", "sign_in_again", pin="flash-lite", mismatch=True,
                  warnings=["env_key", "billing_mismatch"]),
        ],
    }  # fmt: skip
    return {"host": "kmaster", "read_at": "2026-11-19T12:00:00Z", "switched": True, "tools": [claude, gemini],
            "not_ready": []}  # fmt: skip
