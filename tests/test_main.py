from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

import main as main_module


@pytest.fixture(autouse=True)
def isolated_codex_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    home = tmp_path / "custom-codex-home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.delenv("CODEX_NOTIFY_BOT_TOKEN", raising=False)
    monkeypatch.delenv("CODEX_NOTIFY_CHAT_ID", raising=False)
    monkeypatch.delenv("CODEX_NOTIFY_INCLUDE_BODY", raising=False)
    monkeypatch.delenv("CODEX_NOTIFY_DEBUG", raising=False)
    home.mkdir(parents=True, exist_ok=True)
    main_module.LAST_LOGGED_CODEX_HOME = None
    return home


@pytest.fixture
def app(isolated_codex_home: Path) -> main_module:
    module_path = Path(__file__).resolve().parents[1] / "main.py"
    spec = importlib.util.spec_from_file_location("codex_notify_main", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.LAST_LOGGED_CODEX_HOME = None
    return module


def test_notify_line_uses_active_python(app) -> None:
    line = app.notify_line()
    assert 'notify = ["' in line
    assert str(Path(sys.executable).resolve()) in line


def test_set_notify_config_replaces_root_notify_without_duplication(app, monkeypatch: pytest.MonkeyPatch) -> None:
    config = app.codex_config_path()
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        "notify = ['python3', '/tmp/old.py']\n\n[projects.\"x\"]\nnotify = ['python3', '/tmp/section.py']\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(app, "confirm", lambda *_a, **_kw: True)
    app.set_notify_config(interactive=True, force=True)

    updated = config.read_text(encoding="utf-8")
    assert updated.startswith("notify = [")
    assert "/tmp/section.py" in updated
    assert "/tmp/old.py" not in updated


def test_set_notify_config_creates_backup(app) -> None:
    config = app.codex_config_path()
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("model = 'x'\n", encoding="utf-8")

    app.set_notify_config(interactive=True, force=True)

    backups = list(config.parent.glob("config.toml.bak.*"))
    assert len(backups) == 1


def test_install_writes_hook_and_tokens_and_backup_config(app, monkeypatch: pytest.MonkeyPatch) -> None:
    source = app.codex_home() / "source-notify-hook.py"
    source.write_text("print('ok')\n", encoding="utf-8")
    monkeypatch.setattr(app, "SOURCE_HOOK", source)

    config = app.codex_config_path()
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("model = 'x'\n", encoding="utf-8")

    monkeypatch.setattr(app, "prompt_telegram_credentials", lambda: ("tok123456:AAAA", "123456789"))

    rc = app.install(no_overwrite=False, interactive=True, force=True)

    assert rc == 0
    assert app.installed_hook_path().exists()
    assert app.installed_tokens_path().exists()
    assert app.installed_hook_path().stat().st_mode & 0o111 != 0
    assert app.installed_tokens_path().stat().st_mode & 0o077 == 0
    assert app.codex_config_path().exists()
    assert len(list(app.codex_config_path().parent.glob("config.toml.bak.*"))) == 1


def test_install_without_force_noninteractive_fails_on_symlink_hook(app, monkeypatch: pytest.MonkeyPatch) -> None:
    source = app.codex_home() / "source-notify-hook.py"
    source.write_text("print('ok')\n", encoding="utf-8")
    monkeypatch.setattr(app, "SOURCE_HOOK", source)

    hook = app.installed_hook_path()
    hook.parent.mkdir(parents=True, exist_ok=True)
    real_target = hook.parent / "real.py"
    real_target.write_text("print('real')\n")
    hook.symlink_to(real_target)

    result = app.install_hook(interactive=False, force=False)
    assert result == 1


def test_install_allows_symlink_with_confirmation_interactive(app, monkeypatch: pytest.MonkeyPatch) -> None:
    source = app.codex_home() / "source-notify-hook.py"
    source.write_text("print('ok')\n", encoding="utf-8")
    monkeypatch.setattr(app, "SOURCE_HOOK", source)

    hook = app.installed_hook_path()
    hook.parent.mkdir(parents=True, exist_ok=True)
    real_target = hook.parent / "real.py"
    real_target.write_text("print('real')\n")
    hook.symlink_to(real_target)
    monkeypatch.setattr(app, "prompt_telegram_credentials", lambda: ("tok123456:AAAA", "123"))
    monkeypatch.setattr(app, "confirm", lambda *_a, **_kw: True)

    result = app.install_hook(interactive=True, force=False)
    assert result == 0
    assert not hook.is_symlink()


def test_uninstall_keeps_token_by_default(app) -> None:
    hook = app.installed_hook_path()
    token = app.installed_tokens_path()
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("print('hook')\n")
    token.write_text("driver = 'telegram'\n")

    app.remove_hook(interactive=False, force=False)

    assert not hook.exists()
    assert token.exists()

def test_uninstall_alias_parses(app) -> None:
    namespace = app._parse_args(["remove-hook"])
    assert namespace.command == "remove-hook"
    namespace = app._parse_args(["install-hook", "--no-overwrite"])
    assert namespace.command == "install-hook"


def test_status_and_doctor_do_not_leak_tokens(app, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    token_file = app.installed_tokens_path()
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(
        "driver = 'telegram'\n[telegram]\ntoken='123456:ABCD'\nchat_id='7777'\n",
        encoding="utf-8",
    )

    fake_module = type("Hook", (), {"send_notification": lambda *args, **kwargs: None})
    monkeypatch.setattr(app, "_load_hook_module", lambda: fake_module())

    app.status()
    output = capsys.readouterr().out
    assert "123456:ABCD" not in output
    assert "7777" not in output

    app.doctor(no_network=True)
    output = capsys.readouterr().out
    assert "123456:ABCD" not in output
    assert "7777" not in output


def test_token_permission_safety_function(app) -> None:
    token = app.installed_tokens_path()
    token.parent.mkdir(parents=True, exist_ok=True)
    token.write_text("driver='telegram'\n", encoding="utf-8")
    token.chmod(0o644)
    assert app.is_token_permissions_safe(token) is False
    token.chmod(0o600)
    assert app.is_token_permissions_safe(token) is True


def test_install_command_aliases_are_registered(app) -> None:
    args = app._parse_args(["install"])
    assert args.command == "install"
    args = app._parse_args(["install-hook"])
    assert args.command == "install-hook"
