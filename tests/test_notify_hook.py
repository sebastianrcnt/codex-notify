from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def load_hook(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    module_path = Path(__file__).resolve().parents[1] / "notify-hook.py"
    spec = importlib.util.spec_from_file_location("notify_hook_for_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    tokens = tmp_path / "notify-hook-tokens.toml"
    monkeypatch.setattr(module, "TOKENS_PATH", tokens)
    monkeypatch.setattr(module, "LOG_FILE", tmp_path / "notify.log")
    return module, tokens


def test_mask_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module, _ = load_hook(tmp_path, monkeypatch)
    assert module._to_redacted_token("123456:ABCDEF") == "123456...CDEF"
    assert module._to_redacted_token("short") == "*****"


def test_secret_redaction(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module, _ = load_hook(tmp_path, monkeypatch)

    source = """\
sk-abcdefghijklmno
xoxb-1234567890abcdef
ghp_ABCDEFGHJKLMN
github_pat_ABCDEFGHJKLMN
123456789:ABCDEFghijkl
AKIAABCDEFGHIJKLMNOP
TOKEN=shouldhide
API_KEY=hide-me
"""

    redacted = module.redact_secrets(source)
    assert "sk-" not in redacted
    assert "xoxb-" not in redacted
    assert "ghp_" not in redacted
    assert "github_pat_" not in redacted
    assert "123456789:ABC" not in redacted
    assert "AKIA" not in redacted
    assert "[REDACTED]" in redacted


def test_load_tokens_defaults_include_body_to_true(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module, _tokens = load_hook(tmp_path, monkeypatch)
    _tokens.write_text(
        "driver = 'telegram'\n[telegram]\ntoken='123456:ABCDEFabcd'\nchat_id='123'\n",
        encoding="utf-8",
    )

    config = module.load_tokens(_tokens)
    assert config["include_body"] is True


def test_load_tokens_respects_explicit_include_body_false(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module, _tokens = load_hook(tmp_path, monkeypatch)
    _tokens.write_text(
        "driver = 'telegram'\n[telegram]\ntoken='123456:ABCDEFabcd'\nchat_id='123'\ninclude_body=false\n",
        encoding="utf-8",
    )

    config = module.load_tokens(_tokens)
    assert config["include_body"] is False


def test_format_message_can_exclude_full_body_when_requested(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module, _tokens = load_hook(tmp_path, monkeypatch)
    long_body = "A" * 1200
    message = module.format_message(
        {
            "type": "agent-turn-complete",
            "last-assistant-message": long_body,
            "cwd": "/tmp/proj",
            "hostname": "host-x",
            "session_id": "aaaaaaaa-bbbb-cccc",
        },
        include_body=False,
    )
    assert len(message) <= 500
    assert long_body not in message


def test_format_message_includes_body_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module, _tokens = load_hook(tmp_path, monkeypatch)
    body = "A" * 1200
    message = module.format_message(
        {
            "type": "agent-turn-complete",
            "last-assistant-message": body,
            "cwd": "/tmp/proj",
            "hostname": "host-x",
            "session_id": "aaaaaaaa-bbbb",
        },
        include_body=None,
    )
    assert len(message) > 500


def test_request_section_appears_before_body_in_pretty_and_plain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module, _tokens = load_hook(tmp_path, monkeypatch)
    payload = {
        "type": "agent-turn-complete",
        "last-assistant-message": "제목 줄\n본문 줄",
        "request": "사용자 요청",
        "cwd": "/tmp/proj",
        "hostname": "host-x",
        "session_id": "aaaaaaaa-bbbb",
    }

    pretty = module.format_message(payload, include_body=True, style="pretty")
    plain = module.format_message(payload, include_body=True, style="plain")

    assert "📝 <b>요청</b>" in pretty
    assert pretty.index("📝 <b>요청</b>") < pretty.index("제목 줄\n본문 줄")
    assert "📝 요청" in plain
    assert plain.index("📝 요청") < plain.index("제목 줄\n본문 줄")


def test_body_includes_title_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module, _tokens = load_hook(tmp_path, monkeypatch)
    assistant_message = "제목 줄\n본문 줄"
    message = module.format_message(
        {
            "type": "agent-turn-complete",
            "last-assistant-message": assistant_message,
            "cwd": "/tmp/proj",
            "hostname": "host-x",
            "session_id": "aaaaaaaa-bbbb",
        },
        include_body=True,
    )

    assert "<b>제목 줄</b>" in message
    assert assistant_message in message


def test_send_fallback_markdown_parse_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module, tokens = load_hook(tmp_path, monkeypatch)
    tokens.write_text(
        "driver = 'telegram'\n[telegram]\ntoken='123456:ABCDEFabcd'\nchat_id='123'\nparse_mode='Markdown'\n",
        encoding="utf-8",
    )

    calls = {"count": 0}

    def _fake_post(url: str, data: dict, timeout: int = 15):
        calls["count"] += 1
        if calls["count"] == 1:
            return (
                400,
                '{"ok":false,"description":"Bad Request: can\'t parse entities: unclosed tag"}',
                {"ok": False, "description": "Bad Request: can't parse entities: unclosed tag"},
            )
        return 200, '{"ok":true}', {"ok": True}

    monkeypatch.setattr(module, "_post_message", _fake_post)

    payload = {
        "type": "agent-turn-complete",
        "status": "ok",
        "cwd": "/tmp/work",
    }

    module.send_notification(payload, tokens_path=tokens)
    assert calls["count"] == 2
