#!/usr/bin/env python3
"""Codex notify CLI.

Usage:
    uv run main.py                 # onboarding
    uv run main.py install-hook
    uv run main.py remove-hook
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

CODEX_HOME = Path.home() / ".codex"
CODEX_CONFIG = CODEX_HOME / "config.toml"
INSTALLED_HOOK = CODEX_HOME / "notify-hook.py"
INSTALLED_TOKENS = CODEX_HOME / "notify-hook-tokens.toml"

PROJECT_ROOT = Path(__file__).resolve().parent
SOURCE_HOOK = PROJECT_ROOT / "notify-hook.py"

NOTIFY_LINE = "notify = ['python3', '~/.codex/notify-hook.py']"
NETWORK_SECTION_HEADER = "[sandbox_workspace_write]"
NETWORK_LINE = "network_access = true"


def confirm(question: str) -> bool:
    answer = input(f"{question} (y/N): ").strip().lower()
    return answer in {"y", "yes"}


def set_notify_config() -> None:
    CODEX_HOME.mkdir(parents=True, exist_ok=True)

    if CODEX_CONFIG.exists():
        text = CODEX_CONFIG.read_text(encoding="utf-8")
    else:
        text = ""

    if re.search(r"(?m)^\s*notify\s*=.*$", text):
        updated = re.sub(r"(?m)^\s*notify\s*=.*$", NOTIFY_LINE, text, count=1)
    else:
        suffix = "" if not text or text.endswith("\n") else "\n"
        updated = f"{text}{suffix}{NOTIFY_LINE}\n"

    CODEX_CONFIG.write_text(updated, encoding="utf-8")


def remove_notify_config() -> None:
    if not CODEX_CONFIG.exists():
        return

    text = CODEX_CONFIG.read_text(encoding="utf-8")
    updated = re.sub(r"(?m)^\s*notify\s*=.*$\n?", "", text)
    CODEX_CONFIG.write_text(updated, encoding="utf-8")


def network_access_state(config_text: str) -> bool | None:
    section = re.search(
        r"(?ms)^\[sandbox_workspace_write\]\s*\n(.*?)(?=^\[|\Z)", config_text
    )
    if not section:
        return None

    line = re.search(r"(?m)^\s*network_access\s*=\s*(true|false)\s*$", section.group(1))
    if not line:
        return None
    return line.group(1) == "true"


def set_network_access_true(config_text: str) -> str:
    section = re.search(
        r"(?ms)^(\[sandbox_workspace_write\]\s*\n)(.*?)(?=^\[|\Z)", config_text
    )
    if not section:
        suffix = "" if not config_text or config_text.endswith("\n") else "\n"
        return f"{config_text}{suffix}{NETWORK_SECTION_HEADER}\n{NETWORK_LINE}\n"

    header, body = section.group(1), section.group(2)
    if re.search(r"(?m)^\s*network_access\s*=\s*(true|false)\s*$", body):
        new_body = re.sub(
            r"(?m)^\s*network_access\s*=\s*(true|false)\s*$",
            NETWORK_LINE,
            body,
            count=1,
        )
    else:
        separator = "" if not body or body.endswith("\n") else "\n"
        new_body = f"{body}{separator}{NETWORK_LINE}\n"

    return f"{config_text[:section.start()]}{header}{new_body}{config_text[section.end():]}"


def ensure_network_access_enabled() -> bool:
    if CODEX_CONFIG.exists():
        config_text = CODEX_CONFIG.read_text(encoding="utf-8")
    else:
        config_text = ""

    state = network_access_state(config_text)
    if state is True:
        return True

    print("Installation requires [sandbox_workspace_write] network_access = true.")
    if not confirm(f"Update {CODEX_CONFIG} to enable network access"):
        print("Install cancelled.")
        return False

    CODEX_HOME.mkdir(parents=True, exist_ok=True)
    updated = set_network_access_true(config_text)
    CODEX_CONFIG.write_text(updated, encoding="utf-8")
    print(f"Updated config: {CODEX_CONFIG}")
    return True


def prompt_telegram_credentials() -> tuple[str, str]:
    token = input("Telegram bot token: ").strip()
    chat_id = input("Telegram chat_id: ").strip()

    if not token or not chat_id:
        raise ValueError("Both token and chat_id are required.")

    return token, chat_id


def write_tokens_file(path: Path, token: str, chat_id: str) -> None:
    content = (
        "# Notification driver selector.\n"
        "# Supported value for now: telegram\n"
        "driver = 'telegram'\n"
        "\n"
        "[telegram]\n"
        "# Bot token from @BotFather, format: 123456:ABC...\n"
        f"token = '{token}'\n"
        "# Target chat/channel id, e.g. 123456789 or -1001234567890\n"
        f"chat_id = '{chat_id}'\n"
    )
    path.write_text(content, encoding="utf-8")


def install_hook(*, require_network_check: bool = True) -> int:
    if not SOURCE_HOOK.exists():
        print(f"Missing source hook: {SOURCE_HOOK}")
        return 1

    if require_network_check and not ensure_network_access_enabled():
        return 1

    CODEX_HOME.mkdir(parents=True, exist_ok=True)
    tokens_exists = INSTALLED_TOKENS.exists() or INSTALLED_TOKENS.is_symlink()

    if tokens_exists and not confirm(f"{INSTALLED_TOKENS} already exists. Overwrite"):
        token = ""
        chat_id = ""
        should_write_tokens = False
    else:
        try:
            token, chat_id = prompt_telegram_credentials()
        except ValueError as exc:
            print(f"Install cancelled: {exc}")
            return 1
        should_write_tokens = True

    shutil.copy2(SOURCE_HOOK, INSTALLED_HOOK)
    if should_write_tokens:
        write_tokens_file(INSTALLED_TOKENS, token, chat_id)

    set_notify_config()

    print(f"Installed hook: {INSTALLED_HOOK}")
    if should_write_tokens:
        print(f"Installed tokens file: {INSTALLED_TOKENS}")
    else:
        print(f"Kept existing tokens file: {INSTALLED_TOKENS}")
    print(f"Updated config: {CODEX_CONFIG}")
    return 0


def remove_hook() -> int:
    remove_notify_config()

    if INSTALLED_HOOK.exists() or INSTALLED_HOOK.is_symlink():
        INSTALLED_HOOK.unlink()
        print(f"Removed hook: {INSTALLED_HOOK}")

    if INSTALLED_TOKENS.exists() or INSTALLED_TOKENS.is_symlink():
        INSTALLED_TOKENS.unlink()
        print(f"Removed tokens file: {INSTALLED_TOKENS}")

    print(f"Updated config: {CODEX_CONFIG}")
    return 0


def status() -> int:
    config_text = CODEX_CONFIG.read_text(encoding="utf-8") if CODEX_CONFIG.exists() else ""
    network_state = network_access_state(config_text)
    notify_configured = bool(re.search(r"(?m)^\s*notify\s*=.*$", config_text))

    print(f"Config file: {CODEX_CONFIG} ({'exists' if CODEX_CONFIG.exists() else 'missing'})")
    print(f"Notify configured: {'yes' if notify_configured else 'no'}")
    if network_state is True:
        print("Sandbox network_access: true")
    elif network_state is False:
        print("Sandbox network_access: false")
    else:
        print("Sandbox network_access: not set")

    if INSTALLED_HOOK.is_symlink():
        print(f"Hook script: {INSTALLED_HOOK} (symlink)")
    elif INSTALLED_HOOK.exists():
        print(f"Hook script: {INSTALLED_HOOK} (file)")
    else:
        print(f"Hook script: {INSTALLED_HOOK} (missing)")

    if INSTALLED_TOKENS.is_symlink():
        print(f"Tokens file: {INSTALLED_TOKENS} (symlink)")
    elif INSTALLED_TOKENS.exists():
        print(f"Tokens file: {INSTALLED_TOKENS} (file)")
    else:
        print(f"Tokens file: {INSTALLED_TOKENS} (missing)")

    return 0


def onboarding() -> int:
    if not ensure_network_access_enabled():
        return 1

    try:
        import inquirer
    except ImportError:
        print("Onboarding requires 'inquirer'. Install it with: uv add inquirer")
        return 1

    questions = [
        inquirer.List(
            "driver",
            message="Choose a notification driver",
            choices=["telegram"],
            default="telegram",
        ),
        inquirer.Confirm(
            "install_now",
            message="Install hook into ~/.codex now?",
            default=True,
        ),
    ]
    answers = inquirer.prompt(questions) or {}

    driver = answers.get("driver")
    if driver != "telegram":
        print(f"Unsupported driver selected: {driver}")
        return 1

    if answers.get("install_now"):
        return install_hook(require_network_check=False)

    print("Run: uv run main.py install-hook")
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Codex notify helper CLI")
    parser.add_argument(
        "command",
        nargs="?",
        choices=["install-hook", "remove-hook", "status"],
        help="command to run",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])

    if args.command == "install-hook":
        return install_hook()
    if args.command == "remove-hook":
        return remove_hook()
    if args.command == "status":
        return status()
    return onboarding()


if __name__ == "__main__":
    raise SystemExit(main())
