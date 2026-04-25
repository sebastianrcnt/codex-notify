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
from typing import Optional

import tomlkit

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


def notify_line() -> str:
    values = notify_value()
    return f'notify = ["{values[0]}", "{values[1]}"]'


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


def network_access_state(config_text: str) -> Optional[bool]:
    doc = parse_toml_document(config_text)
    section = doc.get("sandbox_workspace_write")
    if not isinstance(section, tomlkit.items.Table):
        return None

    value = section.get("network_access")
    if not isinstance(value, bool):
        return None
    return value


def set_network_access_true(config_text: str) -> str:
    doc = parse_toml_document(config_text)
    section = doc.get("sandbox_workspace_write")
    if isinstance(section, tomlkit.items.Table):
        section["network_access"] = True
    else:
        table = tomlkit.table()
        table.add("network_access", True)
        doc["sandbox_workspace_write"] = table
    return tomlkit.dumps(doc)


def ensure_network_access_enabled() -> bool:
    """Compatibility helper kept for existing callers.

    In this implementation installation no longer auto-enables the setting;
    this function only reports whether it is already enabled.
    """
    config_path = codex_config_path()
    if not config_path.exists():
        return False
    return network_access_state(_read_file(config_path)) is True


def ensure_codex_home() -> Path:
    home = codex_home()
    home.mkdir(parents=True, exist_ok=True)
    _safe_permissions(home, 0o700)
    return home


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


