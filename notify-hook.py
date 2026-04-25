#!/usr/bin/env python3
"""Codex CLI → Telegram notification hook."""

from __future__ import annotations

import html
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Tuple

try:
    import tomllib
except ImportError:  # pragma: no cover
    import tomli as tomllib

CODEX_HOME = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
TOKENS_PATH = CODEX_HOME / "notify-hook-tokens.toml"
LOG_FILE = CODEX_HOME / "log" / "notify.log"

MAX_MESSAGE_LEN = 4000


def _bool_from_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on", "y"}


def _current_debug() -> bool:
    return _bool_from_env("CODEX_NOTIFY_DEBUG")


def codex_home() -> Path:
    return CODEX_HOME


def tokens_path() -> Path:
    path = os.environ.get("CODEX_NOTIFY_TOKENS_PATH")
    return Path(path).expanduser() if path else TOKENS_PATH


def log_file() -> Path:
    return LOG_FILE


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _to_redacted_token(token: str) -> str:
    token = token.strip()
    if not token:
        return ""
    if len(token) <= 8:
        return "*" * len(token)
    return f"{token[:6]}...{token[-4:]}"


_SECRET_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9]{10,}\b"),
    re.compile(r"\bxoxb-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{10,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{10,}\b"),
    re.compile(r"\b[0-9]{5,16}:[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
]


def redact_secrets(text: str, known_tokens: Iterable[str] | None = None) -> str:
    replaced = text
    for pattern in _SECRET_PATTERNS:
        replaced = pattern.sub("[REDACTED]", replaced)

    key_value_pattern = re.compile(r"(?im)^\s*([A-Za-z0-9_]{2,})\s*=\s*(.+)$")

    def _mask_value(match: re.Match[str]) -> str:
        key = match.group(1)
        value = match.group(2)
        upper = key.upper()
        if any(x in upper for x in ("TOKEN", "SECRET", "PASSWORD", "API_KEY")):
            return match.group(0).replace(value, "[REDACTED]")
        return match.group(0)

    replaced = key_value_pattern.sub(_mask_value, replaced)

    if known_tokens:
        for known in known_tokens:
            if not known:
                continue
            replaced = replaced.replace(known, _to_redacted_token(known))
            # very short token-like fragments may still leak; remove obvious duplicates.
            replaced = replaced.replace(f"{known[:4]}...", "[REDACTED]")
    return replaced


def read_payload() -> Dict[str, Any]:
    if len(sys.argv) >= 2 and sys.argv[1].strip():
        return json.loads(sys.argv[1])
    raw = sys.stdin.read()
    if raw and raw.strip():
        return json.loads(raw)
    raise ValueError("No JSON payload in argv or stdin")


def load_tokens(path: Optional[Path] = None) -> Dict[str, Any]:
    token_path = path or tokens_path()
    if not token_path.exists():
        raise FileNotFoundError(f"Missing token file: {token_path}")

    with open(token_path, "rb") as fileobj:
        config = tomllib.load(fileobj)

    driver = config.get("driver", "")
    if driver != "telegram":
        raise ValueError(f"Unsupported driver '{driver}' in {token_path}")

    telegram = config.get("telegram", {})
    if not isinstance(telegram, dict):
        raise ValueError(f"Missing [telegram] section in {token_path}")

    token = str(telegram.get("token", "")).strip()
    chat_id = str(telegram.get("chat_id", "")).strip()
    if not token or not chat_id:
        raise ValueError(f"Missing telegram.token/chat_id in {token_path}")

    include_body = bool(telegram.get("include_body", False) or _bool_from_env("CODEX_NOTIFY_INCLUDE_BODY"))
    style = str(telegram.get("style", "pretty") or "pretty").strip().lower()
    if style not in {"plain", "compact", "pretty"}:
        style = "pretty"
    show_debug = bool(telegram.get("show_debug", True))

    parse_mode = telegram.get("parse_mode")
    if parse_mode is not None:
        parse_mode = str(parse_mode).strip()
        if parse_mode.lower() in {"", "none", "plain"}:
            parse_mode = None
    elif style == "pretty":
        parse_mode = "HTML"

    return {
        "token": token,
        "chat_id": chat_id,
        "include_body": include_body,
        "parse_mode": parse_mode,
        "style": style,
        "show_debug": show_debug,
    }


def _safe_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    return text.strip()


def _shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def _h(text: Any) -> str:
    return html.escape(_safe_text(text), quote=False)


def _folder_name(payload: Dict[str, Any]) -> str:
    cwd = _safe_text(payload.get("cwd") or payload.get("workdir") or payload.get("path"))
    if not cwd:
        return "unknown"
    try:
        return Path(cwd).name
    except Exception:
        return cwd[-24:]


def _session_short(payload: Dict[str, Any]) -> str:
    candidates = [
        "session_id",
        "session",
        "id",
        "turn-id",
        "turn_id",
        "thread-id",
        "thread_id",
    ]
    for key in candidates:
        session = _safe_text(payload.get(key))
        if session:
            return session[:8]
    return "unknown"


