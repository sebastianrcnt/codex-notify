#!/usr/bin/env python3
"""Codex notify CLI.

사용법:
    uv run main.py                 # 온보딩
    uv run main.py install-hook
    uv run main.py remove-hook
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path
from typing import Optional

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


def network_access_state(config_text: str) -> Optional[bool]:
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

    print("설치를 위해 [sandbox_workspace_write] network_access = true 설정이 필요해요.")
    if not confirm(f"{CODEX_CONFIG} 파일에 네트워크 접근을 허용하도록 업데이트할까요"):
        print("설치를 취소했어요.")
        return False

    CODEX_HOME.mkdir(parents=True, exist_ok=True)
    updated = set_network_access_true(config_text)
    CODEX_CONFIG.write_text(updated, encoding="utf-8")
    print(f"설정 파일을 업데이트했어요: {CODEX_CONFIG}")
    return True


def prompt_telegram_credentials() -> tuple[str, str]:
    token = input("텔레그램 봇 토큰을 입력해 주세요: ").strip()
    chat_id = input("텔레그램 chat_id를 입력해 주세요: ").strip()

    if not token or not chat_id:
        raise ValueError("토큰과 chat_id는 모두 필수예요.")

    return token, chat_id


def write_tokens_file(path: Path, token: str, chat_id: str) -> None:
    content = (
        "# 알림 드라이버 선택.\n"
        "# 현재 지원되는 값: telegram\n"
        "driver = 'telegram'\n"
        "\n"
        "[telegram]\n"
        "# @BotFather에서 발급받은 봇 토큰, 형식: 123456:ABC...\n"
        f"token = '{token}'\n"
        "# 대상 채팅/채널 id, 예: 123456789 또는 -1001234567890\n"
        f"chat_id = '{chat_id}'\n"
    )
    path.write_text(content, encoding="utf-8")


def install_hook(*, require_network_check: bool = True, no_overwrite: bool = False) -> int:
    if not SOURCE_HOOK.exists():
        print(f"소스 훅 파일을 찾을 수 없어요: {SOURCE_HOOK}")
        return 1

    if require_network_check and not ensure_network_access_enabled():
        return 1

    CODEX_HOME.mkdir(parents=True, exist_ok=True)
    tokens_exists = INSTALLED_TOKENS.exists() or INSTALLED_TOKENS.is_symlink()

    if tokens_exists and no_overwrite:
        should_write_tokens = False
    elif tokens_exists and not confirm(f"{INSTALLED_TOKENS} 파일이 이미 존재해요. 덮어쓸까요"):
        should_write_tokens = False
    else:
        try:
            token, chat_id = prompt_telegram_credentials()
        except ValueError as exc:
            print(f"설치를 취소했어요: {exc}")
            return 1
        should_write_tokens = True

    shutil.copy2(SOURCE_HOOK, INSTALLED_HOOK)
    if should_write_tokens:
        write_tokens_file(INSTALLED_TOKENS, token, chat_id)

    set_notify_config()

    print(f"훅을 설치했어요: {INSTALLED_HOOK}")
    if should_write_tokens:
        print(f"토큰 파일을 설치했어요: {INSTALLED_TOKENS}")
    else:
        print(f"기존 토큰 파일을 그대로 유지했어요: {INSTALLED_TOKENS}")
    print(f"설정 파일을 업데이트했어요: {CODEX_CONFIG}")
    return 0


def remove_hook() -> int:
    remove_notify_config()

    if INSTALLED_HOOK.exists() or INSTALLED_HOOK.is_symlink():
        INSTALLED_HOOK.unlink()
        print(f"훅을 제거했어요: {INSTALLED_HOOK}")

    if INSTALLED_TOKENS.exists() or INSTALLED_TOKENS.is_symlink():
        INSTALLED_TOKENS.unlink()
        print(f"토큰 파일을 제거했어요: {INSTALLED_TOKENS}")

    print(f"설정 파일을 업데이트했어요: {CODEX_CONFIG}")
    return 0


def status() -> int:
    config_text = CODEX_CONFIG.read_text(encoding="utf-8") if CODEX_CONFIG.exists() else ""
    network_state = network_access_state(config_text)
    notify_configured = bool(re.search(r"(?m)^\s*notify\s*=.*$", config_text))

    print(f"설정 파일: {CODEX_CONFIG} ({'존재함' if CODEX_CONFIG.exists() else '없음'})")
    print(f"알림 설정 여부: {'예' if notify_configured else '아니오'}")
    if network_state is True:
        print("샌드박스 network_access: true")
    elif network_state is False:
        print("샌드박스 network_access: false")
    else:
        print("샌드박스 network_access: 설정되지 않음")

    if INSTALLED_HOOK.is_symlink():
        print(f"훅 스크립트: {INSTALLED_HOOK} (심볼릭 링크)")
    elif INSTALLED_HOOK.exists():
        print(f"훅 스크립트: {INSTALLED_HOOK} (파일)")
    else:
        print(f"훅 스크립트: {INSTALLED_HOOK} (없음)")

    if INSTALLED_TOKENS.is_symlink():
        print(f"토큰 파일: {INSTALLED_TOKENS} (심볼릭 링크)")
    elif INSTALLED_TOKENS.exists():
        print(f"토큰 파일: {INSTALLED_TOKENS} (파일)")
    else:
        print(f"토큰 파일: {INSTALLED_TOKENS} (없음)")

    return 0


def onboarding() -> int:
    if not ensure_network_access_enabled():
        return 1

    try:
        import inquirer
    except ImportError:
        print("온보딩을 사용하려면 'inquirer'가 필요해요. 설치하려면: uv add inquirer")
        return 1

    questions = [
        inquirer.List(
            "driver",
            message="알림 드라이버를 선택해 주세요",
            choices=["telegram"],
            default="telegram",
        ),
        inquirer.Confirm(
            "install_now",
            message="지금 바로 ~/.codex에 훅을 설치할까요?",
            default=True,
        ),
    ]
    answers = inquirer.prompt(questions) or {}

    driver = answers.get("driver")
    if driver != "telegram":
        print(f"지원하지 않는 드라이버예요: {driver}")
        return 1

    if answers.get("install_now"):
        return install_hook(require_network_check=False)

    print("다음 명령으로 설치할 수 있어요: uv run main.py install-hook")
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Codex notify 헬퍼 CLI")
    parser.add_argument(
        "command",
        nargs="?",
        choices=["install-hook", "remove-hook", "status"],
        help="실행할 명령",
    )
    parser.add_argument(
        "--no-overwrite",
        action="store_true",
        help="기존 ~/.codex/notify-hook-tokens.toml 파일을 덮어쓰지 않아요",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv or sys.argv[1:])

    if args.command == "install-hook":
        return install_hook(no_overwrite=args.no_overwrite)
    if args.command == "remove-hook":
        return remove_hook()
    if args.command == "status":
        return status()
    return onboarding()


if __name__ == "__main__":
    raise SystemExit(main())
