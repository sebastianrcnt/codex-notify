#!/usr/bin/env python3
"""CLI for managing Codex notify hook for Telegram forwarding."""

from __future__ import annotations

import argparse
import importlib.util
import logging
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import tomlkit

try:
    import tomllib
except ImportError:  # pragma: no cover
    import tomli as tomllib

PROJECT_ROOT = Path(__file__).resolve().parent
SOURCE_HOOK = PROJECT_ROOT / "notify-hook.py"

logger = logging.getLogger(__name__)
LAST_LOGGED_CODEX_HOME: Optional[str] = None


def configure_logging() -> None:
    level_name = os.environ.get("CODEX_NOTIFY_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


def codex_home() -> Path:
    global LAST_LOGGED_CODEX_HOME

    override = os.environ.get("CODEX_HOME")
    if override:
        home = Path(override).expanduser()
    else:
        home = Path.home() / ".codex"

    if str(home) != LAST_LOGGED_CODEX_HOME:
        if override:
            logger.info("Using CODEX_HOME override: %s", home)
        else:
            logger.info("Using default CODEX_HOME: %s", home)
        LAST_LOGGED_CODEX_HOME = str(home)
    return home


def codex_config_path() -> Path:
    return codex_home() / "config.toml"


def installed_hook_path() -> Path:
    return codex_home() / "notify-hook.py"


def installed_tokens_path() -> Path:
    return codex_home() / "notify-hook-tokens.toml"


def notify_value() -> list[str]:
    return [str(Path(sys.executable).resolve()), installed_hook_path().as_posix()]


def parse_toml_document(text: str) -> tomlkit.TOMLDocument:
    if not text.strip():
        return tomlkit.document()
    return tomlkit.parse(text)


def confirm(question: str, *, interactive: bool = True, default: bool = False) -> bool:
    if not interactive:
        return default
    prompt = "Y/n" if default else "y/N"
    answer = input(f"{question} ({prompt}): ").strip().lower()
    if not answer:
        return default
    return answer in {"y", "yes"}


def _safe_permissions(path: Path, mode: int) -> bool:
    try:
        path.chmod(mode)
        return True
    except OSError:
        return False


def _format_mode(path: Path) -> Optional[str]:
    try:
        return f"{path.stat().st_mode & 0o777:03o}"
    except FileNotFoundError:
        return None


def is_token_permissions_safe(tokens_path: Path) -> bool:
    mode = _format_mode(tokens_path)
    if mode is None:
        return False
    return int(mode, 8) & 0o077 == 0


def _read_file(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _safe_prompt(message: str) -> str:
    value = input(message).strip()
    if not value:
        raise ValueError(f"필수 입력 누락: {message.strip()}")
    return value


def _to_redacted_token(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:6]}...{value[-4:]}"


def _mask_chat_id(chat_id: str) -> str:
    chat_id = chat_id.strip()
    if not chat_id:
        return ""
    if len(chat_id) <= 4:
        return "*" * len(chat_id)
    return f"{chat_id[:2]}...{chat_id[-2:]}"


def _load_token_config(tokens_path: Path) -> Optional[dict[str, Any]]:
    if not tokens_path.exists():
        return None
    with open(tokens_path, "rb") as fileobj:
        raw = tomllib.load(fileobj)
    telegram = raw.get("telegram", {})
    if not isinstance(telegram, dict):
        telegram = {}
    return {
        "driver": str(raw.get("driver", "")).strip(),
        "token": str(telegram.get("token", "")).strip(),
        "chat_id": str(telegram.get("chat_id", "")).strip(),
    }


def _ensure_not_symlink(path: Path, *, interactive: bool, force: bool, prompt_action: str) -> None:
    if not path.exists() and not path.is_symlink():
        return
    if not path.is_symlink():
        return

    if interactive and not force:
        if not confirm(f"{path}는 심볼릭 링크입니다. {prompt_action} 위해 덮어쓸까요?", interactive=True, default=False):
            raise RuntimeError("symlink overwrite denied")
    elif not interactive and not force:
        raise RuntimeError(f"{path}는 심볼릭 링크이며 --force 없이 덮어쓸 수 없습니다.")

    path.unlink()


def _backup_config(config_path: Path) -> Optional[Path]:
    if not config_path.exists():
        return None
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup = config_path.with_name(f"{config_path.name}.bak.{timestamp}")
    shutil.copy2(config_path, backup)
    return backup


def ensure_codex_home() -> Path:
    home = codex_home()
    home.mkdir(parents=True, exist_ok=True)
    _safe_permissions(home, 0o700)
    return home


def _write_tokens_file(path: Path, token: str, chat_id: str) -> None:
    path.write_text(
        (
            "# One-way Codex notifier config.\n"
            "# This project is a Telegram outbound notify hook only.\n"
            "driver = 'telegram'\n\n"
            "[telegram]\n"
            "# From @BotFather: 123456:ABC...\n"
            f"token = '{token}'\n"
            "# Telegram chat id or super-group id.\n"
            f"chat_id = '{chat_id}'\n"
            "# Include full body only when explicitly needed.\n"
            "include_body = false\n"
        ),
        encoding="utf-8",
    )
    _safe_permissions(path, 0o600)


def prompt_telegram_credentials() -> tuple[str, str]:
    token = os.environ.get("CODEX_NOTIFY_BOT_TOKEN") or _safe_prompt("텔레그램 봇 토큰: ")
    chat_id = os.environ.get("CODEX_NOTIFY_CHAT_ID") or _safe_prompt("텔레그램 chat_id: ")
    return token, chat_id


def network_access_state(config_text: str) -> Optional[bool]:
    doc = parse_toml_document(config_text)
    section = doc.get("sandbox_workspace_write")
    if not isinstance(section, tomlkit.items.Table):
        return None
    value = section.get("network_access")
    if not isinstance(value, bool):
        return None
    return value


def _set_network_access(enabled: bool, *, config_text: str) -> str:
    doc = parse_toml_document(config_text)
    section = doc.get("sandbox_workspace_write")
    if isinstance(section, tomlkit.items.Table):
        section["network_access"] = enabled
    else:
        table = tomlkit.table()
        table.add("network_access", enabled)
        doc["sandbox_workspace_write"] = table
    return tomlkit.dumps(doc)


def _is_our_notify_entry(entry: Any) -> bool:
    if not isinstance(entry, list):
        return False
    if len(entry) < 2:
        return False
    command = str(entry[1]).strip()
    if not command:
        return False
    try:
        return Path(command).expanduser() == installed_hook_path()
    except OSError:
        return False


def set_notify_config(*, interactive: bool = True, force: bool = False) -> None:
    config_path = codex_config_path()
    config_text = _read_file(config_path)
    doc = parse_toml_document(config_text)
    existing = doc.get("notify")

    if existing is not None and not _is_our_notify_entry(existing):
        if force:
            pass
        elif interactive:
            if not confirm(
                f"{config_path}의 기존 notify 설정은 codex-notify가 아닙니다. 교체할까요?",
                interactive=True,
                default=False,
            ):
                raise RuntimeError("notify config update cancelled")
        else:
            raise RuntimeError("기존 notify 설정이 codex-notify가 아닙니다. --force 없이 교체할 수 없습니다.")

    desired = notify_value()
    if isinstance(existing, list) and [str(x) for x in existing] == desired:
        return

    doc["notify"] = desired
    _backup_config(config_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    _safe_permissions(config_path.parent, 0o700)
    config_path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    logger.info("Updated notify config in %s", config_path)


def remove_notify_config() -> None:
    config_path = codex_config_path()
    if not config_path.exists():
        return
    doc = parse_toml_document(_read_file(config_path))
    if "notify" not in doc:
        return
    doc.pop("notify")
    _backup_config(config_path)
    config_path.write_text(tomlkit.dumps(doc), encoding="utf-8")


def _install_or_update_hook(*, interactive: bool, force: bool) -> None:
    hook = installed_hook_path()
    ensure_codex_home()
    _ensure_not_symlink(hook, interactive=interactive, force=force, prompt_action="훅 설치")
    if not SOURCE_HOOK.exists():
        raise RuntimeError(f"SOURCE_HOOK not found: {SOURCE_HOOK}")
    shutil.copy2(SOURCE_HOOK, hook)
    _safe_permissions(hook, 0o700)


def install(*, interactive: bool = True, force: bool = False) -> int:
    tokens = installed_tokens_path()
    try:
        _install_or_update_hook(interactive=interactive, force=force)
        set_notify_config(interactive=interactive, force=force)
    except RuntimeError as exc:
        print(str(exc))
        return 1

    if tokens.exists():
        _safe_permissions(tokens, 0o600)
        print(f"기존 credential 파일을 유지했어요: {tokens}")
    else:
        try:
            token, chat_id = prompt_telegram_credentials()
        except ValueError as exc:
            print(f"credential 입력이 없어 설치를 중단했어요: {exc}")
            return 1
        _write_tokens_file(tokens, token, chat_id)
        print(f"credential 파일 생성 완료: {tokens}")

    print(f"훅 설치 완료: {installed_hook_path()}")
    print(f"설정 파일 업데이트 완료: {codex_config_path()}")
    if network_access_state(_read_file(codex_config_path())) is not True:
        print(
            "참고: Telegram 전송이 실패하면 `codex-notify configure-network --enable` 또는 ~/.codex/config.toml 수동 편집으로 network_access를 켜세요."
        )
    return 0


def update(*, interactive: bool = True, force: bool = False) -> int:
    try:
        _install_or_update_hook(interactive=interactive, force=force)
        set_notify_config(interactive=interactive, force=force)
    except RuntimeError as exc:
        print(str(exc))
        return 1

    tokens = installed_tokens_path()
    if tokens.exists():
        _safe_permissions(tokens, 0o600)
    print(f"훅 업데이트 완료: {installed_hook_path()}")
    print("credential 파일은 변경하지 않았어요.")
    return 0


def reconfigure(*, interactive: bool = True, force: bool = False) -> int:
    tokens = installed_tokens_path()
    ensure_codex_home()
    try:
        _ensure_not_symlink(tokens, interactive=interactive, force=force, prompt_action="credential 재설정")
        token, chat_id = prompt_telegram_credentials()
    except (RuntimeError, ValueError) as exc:
        print(str(exc))
        return 1

    _write_tokens_file(tokens, token, chat_id)
    print(f"credential 재설정 완료: {tokens}")
    return 0


def uninstall(*, force: bool = False, delete_credentials: bool = False, interactive: bool = True) -> int:
    del force  # currently kept for CLI compatibility.
    hook = installed_hook_path()
    tokens = installed_tokens_path()

    remove_notify_config()

    if hook.exists() or hook.is_symlink():
        hook.unlink()
        print(f"훅 제거됨: {hook}")

    remove_tokens = delete_credentials
    if not delete_credentials and tokens.exists() and interactive:
        remove_tokens = confirm("credential 파일도 제거할까요?", interactive=True, default=False)

    if remove_tokens and (tokens.exists() or tokens.is_symlink()):
        tokens.unlink()
        print(f"credential 파일 제거됨: {tokens}")
    else:
        print(f"credential 파일은 유지됨: {tokens}")

    return 0


def status() -> int:
    hook = installed_hook_path()
    tokens = installed_tokens_path()
    log_path = codex_home() / "log" / "notify.log"
    config_path = codex_config_path()
    config_text = _read_file(config_path)

    print("=== codex-notify status ===")
    print(f"CODEX_HOME: {codex_home()}")
    print(f"Config: {config_path} ({'exists' if config_path.exists() else 'missing'})")
    print(f"Hook: {hook} ({'exists' if hook.exists() else 'missing'})")
    print(f"Token file: {tokens} ({'exists' if tokens.exists() else 'missing'})")
    print(f"Log file: {log_path} ({'exists' if log_path.exists() else 'missing'})")

    if hook.exists():
        print(f"Hook readable: {'yes' if os.access(hook, os.R_OK) else 'no'}")
        print(f"Hook executable: {'yes' if os.access(hook, os.X_OK) else 'no'}")
        print(f"Hook mode: {_format_mode(hook)}")

    token_cfg = _load_token_config(tokens)
    if tokens.exists():
        print(f"Token file mode: {_format_mode(tokens)}")
        if not is_token_permissions_safe(tokens):
            print("Token file permissions are too open. Recommend 0600.")
    if token_cfg:
        print(f"Credential loaded: {'yes' if token_cfg['driver'] == 'telegram' and token_cfg['token'] and token_cfg['chat_id'] else 'no'}")
        print(f"Token masked: {_to_redacted_token(token_cfg['token'])}")
        print(f"Chat ID masked: {_mask_chat_id(token_cfg['chat_id'])}")

    if config_text:
        parsed = parse_toml_document(config_text)
        print(f"Notify installed: {'yes' if parsed.get('notify') is not None else 'no'}")
        print(f"Notify points to stable hook: {'yes' if _is_our_notify_entry(parsed.get('notify')) else 'no'}")
        state = network_access_state(config_text)
        print(f"network_access: {state if state is not None else 'unset'}")
    else:
        print("Notify installed: no")
        print("network_access: unset")

    return 0


def _load_hook_module():
    spec = importlib.util.spec_from_file_location("codex_notify_hook", SOURCE_HOOK)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _validate_hook_send(module, tokens_path: Path, payload: dict, *, on_failure: bool = False) -> bool:
    try:
        module.send_notification(payload, tokens_path=tokens_path)
        print("Telegram test send succeeded")
        return True
    except Exception as exc:
        if on_failure:
            print(f"Telegram test send failed: {exc}")
        return False


def test_command() -> int:
    tokens = installed_tokens_path()
    if not tokens.exists():
        print("credential 파일이 없습니다. install 또는 reconfigure를 먼저 실행하세요.")
        return 1

    module = _load_hook_module()
    payload = {
        "type": "codex-notify-test",
        "status": "Codex turn complete",
        "cwd": str(Path.cwd()),
        "hostname": os.uname().nodename if hasattr(os, "uname") else "unknown",
        "session_id": "cli-test",
        "summary": "codex-notify CLI test message",
    }
    return 0 if _validate_hook_send(module, tokens, payload, on_failure=True) else 1


def doctor(*, no_network: bool = False, interactive: bool = True) -> int:
    print("=== codex-notify doctor ===")
    print(f"Python version: {sys.version.split()[0]}")
    print(f"CODEX_HOME: {codex_home()}")
    print(f"Config path: {codex_config_path()} (exists={codex_config_path().exists()})")

    config_text = _read_file(codex_config_path())
    if config_text:
        parsed = parse_toml_document(config_text)
        print(f"Notify installed: {'yes' if parsed.get('notify') is not None else 'no'}")
        print(f"Notify points to stable hook: {'yes' if _is_our_notify_entry(parsed.get('notify')) else 'no'}")
    else:
        print("Notify installed: no")
    network_state = network_access_state(config_text) if config_text else None
    print(f"network_access: {network_state if network_state is not None else 'unset'}")

    hook = installed_hook_path()
    print(f"Hook path: {hook}")
    print(f"Hook exists: {'yes' if hook.exists() else 'no'}")
    print(f"Hook readable: {'yes' if hook.exists() and os.access(hook, os.R_OK) else 'no'}")
    print(f"Hook executable: {'yes' if hook.exists() and os.access(hook, os.X_OK) else 'no'}")
    print(f"Hook mode: {_format_mode(hook) if hook.exists() else 'missing'}")

    token_path = installed_tokens_path()
    token_cfg = _load_token_config(token_path)
    print(f"Token file path: {token_path}")
    print(f"Token file exists: {'yes' if token_path.exists() else 'no'}")
    if token_path.exists():
        print(f"Token file mode: {_format_mode(token_path)}")
        print(f"Token file permissions safe: {'yes' if is_token_permissions_safe(token_path) else 'no'}")
    if token_cfg:
        print(f"Credential parse: {'ok' if token_cfg['driver'] == 'telegram' and token_cfg['token'] and token_cfg['chat_id'] else 'invalid'}")
        print(f"Token masked: {_to_redacted_token(token_cfg['token'])}")
        print(f"Chat ID masked: {_mask_chat_id(token_cfg['chat_id'])}")
    else:
        print("Credential parse: missing")

    print(f"Log file: {codex_home() / 'log' / 'notify.log'}")
    if no_network:
        print("Telegram network test: skipped (--no-network)")
        return 0

    if not token_path.exists():
        print("Telegram network test: skipped (credential missing)")
        return 1

    module = _load_hook_module()
    payload = {
        "type": "codex-notify-doctor",
        "status": "doctor",
        "cwd": str(Path.cwd()),
        "hostname": os.uname().nodename if hasattr(os, "uname") else "unknown",
        "session_id": "doctor-check",
        "summary": "Doctor check",
    }
    if _validate_hook_send(module, token_path, payload, on_failure=not interactive):
        print("Telegram network test: success")
        return 0
    print("Telegram network test: failed")
    return 1


def configure_network(enable: bool) -> None:
    config_path = codex_config_path()
    config_text = _read_file(config_path)
    updated = _set_network_access(enable, config_text=config_text)
    if config_text == updated:
        return
    _backup_config(config_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    _safe_permissions(config_path.parent, 0o700)
    config_path.write_text(updated, encoding="utf-8")


def configure_network_command(*, enable: bool) -> int:
    configure_network(enable)
    print(f"network_access = {'true' if enable else 'false'} in {codex_config_path()}")
    return 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Codex Telegram notify manager")
    parser.add_argument("--no-interactive", action="store_true", help="비대화형 모드")
    parser.add_argument("--force", action="store_true", help="강제 실행")

    subparsers = parser.add_subparsers(dest="command")

    install_parser = subparsers.add_parser("install", help="Install notify hook")
    install_parser.set_defaults(func=lambda ns: install(interactive=not ns.no_interactive, force=ns.force))

    update_parser = subparsers.add_parser("update", help="Update installed hook and notify config")
    update_parser.set_defaults(func=lambda ns: update(interactive=not ns.no_interactive, force=ns.force))

    reconfigure_parser = subparsers.add_parser("reconfigure", help="Reconfigure Telegram credentials only")
    reconfigure_parser.set_defaults(func=lambda ns: reconfigure(interactive=not ns.no_interactive, force=ns.force))

    install_alias = subparsers.add_parser("install-hook", help="Alias for install")
    install_alias.set_defaults(func=lambda ns: install(interactive=not ns.no_interactive, force=ns.force))

    uninstall_parser = subparsers.add_parser("uninstall", help="Uninstall notify hook")
    uninstall_parser.add_argument("--delete-credentials", action="store_true", help="credential 파일도 삭제")
    uninstall_parser.add_argument("--delete-tokens", action="store_true", help=argparse.SUPPRESS)
    uninstall_parser.set_defaults(
        func=lambda ns: uninstall(
            force=ns.force,
            interactive=not ns.no_interactive,
            delete_credentials=bool(ns.delete_credentials or ns.delete_tokens),
        )
    )

    remove_alias = subparsers.add_parser("remove-hook", help="Alias for uninstall")
    remove_alias.set_defaults(
        func=lambda ns: uninstall(force=ns.force, interactive=not ns.no_interactive, delete_credentials=False)
    )

    status_parser = subparsers.add_parser("status", help="Show status")
    status_parser.set_defaults(func=lambda _ns: status())

    test_parser = subparsers.add_parser("test", help="Send test message")
    test_parser.set_defaults(func=lambda _ns: test_command())

    doctor_parser = subparsers.add_parser("doctor", help="Run diagnostics")
    doctor_parser.add_argument("--no-network", action="store_true", help="Skip Telegram network test")
    doctor_parser.set_defaults(func=lambda ns: doctor(no_network=ns.no_network, interactive=not ns.no_interactive))

    network_parser = subparsers.add_parser("configure-network", help="Set network_access")
    group = network_parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--enable", action="store_true", help="Enable network_access")
    group.add_argument("--disable", action="store_true", help="Disable network_access")
    network_parser.set_defaults(func=lambda ns: configure_network_command(enable=ns.enable))

    return parser.parse_args(argv)


def interactive_onboarding() -> int:
    return install(interactive=True, force=False)


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = _parse_args(argv)
    if not hasattr(args, "func"):
        return interactive_onboarding()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
