#!/usr/bin/env python3
"""Codex notify CLI.

사용법:
    uv run main.py                 # 온보딩
    uv run main.py install-hook
    uv run main.py remove-hook
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Optional

import tomlkit

logger = logging.getLogger(__name__)
_last_logged_codex_home: Optional[str] = None

PROJECT_ROOT = Path(__file__).resolve().parent
SOURCE_HOOK = PROJECT_ROOT / "notify-hook.py"

def configure_logging() -> None:
    level_name = os.environ.get("CODEX_NOTIFY_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


def codex_home() -> Path:
    global _last_logged_codex_home

    override = os.environ.get("CODEX_HOME")
    if override:
        home = Path(override).expanduser()
    else:
        home = Path.home() / ".codex"

    if str(home) != _last_logged_codex_home:
        if override:
            logger.info("Using CODEX_HOME override: %s", home)
        else:
            logger.info("Using default CODEX_HOME: %s", home)
        _last_logged_codex_home = str(home)
    return home


def codex_config_path() -> Path:
    return codex_home() / "config.toml"


def installed_hook_path() -> Path:
    return codex_home() / "notify-hook.py"


def installed_tokens_path() -> Path:
    return codex_home() / "notify-hook-tokens.toml"


def notify_line() -> str:
    default_hook = Path.home() / ".codex" / "notify-hook.py"
    target_hook = installed_hook_path()
    if target_hook == default_hook:
        hook_path = "~/.codex/notify-hook.py"
    else:
        hook_path = target_hook.as_posix()
    return f'notify = ["python3", "{hook_path}"]'


def notify_value() -> list[str]:
    default_hook = Path.home() / ".codex" / "notify-hook.py"
    target_hook = installed_hook_path()
    if target_hook == default_hook:
        hook_path = "~/.codex/notify-hook.py"
    else:
        hook_path = target_hook.as_posix()
    return ["python3", hook_path]


def parse_toml_document(text: str) -> tomlkit.TOMLDocument:
    if not text.strip():
        return tomlkit.document()
    return tomlkit.parse(text)


def confirm(question: str) -> bool:
    answer = input(f"{question} (y/N): ").strip().lower()
    return answer in {"y", "yes"}


def set_notify_config() -> None:
    codex_home_path = codex_home()
    codex_config = codex_config_path()
    codex_home_path.mkdir(parents=True, exist_ok=True)

    if codex_config.exists():
        text = codex_config.read_text(encoding="utf-8")
    else:
        text = ""

    doc = parse_toml_document(text)
    if "notify" in doc:
        del doc["notify"]

    updated_doc = tomlkit.document()
    updated_doc.add("notify", notify_value())
    for key, value in doc.items():
        updated_doc.add(key, value)

    updated = tomlkit.dumps(updated_doc)

    codex_config.write_text(updated, encoding="utf-8")
    logger.info("Updated notify config in %s", codex_config)


def remove_notify_config() -> None:
    codex_config = codex_config_path()
    if not codex_config.exists():
        return

    text = codex_config.read_text(encoding="utf-8")
    doc = parse_toml_document(text)
    if "notify" in doc:
        del doc["notify"]
    updated = tomlkit.dumps(doc)
    codex_config.write_text(updated, encoding="utf-8")
    logger.info("Removed notify config from %s", codex_config)


def network_access_state(config_text: str) -> Optional[bool]:
    doc = parse_toml_document(config_text)
    section = doc.get("sandbox_workspace_write")
    if not isinstance(section, dict):
        return None

    value = section.get("network_access")
    if not isinstance(value, bool):
        return None
    return value


def set_network_access_true(config_text: str) -> str:
    doc = parse_toml_document(config_text)
    section = doc.get("sandbox_workspace_write")
    if isinstance(section, dict):
        section["network_access"] = True
    else:
        table = tomlkit.table()
        table.add("network_access", True)
        doc.add("sandbox_workspace_write", table)
    return tomlkit.dumps(doc)


def ensure_network_access_enabled() -> bool:
    codex_home_path = codex_home()
    codex_config = codex_config_path()
    if codex_config.exists():
        config_text = codex_config.read_text(encoding="utf-8")
    else:
        config_text = ""

    state = network_access_state(config_text)
    if state is True:
        return True

    print("설치를 위해 [sandbox_workspace_write] network_access = true 설정이 필요해요.")
    if not confirm(f"{codex_config} 파일에 네트워크 접근을 허용하도록 업데이트할까요"):
        print("설치를 취소했어요.")
        return False

    codex_home_path.mkdir(parents=True, exist_ok=True)
    updated = set_network_access_true(config_text)
    codex_config.write_text(updated, encoding="utf-8")
    print(f"설정 파일을 업데이트했어요: {codex_config}")
    logger.info("Enabled network_access in %s", codex_config)
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
    installed_hook = installed_hook_path()
    installed_tokens = installed_tokens_path()
    codex_home_path = codex_home()
    codex_config = codex_config_path()

    if not SOURCE_HOOK.exists():
        print(f"소스 훅 파일을 찾을 수 없어요: {SOURCE_HOOK}")
        return 1

    if require_network_check and not ensure_network_access_enabled():
        return 1

    codex_home_path.mkdir(parents=True, exist_ok=True)
    tokens_exists = installed_tokens.exists() or installed_tokens.is_symlink()

    if tokens_exists and no_overwrite:
        should_write_tokens = False
    elif tokens_exists and not confirm(f"{installed_tokens} 파일이 이미 존재해요. 덮어쓸까요"):
        should_write_tokens = False
    else:
        try:
            token, chat_id = prompt_telegram_credentials()
        except ValueError as exc:
            print(f"설치를 취소했어요: {exc}")
            return 1
        should_write_tokens = True

    shutil.copy2(SOURCE_HOOK, installed_hook)
    if should_write_tokens:
        write_tokens_file(installed_tokens, token, chat_id)

    set_notify_config()

    print(f"훅을 설치했어요: {installed_hook}")
    if should_write_tokens:
        print(f"토큰 파일을 설치했어요: {installed_tokens}")
    else:
        print(f"기존 토큰 파일을 그대로 유지했어요: {installed_tokens}")
    print(f"설정 파일을 업데이트했어요: {codex_config}")
    logger.info("Installed hook at %s", installed_hook)
    return 0


def remove_hook() -> int:
    installed_hook = installed_hook_path()
    installed_tokens = installed_tokens_path()
    codex_config = codex_config_path()

    remove_notify_config()

    if installed_hook.exists() or installed_hook.is_symlink():
        installed_hook.unlink()
        print(f"훅을 제거했어요: {installed_hook}")

    if installed_tokens.exists() or installed_tokens.is_symlink():
        installed_tokens.unlink()
        print(f"토큰 파일을 제거했어요: {installed_tokens}")

    print(f"설정 파일을 업데이트했어요: {codex_config}")
    logger.info("Removed hook artifacts under %s", codex_home())
    return 0


def status() -> int:
    codex_config = codex_config_path()
    installed_hook = installed_hook_path()
    installed_tokens = installed_tokens_path()

    config_text = codex_config.read_text(encoding="utf-8") if codex_config.exists() else ""
    network_state = network_access_state(config_text)
    doc = parse_toml_document(config_text)
    notify_configured = isinstance(doc.get("notify"), list)

    print(f"설정 파일: {codex_config} ({'존재함' if codex_config.exists() else '없음'})")
    print(f"알림 설정 여부: {'예' if notify_configured else '아니오'}")
    if network_state is True:
        print("샌드박스 network_access: true")
    elif network_state is False:
        print("샌드박스 network_access: false")
    else:
        print("샌드박스 network_access: 설정되지 않음")

    if installed_hook.is_symlink():
        print(f"훅 스크립트: {installed_hook} (심볼릭 링크)")
    elif installed_hook.exists():
        print(f"훅 스크립트: {installed_hook} (파일)")
    else:
        print(f"훅 스크립트: {installed_hook} (없음)")

    if installed_tokens.is_symlink():
        print(f"토큰 파일: {installed_tokens} (심볼릭 링크)")
    elif installed_tokens.exists():
        print(f"토큰 파일: {installed_tokens} (파일)")
    else:
        print(f"토큰 파일: {installed_tokens} (없음)")

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
    configure_logging()
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
