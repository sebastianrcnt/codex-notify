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
SOURCE_TOKENS = PROJECT_ROOT / "notify-hook-tokens.toml"

NOTIFY_LINE = "notify = ['python3', '~/.codex/notify-hook.py']"


def confirm_overwrite(path: Path) -> bool:
    answer = input(f"{path} already exists. Overwrite? (y/N): ").strip().lower()
    return answer in {"y", "yes"}


def set_notify_config() -> None:
    CODEX_HOME.mkdir(parents=True, exist_ok=True)

    if CODEX_CONFIG.exists():
        text = CODEX_CONFIG.read_text(encoding="utf-8")
    else:
        text = ""

    if re.search(r"(?m)^\\s*notify\\s*=.*$", text):
        updated = re.sub(r"(?m)^\\s*notify\\s*=.*$", NOTIFY_LINE, text, count=1)
    else:
        suffix = "" if not text or text.endswith("\n") else "\n"
        updated = f"{text}{suffix}{NOTIFY_LINE}\n"

    CODEX_CONFIG.write_text(updated, encoding="utf-8")


def remove_notify_config() -> None:
    if not CODEX_CONFIG.exists():
        return

    text = CODEX_CONFIG.read_text(encoding="utf-8")
    updated = re.sub(r"(?m)^\\s*notify\\s*=.*$\\n?", "", text)
    CODEX_CONFIG.write_text(updated, encoding="utf-8")


def install_hook() -> int:
    if not SOURCE_HOOK.exists():
        print(f"Missing source hook: {SOURCE_HOOK}")
        return 1
    if not SOURCE_TOKENS.exists():
        print(f"Missing source tokens file: {SOURCE_TOKENS}")
        return 1

    CODEX_HOME.mkdir(parents=True, exist_ok=True)

    if (INSTALLED_HOOK.exists() or INSTALLED_HOOK.is_symlink()) and not confirm_overwrite(
        INSTALLED_HOOK
    ):
        print("Install cancelled.")
        return 1

    if (
        INSTALLED_TOKENS.exists() or INSTALLED_TOKENS.is_symlink()
    ) and not confirm_overwrite(INSTALLED_TOKENS):
        print("Install cancelled.")
        return 1

    shutil.copy2(SOURCE_HOOK, INSTALLED_HOOK)
    shutil.copy2(SOURCE_TOKENS, INSTALLED_TOKENS)

    set_notify_config()

    print(f"Installed hook: {INSTALLED_HOOK}")
    print(f"Installed tokens template: {INSTALLED_TOKENS}")
    print(f"Updated config: {CODEX_CONFIG}")
    print("Edit ~/.codex/notify-hook-tokens.toml with real credentials.")
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


def onboarding() -> int:
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
        return install_hook()

    print("Run: uv run main.py install-hook")
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Codex notify helper CLI")
    parser.add_argument(
        "command",
        nargs="?",
        choices=["install-hook", "remove-hook"],
        help="command to run",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])

    if args.command == "install-hook":
        return install_hook()
    if args.command == "remove-hook":
        return remove_hook()
    return onboarding()


if __name__ == "__main__":
    raise SystemExit(main())