def _first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def _remaining_body(text: str) -> str:
    lines = text.splitlines()
    if not lines:
        return ""

    first_seen = False
    rest: list[str] = []
    for line in lines:
        if not first_seen and line.strip():
            first_seen = True
            continue
        if first_seen:
            rest.append(line)
    return "\n".join(rest).strip()


def _clean_summary(payload: Dict[str, Any], include_body: bool) -> str:
    candidate_keys = [
        "summary",
        "status",
        "title",
        "last-message",
        "last-assistant-message",
        "assistant-message",
        "message",
        "text",
    ]
    for key in candidate_keys:
        value = _safe_text(payload.get(key))
        if value:
            break
    else:
        value = ""

    if include_body:
        body = value
    else:
        # Keep notification previews focused on the actual first result line.
        body = _shorten(_first_nonempty_line(value), 240)

    return body.strip()


def _request_excerpt(payload: Dict[str, Any], include_body: bool) -> str:
    messages = payload.get("input-messages") or payload.get("input_messages")
    if isinstance(messages, list):
        for item in reversed(messages):
            text = _safe_text(item)
            if text:
                return text if include_body else _shorten(text.replace("\n", " "), 320)

    for key in ("prompt", "request", "user-message", "user_message", "input"):
        text = _safe_text(payload.get(key))
        if text:
            return text if include_body else _shorten(text.replace("\n", " "), 320)
    return ""


def _event_icon(event_type: str) -> str:
    if event_type == "agent-turn-complete":
        return "✅"
    if event_type == "codex-notify-test":
        return "🔔"
    if event_type == "codex-notify-doctor":
        return "🩺"
    return "📣"


def _escape_markdown(text: str, parse_mode: Optional[str]) -> str:
    if not parse_mode:
        return text

    mode = str(parse_mode).strip().lower()
    if mode == "markdown":
        specials = r"_[]()~`>#+-=|{}.!\\*"
    elif mode == "markdownv2":
        specials = r"_[]()~`>#+-=|{}.!\\*"
    else:
        return text

    out = []
    for char in text:
        if char in specials:
            out.append("\\")
        out.append(char)
    return "".join(out)


def _message_context(payload: Dict[str, Any], include: bool) -> Dict[str, str]:
    event_type = _safe_text(payload.get("type") or payload.get("event") or "unknown")
    status_line = _safe_text(
        payload.get("status")
        or payload.get("status_line")
        or "Codex turn complete"
    )
    folder = _folder_name(payload)
    host = _safe_text(payload.get("hostname") or payload.get("host") or socket.gethostname())
    session = _session_short(payload)
    summary = _clean_summary(payload, include)
    raw_title = _first_nonempty_line(summary) or status_line or "Codex notification"
    title = _shorten(raw_title.replace("\n", " "), 240)
    request = _request_excerpt(payload, include)
    body = _remaining_body(summary) if include else ""
    if include and not body and len(raw_title) > 240:
        body = raw_title[240:].strip()

    return {
        "event": event_type,
        "status": status_line,
        "folder": folder,
        "host": host,
        "session": session,
        "summary": summary,
        "title": title,
        "body": _shorten(body, 2200),
        "request": request,
        "client": _safe_text(payload.get("client")),
    }


def _format_plain_message(ctx: Dict[str, str], *, include_body: bool, show_debug: bool) -> str:
    lines = [
        f"{_event_icon(ctx['event'])} {ctx['title']}",
    ]
    if include_body and ctx["body"]:
        lines.extend(["", ctx["body"]])
    if ctx["request"]:
        lines.extend(["", "요청", ctx["request"]])

    lines.extend(["", f"📁 {ctx['folder']} · 🖥 {ctx['host']} · 🧵 {ctx['session']}"])

    if show_debug:
        debug_lines = [
            "",
            "debug",
            f"event: {ctx['event']}",
            f"status: {ctx['status']}",
            f"folder: {ctx['folder']}",
            f"host: {ctx['host']}",
            f"session: {ctx['session']}",
        ]
        if ctx["client"]:
            debug_lines.append(f"client: {ctx['client']}")
        lines.extend(debug_lines)

    return "\n".join(line for line in lines if line is not None)


def _format_pretty_message(ctx: Dict[str, str], *, include_body: bool, show_debug: bool) -> str:
    lines = [
        f"{_event_icon(ctx['event'])} <b>{_h(ctx['title'])}</b>",
    ]
    if include_body and ctx["body"]:
        lines.extend(["", _h(ctx["body"])])
    if ctx["request"]:
        lines.extend(["", "<b>요청</b>", _h(ctx["request"])])

    lines.extend([
        "",
        f"📁 <code>{_h(ctx['folder'])}</code> · 🖥 <code>{_h(ctx['host'])}</code> · 🧵 <code>{_h(ctx['session'])}</code>",
    ])

    if show_debug:
        debug = [
            f"event: {ctx['event']}",
            f"status: {ctx['status']}",
            f"folder: {ctx['folder']}",
            f"host: {ctx['host']}",
            f"session: {ctx['session']}",
        ]
        if ctx["client"]:
            debug.append(f"client: {ctx['client']}")
        lines.extend(["", f"<pre>{_h(chr(10).join(debug))}</pre>"])

    return "\n".join(line for line in lines if line is not None)


