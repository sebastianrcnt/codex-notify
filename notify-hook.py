#!/usr/bin/env python3
"""Codex CLI → Telegram notification hook.

Usage in ~/.codex/config.toml:
    notify = ["python3", "/path/to/notify-hook.py"]

Tokens file (~/.codex/notify-hook-tokens.toml):
    driver = "telegram"

    [telegram]
    token = "123456:ABC-DEF..."
    chat_id = "987654321"
"""

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Tuple

try:
    import tomllib
except ImportError:  # Python < 3.11
    import tomli as tomllib

# ── paths ────────────────────────────────────────────────────────────
CODEX_HOME = Path.home() / ".codex"
TOKENS_CONF = CODEX_HOME / "notify-hook-tokens.toml"
LOG_FILE = CODEX_HOME / "log" / "notify.log"

# Telegram hard limit: 4096 chars
MAX_LEN = 4000  # leave a small buffer


# ── logging ──────────────────────────────────────────────────────────
def log(msg: str) -> None:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {msg}\n")


# ── payload ──────────────────────────────────────────────────────────
def read_payload() -> Dict[str, Any]:
    if len(sys.argv) >= 2 and sys.argv[1].strip():
        return json.loads(sys.argv[1])
    raw = sys.stdin.read()
    if raw and raw.strip():
        return json.loads(raw)
    raise ValueError("No JSON payload in argv or stdin")


# ── tokens ───────────────────────────────────────────────────────────
def load_tokens() -> Tuple[str, str]:
    if not TOKENS_CONF.exists():
        raise FileNotFoundError(f"Missing: {TOKENS_CONF}")

    with open(TOKENS_CONF, "rb") as f:
        config = tomllib.load(f)

    driver = config.get("driver", "")
    if driver != "telegram":
        raise ValueError(f"Unsupported driver '{driver}' in {TOKENS_CONF}")

    telegram = config.get("telegram", {})
    if not isinstance(telegram, dict):
        raise ValueError(f"Missing [telegram] section in {TOKENS_CONF}")

    token = str(telegram.get("token", "")).strip()
    chat_id = str(telegram.get("chat_id", "")).strip()
    if not token or not chat_id:
        raise ValueError(f"Missing telegram.token/chat_id in {TOKENS_CONF}")
    return token, chat_id


# ── message formatting ───────────────────────────────────────────────
def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def format_message(p: Dict[str, Any]) -> str:
    event_type = p.get("type", "unknown")

    # ── agent-turn-complete ──────────────────────────────────────
    if event_type == "agent-turn-complete":
        # last assistant message (markdown from Codex)
        body = p.get("last-assistant-message", "")

        # extract first meaningful line as title
        title_line = ""
        for line in body.splitlines():
            stripped = line.strip().lstrip("#").strip("* ").strip()
            if stripped:
                title_line = stripped
                break
        title_line = title_line or "Turn complete"

        # cwd → project name (last component)
        cwd = p.get("cwd", "")
        project = Path(cwd).name if cwd else "?"
        hostname = _first_value(p, "hostname", "host", "machine")
        session_id = _first_value(p, "session_id", "session-id", "sessionId")
        footer = " ".join(
            [
                _inline_code(f"folder:{project}"),
                _inline_code(f"host:{hostname or '?'}"),
                _inline_code(f"sid:{session_id or '?'}"),
            ]
        )

        # build summary: strip markdown cruft, keep it readable
        summary = _clean_markdown(body)
        summary = truncate(summary, 3000)

        lines = [
            "*Update:*",
            _escape_md(title_line),
            "",
            _escape_md(summary),
            "",
            footer,
        ]
        return "\n".join(lines)

    # ── fallback for unknown event types ─────────────────────────
    raw = json.dumps(p, ensure_ascii=False, indent=2)
    return truncate(f"🔔 Codex event: `{event_type}`\n\n```\n{raw}\n```", MAX_LEN)


def _clean_markdown(text: str) -> str:
    """Light cleanup: collapse bullet noise, keep readable."""
    out_lines: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        # turn "- **Foo** …" into "• Foo …"
        if s.startswith("- **"):
            s = s.replace("- **", "• ", 1).replace("**", "", 1)
        elif s.startswith("- "):
            s = "• " + s[2:]
        # drop lines that are just refs like (file:line)
        if s.startswith("(") and s.endswith(")") and ":" in s:
            continue
        if s:
            out_lines.append(s)
    return "\n".join(out_lines)


def _first_value(payload: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _inline_code(text: str) -> str:
    # Backticks break MarkdownV1 inline code; replace them defensively.
    safe = text.replace("`", "'")
    return f"`{safe}`"


def _escape_md(text: str) -> str:
    """Escape Telegram MarkdownV1 special chars (minimal)."""
    # For parse_mode=Markdown (v1), escape chars that commonly break text.
    # We intentionally leave backticks as-is so inline code can still render.
    for ch in ("_", "*", "["):
        text = text.replace(ch, f"\\{ch}")
    return text


# ── send ─────────────────────────────────────────────────────────────
def send(token: str, chat_id: str, text: str) -> None:
    text = truncate(text, MAX_LEN)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": "true",
    }
    data = urllib.parse.urlencode(payload, encoding="utf-8").encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        log(f"OK {resp.status}")


# ── main ─────────────────────────────────────────────────────────────
def main() -> int:
    log("=== start ===")
    try:
        payload = read_payload()
        token, chat_id = load_tokens()
        text = format_message(payload)
        send(token, chat_id, text)
    except Exception as e:
        log(f"ERROR: {e}")
        return 1
    log("=== done ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