def _read_file(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _safe_prompt(message: str) -> str:
    value = input(message).strip()
    if not value:
        raise ValueError(f"필수 입력 누락: {message.strip()}")
    return value


def prompt_telegram_credentials() -> tuple[str, str]:
    token = os.environ.get("CODEX_NOTIFY_BOT_TOKEN") or _safe_prompt("텔레그램 봇 토큰: ")
    chat_id = os.environ.get("CODEX_NOTIFY_CHAT_ID") or _safe_prompt("텔레그램 chat_id: ")
    return token, chat_id


def _write_tokens_file(path: Path, token: str, chat_id: str) -> None:
    path.write_text(
        (
            "# One-way Codex notifier config.\n"
            "# Keep this file secure.\n"
            "driver = 'telegram'\n\n"
            "[telegram]\n"
            "# From @BotFather: 123456:ABC...\n"
            f"token = '{token}'\n"
            "# Telegram chat id or super-group id.\n"
            f"chat_id = '{chat_id}'\n"
            "# Send full last message only when CODEX_NOTIFY_INCLUDE_BODY=1.\n"
            "include_body = false\n"
        ),
        encoding="utf-8",
    )


def set_notify_config(*, interactive: bool = True, force: bool = False) -> None:
    config_path = codex_config_path()
    config_text = _read_file(config_path)
    doc = parse_toml_document(config_text)

    if "notify" in doc and not force:
        if not interactive:
            raise RuntimeError("notify 설정이 이미 존재합니다. --force를 사용해 교체하세요.")
        if not confirm(f"{config_path} notify 항목을 교체할까요?", interactive=True, default=False):
            raise RuntimeError("notify config update cancelled")

    if "notify" in doc:
        doc.pop("notify")

    updated = tomlkit.document()
    updated.add("notify", notify_value())
    for key, value in doc.items():
        if key == "notify":
            continue
        updated.add(key, value)

    _backup_config(config_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    _safe_permissions(config_path.parent, 0o700)
    config_path.write_text(tomlkit.dumps(updated), encoding="utf-8")
    logger.info("Updated notify config in %s", config_path)


def remove_notify_config() -> None:
    config_path = codex_config_path()
    if not config_path.exists():
        return

    doc = parse_toml_document(_read_file(config_path))
    if "notify" in doc:
        doc.pop("notify")

    _backup_config(config_path)
    config_path.write_text(tomlkit.dumps(doc), encoding="utf-8")


def set_network_access(enabled: bool, *, config_text: Optional[str] = None) -> str:
    doc = parse_toml_document(config_text or "")
    section = doc.get("sandbox_workspace_write")
    if isinstance(section, tomlkit.items.Table):
        section["network_access"] = enabled
    else:
        table = tomlkit.table()
        table.add("network_access", enabled)
        doc["sandbox_workspace_write"] = table
    return tomlkit.dumps(doc)


def configure_network(enable: bool) -> None:
    config_path = codex_config_path()
    config_text = _read_file(config_path)
    updated = set_network_access(enable, config_text=config_text)
    if config_text == updated:
        return
    _backup_config(config_path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    _safe_permissions(config_path.parent, 0o700)
    config_path.write_text(updated, encoding="utf-8")


def _load_hook_module():
    spec = importlib.util.spec_from_file_location("codex_notify_hook", SOURCE_HOOK)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def install_hook(
    *,
    require_network_check: bool = True,
    no_overwrite: bool = False,
    interactive: bool = True,
    force: bool = False,
    delete_existing_tokens: bool = False,
) -> int:
    hook = installed_hook_path()
    tokens = installed_tokens_path()
    config_path = codex_config_path()

    if not SOURCE_HOOK.exists():
        print(f"SOURCE_HOOK not found: {SOURCE_HOOK}")
        return 1

    ensure_codex_home()

    try:
        _ensure_not_symlink(hook, interactive=interactive, force=force, prompt_action="훅 설치")
        _ensure_not_symlink(tokens, interactive=interactive, force=force, prompt_action="토큰 파일 덮어쓰기")
    except RuntimeError as exc:
        print(str(exc))
        return 1

    if not no_overwrite and not interactive and not force and require_network_check:
        # retained for signature compatibility; no-op check in non-interactive mode.
        pass

    shutil.copy2(SOURCE_HOOK, hook)
    _safe_permissions(hook, 0o700)

    should_write_tokens = True
    if no_overwrite and tokens.exists():
        should_write_tokens = False
    elif tokens.exists() and interactive:
        should_write_tokens = confirm(
            f"{tokens} 파일이 이미 존재해요. 덮어쓸까요?", interactive=True, default=False
        )
        if not should_write_tokens:
            print(f"기존 토큰 파일을 그대로 유지했어요: {tokens}")
    elif tokens.exists() and not interactive and not force:
        should_write_tokens = False

    if should_write_tokens:
        try:
            token, chat_id = prompt_telegram_credentials()
        except ValueError as exc:
            print(f"설치를 취소했어요: {exc}")
            return 1
        _write_tokens_file(tokens, token, chat_id)
        _safe_permissions(tokens, 0o600)

    if delete_existing_tokens:
        # explicit path for compatibility in uninstall tests.
        pass

    try:
        set_notify_config(interactive=interactive, force=force)
    except RuntimeError as exc:
        print(str(exc))
        return 1

    print(f"훅 설치 완료: {hook}")
    if should_write_tokens:
        print(f"토큰 파일 설치 완료: {tokens}")
    print(f"설정 파일 업데이트 완료: {config_path}")

    state = network_access_state(_read_file(config_path))
    if state is not True:
        print(
            "참고: 현재 network_access가 false거나 미설정입니다. Telegram 전송 실패 시 `codex-notify configure-network --enable` 또는 ~/.codex/config.toml 직접 편집으로 활성화하세요."
        )

    return 0


def install(*, interactive: bool = True, force: bool = False, no_overwrite: bool = False) -> int:
    return install_hook(
        require_network_check=False,
        no_overwrite=no_overwrite,
        interactive=interactive,
        force=force,
    )


def uninstall(*, force: bool = False, delete_tokens: bool = False, interactive: bool = True) -> int:
    hook = installed_hook_path()
    tokens = installed_tokens_path()

    remove_notify_config()

    if hook.exists() or hook.is_symlink():
        hook.unlink()
        print(f"훅 제거됨: {hook}")

    if delete_tokens:
        if tokens.exists() or tokens.is_symlink():
            tokens.unlink()
            print(f"토큰 파일 제거됨: {tokens}")
    else:
        if tokens.exists() and interactive and confirm("토큰 파일도 제거할까요?", interactive=True, default=False):
            tokens.unlink()
            print(f"토큰 파일 제거됨: {tokens}")
        else:
            print(f"토큰 파일은 유지됨: {tokens}")

    return 0


def remove_hook(*, force: bool = False, interactive: bool = True, delete_tokens: bool = False) -> int:
    return uninstall(force=force, delete_tokens=delete_tokens, interactive=interactive)


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

    if tokens.exists():
        mode = _format_mode(tokens)
        print(f"Token file mode: {mode}")
        if not is_token_permissions_safe(tokens):
            print("Token file permissions are too open. Recommend 0600.")

    if config_text:
        parsed = parse_toml_document(config_text)
        print(f"Notify installed: {'yes' if parsed.get('notify') is not None else 'no'}")
        state = network_access_state(config_text)
        print(f"network_access: {state if state is not None else 'unset'}")
    else:
        print("Notify installed: no")
        print("network_access: unset")

    return 0


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
        print("토큰 파일이 없습니다. 먼저 install을 실행하세요.")
        return 1

    module = _load_hook_module()
    payload = {
        "type": "codex-notify-test",
        "status": "테스트",
        "cwd": str(Path.cwd()),
        "hostname": os.uname().nodename if hasattr(os, "uname") else "unknown",
        "session_id": "cli-test",
        "summary": "codex-notify CLI test message",
    }
    return 0 if _validate_hook_send(module, tokens, payload, on_failure=True) else 1


def doctor(*, no_network: bool = False, interactive: bool = True) -> int:
    print(f"Python version: {sys.version.split()[0]}")
    print(f"CODEX_HOME: {codex_home()}")
    print(f"Config path: {codex_config_path()}")

    config_path = codex_config_path()
    config_text = _read_file(config_path)
    network_state = network_access_state(config_text) if config_text else None
    print(f"network_access: {network_state if network_state is not None else 'unset'}")

    hook = installed_hook_path()
    hook_exists = hook.exists() or hook.is_symlink()
    print(f"Hook installed: {'yes' if hook_exists else 'no'}")
    print(f"Hook path: {hook}")
    print(f"Hook readable: {'yes' if hook.exists() and os.access(hook, os.R_OK) else 'no'}")
    print(f"Hook executable: {'yes' if hook.exists() and os.access(hook, os.X_OK) else 'no'}")

    token_path = installed_tokens_path()
    token_exists = token_path.exists() or token_path.is_symlink()
    print(f"Token file exists: {'yes' if token_exists else 'no'}")
    if token_exists:
        print(f"Token file mode: {_format_mode(token_path)}")
        print(f"Token file permissions safe: {'yes' if is_token_permissions_safe(token_path) else 'no'}")

    if no_network:
        print("Network check skipped (--no-network)")
        return 0

    if not token_exists:
        print("Token file is missing.")
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
        print("Telegram send check: success")
        return 0
    return 1


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
    install_parser.add_argument("--no-overwrite", action="store_true", help="기존 토큰 유지")
    install_parser.set_defaults(
        func=lambda ns: install(interactive=not ns.no_interactive, force=ns.force, no_overwrite=ns.no_overwrite)
    )

    install_alias = subparsers.add_parser("install-hook", help="Alias for install")
    install_alias.add_argument("--no-overwrite", action="store_true")
    install_alias.set_defaults(
        func=lambda ns: install(interactive=not ns.no_interactive, force=ns.force, no_overwrite=ns.no_overwrite)
    )

    uninstall_parser = subparsers.add_parser("uninstall", help="Uninstall notify hook")
    uninstall_parser.add_argument("--delete-tokens", action="store_true", help="토큰 파일도 삭제")
    uninstall_parser.set_defaults(
        func=lambda ns: uninstall(force=ns.force, interactive=not ns.no_interactive, delete_tokens=ns.delete_tokens)
    )

    remove_alias = subparsers.add_parser("remove-hook", help="Alias for uninstall")
    remove_alias.set_defaults(func=lambda ns: uninstall(force=ns.force, interactive=not ns.no_interactive, delete_tokens=False))

    subparsers.add_parser("status", help="Show status")
    status_parser = subparsers._name_parser_map["status"]
    status_parser.set_defaults(func=lambda _ns: status())

    test_parser = subparsers.add_parser("test", help="Send test message")
    test_parser.set_defaults(func=lambda _ns: test_command())

    doctor_parser = subparsers.add_parser("doctor", help="Run diagnostics")
    doctor_parser.add_argument("--no-network", action="store_true", help="Skip network check")
    doctor_parser.set_defaults(func=lambda ns: doctor(no_network=ns.no_network, interactive=not ns.no_interactive))

    network_parser = subparsers.add_parser("configure-network", help="Set network_access")
    group = network_parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--enable", action="store_true", help="Enable network_access")
    group.add_argument("--disable", action="store_true", help="Disable network_access")
    network_parser.set_defaults(func=lambda ns: configure_network_command(enable=ns.enable))

    return parser.parse_args(argv)


def interactive_onboarding() -> int:
    return install(interactive=True, force=False, no_overwrite=False)


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = _parse_args(argv)
    if not hasattr(args, "func"):
        return interactive_onboarding()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