def format_message(
    payload: Dict[str, Any],
    *,
    include_body: Optional[bool] = None,
    style: str = "pretty",
    show_debug: bool = True,
) -> str:
    include = bool(include_body)
    if include_body is None:
        include = _bool_from_env("CODEX_NOTIFY_INCLUDE_BODY")

    ctx = _message_context(payload, include)
    normalized_style = (style or "pretty").strip().lower()

    if normalized_style == "compact":
        msg = f"{_event_icon(ctx['event'])} {ctx['title']}\n📁 {ctx['folder']} · 🖥 {ctx['host']} · 🧵 {ctx['session']}"
    elif normalized_style == "plain":
        msg = _format_plain_message(ctx, include_body=include, show_debug=show_debug)
    else:
        msg = _format_pretty_message(ctx, include_body=include, show_debug=show_debug)

    if not include and len(msg) > 1000:
        msg = _shorten(msg, 1000)
    else:
        msg = _shorten(msg, MAX_MESSAGE_LEN)

    return msg


def _is_parse_error(status_code: int, payload: Dict[str, Any]) -> bool:
    if status_code != 400:
        return False
    error = str(payload.get("description", "")).lower()
    return "parse" in error or "entity" in error


def _post_message(url: str, data: Dict[str, Any], timeout: int = 15) -> Tuple[int, str, Dict[str, Any]]:
    body = urllib.parse.urlencode(data, encoding="utf-8").encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="ignore")
            status = response.status
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read().decode("utf-8", errors="ignore")
    except urllib.error.URLError as exc:
        raise RuntimeError(str(exc.reason)) from exc

    try:
        payload = json.loads(raw) if raw else {}
        if isinstance(payload, dict):
            if not payload.get("ok") and status == 200:
                status = 400
        else:
            payload = {}
    except json.JSONDecodeError:
        payload = {}

    return status, raw, payload


def _send_once(token: str, chat_id: str, text: str, parse_mode: Optional[str]) -> bool:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": "true",
    }
    if parse_mode:
        if str(parse_mode).strip().lower() in {"markdown", "markdownv2"}:
            payload["text"] = _escape_markdown(text, parse_mode)
        payload["parse_mode"] = parse_mode

    status, raw, response = _post_message(url, payload)
    if status != 200:
        raise RuntimeError(f"HTTP {status} {response.get('description', raw) if isinstance(response, dict) else raw}")
    return True


def send_notification(payload: Dict[str, Any], *, tokens_path: Optional[Path] = None) -> None:
    token_cfg = load_tokens(tokens_path)
    token = token_cfg["token"]
    chat_id = token_cfg["chat_id"]
    include_body = token_cfg.get("include_body")
    parse_mode = token_cfg.get("parse_mode")
    style = str(token_cfg.get("style") or "pretty")
    show_debug = bool(token_cfg.get("show_debug", True))

    message = format_message(payload, include_body=bool(include_body), style=style, show_debug=show_debug)
    message = redact_secrets(message, known_tokens=[token, chat_id])
    redacted_token = _to_redacted_token(token)

    try:
        _send_once(token, chat_id, message, parse_mode)
        _log_event(payload, "success", token_hint=redacted_token, status_code=200)
        return
    except RuntimeError as exc:
        if parse_mode and _is_parse_error(400, {"description": str(exc)}):
            _log_event(payload, "retry", token_hint=redacted_token, error=str(exc))
            fallback = format_message(payload, include_body=bool(include_body), style="plain", show_debug=show_debug)
            fallback = redact_secrets(fallback, known_tokens=[token, chat_id])
            _send_once(token, chat_id, fallback, parse_mode=None)
            _log_event(payload, "success", token_hint=redacted_token, status_code=200)
            return
        _log_event(payload, "failure", token_hint=redacted_token, status_code=400, error=str(exc))
        raise


def _log_event(payload: Dict[str, Any], result: str, *, token_hint: str, status_code: Optional[int] = None, error: Optional[str] = None) -> None:
    event_type = _safe_text(payload.get("type") or payload.get("event") or "unknown")
    safe_token = token_hint or ""
    line = {
        "ts": _now(),
        "event": event_type,
        "result": result,
        "token": safe_token,
    }
    if status_code is not None:
        line["status"] = status_code
    if error:
        line["error"] = redact_secrets(str(error))
    if _current_debug():
        msg = _safe_text(payload.get("status") or payload.get("summary") or "")
        line["debug_summary"] = redact_secrets(msg)

    _ensure_parent(log_file())
    with open(log_file(), "a", encoding="utf-8") as fileobj:
        fileobj.write(json.dumps(line, ensure_ascii=False) + "\n")


def main() -> int:
    try:
        payload = read_payload()
        send_notification(payload)
    except Exception as exc:
        _log_event(locals().get("payload", {}), "failure", token_hint="", error=str(exc))
        return 1
    return 0


def redact_test_text(text: str) -> str:
    return redact_secrets(text)


if __name__ == "__main__":
    raise SystemExit(main())
