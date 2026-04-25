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
def app() -> main_module:
    module_path = Path(__file__).resolve().parents[1] / "main.py"
    spec = importlib.util.spec_from_file_location("codex_notify_main", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.LAST_LOGGED_CODEX_HOME = None
    return module


def test_notify_value_uses_active_python(app) -> None:
    values = app.notify_value()
    assert values[0] == str(Path(sys.executable).resolve())
    assert values[1] == str(app.installed_hook_path())


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
    assert "/tmp/old.py" not in updated
    assert "/tmp/section.py" in updated
    assert str(app.installed_hook_path()) in updated


def test_set_notify_config_noninteractive_fails_for_foreign_notify(app) -> None:
    config = app.codex_config_path()
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("notify = ['python3', '/tmp/foreign.py']\n", encoding="utf-8")

    with pytest.raises(RuntimeError):
        app.set_notify_config(interactive=False, force=False)


def test_set_notify_config_creates_backup(app) -> None:
    config = app.codex_config_path()
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("model = 'x'\n", encoding="utf-8")

    app.set_notify_config(interactive=True, force=True)

    backups = list(config.parent.glob("config.toml.bak.*"))
    assert len(backups) == 1


def test_install_keeps_existing_credentials(app, monkeypatch: pytest.MonkeyPatch) -> None:
    source = app.codex_home() / "source-notify-hook.py"
    source.write_text("print('ok')\n", encoding="utf-8")
    monkeypatch.setattr(app, "SOURCE_HOOK", source)

    token_file = app.installed_tokens_path()
    token_file.parent.mkdir(parents=True, exist_ok=True)
    original = "driver='telegram'\n[telegram]\ntoken='oldtok'\nchat_id='1234'\n"
    token_file.write_text(original, encoding="utf-8")
    token_file.chmod(0o644)

    monkeypatch.setattr(app, "prompt_telegram_credentials", lambda: (_ for _ in ()).throw(AssertionError("must not prompt")))
    rc = app.install(interactive=False, force=True)

    assert rc == 0
    assert token_file.read_text(encoding="utf-8") == original
    assert token_file.stat().st_mode & 0o077 == 0


def test_install_creates_credentials_when_missing(app, monkeypatch: pytest.MonkeyPatch) -> None:
    source = app.codex_home() / "source-notify-hook.py"
    source.write_text("print('ok')\n", encoding="utf-8")
    monkeypatch.setattr(app, "SOURCE_HOOK", source)
    monkeypatch.setattr(app, "prompt_telegram_credentials", lambda: ("tok123456:AAAA", "123456789"))

    rc = app.install(interactive=True, force=True)

    assert rc == 0
    assert app.installed_tokens_path().exists()
    assert app.installed_tokens_path().stat().st_mode & 0o077 == 0


def test_update_does_not_change_credentials(app, monkeypatch: pytest.MonkeyPatch) -> None:
    source = app.codex_home() / "source-notify-hook.py"
    source.write_text("print('new')\n", encoding="utf-8")
    monkeypatch.setattr(app, "SOURCE_HOOK", source)

    token_file = app.installed_tokens_path()
    token_file.parent.mkdir(parents=True, exist_ok=True)
    original = "driver='telegram'\n[telegram]\ntoken='keep'\nchat_id='9999'\n"
    token_file.write_text(original, encoding="utf-8")

    rc = app.update(interactive=False, force=True)
    assert rc == 0
    assert token_file.read_text(encoding="utf-8") == original


def test_reconfigure_updates_credentials_only(app, monkeypatch: pytest.MonkeyPatch) -> None:
    token_file = app.installed_tokens_path()
    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text("driver='telegram'\n[telegram]\ntoken='old'\nchat_id='1'\n", encoding="utf-8")
    monkeypatch.setattr(app, "prompt_telegram_credentials", lambda: ("newtok123456:ABCD", "98765"))

    rc = app.reconfigure(interactive=True, force=True)
    assert rc == 0
    updated = token_file.read_text(encoding="utf-8")
    assert "newtok123456:ABCD" in updated
    assert "98765" in updated


def test_install_without_force_noninteractive_fails_on_symlink_hook(app, monkeypatch: pytest.MonkeyPatch) -> None:
    source = app.codex_home() / "source-notify-hook.py"
    source.write_text("print('ok')\n", encoding="utf-8")
    monkeypatch.setattr(app, "SOURCE_HOOK", source)

    hook = app.installed_hook_path()
    hook.parent.mkdir(parents=True, exist_ok=True)
    real_target = hook.parent / "real.py"
    real_target.write_text("print('real')\n")
    hook.symlink_to(real_target)

    result = app.install(interactive=False, force=False)
    assert result == 1


def test_uninstall_keeps_credential_by_default(app) -> None:
    hook = app.installed_hook_path()
    token = app.installed_tokens_path()
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("print('hook')\n")
    token.write_text("driver = 'telegram'\n", encoding="utf-8")

    app.uninstall(interactive=False, force=False, delete_credentials=False)

    assert not hook.exists()
    assert token.exists()


def test_uninstall_deletes_credentials_with_flag(app) -> None:
    token = app.installed_tokens_path()
    token.parent.mkdir(parents=True, exist_ok=True)
    token.write_text("driver='telegram'\n", encoding="utf-8")
    app.uninstall(interactive=False, force=False, delete_credentials=True)
    assert not token.exists()


def test_alias_parsing_and_new_commands(app) -> None:
    assert app._parse_args(["install-hook"]).command == "install-hook"
    assert app._parse_args(["remove-hook"]).command == "remove-hook"
    assert app._parse_args(["update"]).command == "update"
    assert app._parse_args(["reconfigure"]).command == "reconfigure"
    uninstall = app._parse_args(["uninstall", "--delete-credentials"])
    assert uninstall.command == "uninstall"
    assert uninstall.delete_credentials is True


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
    assert "123456...ABCD" in output


def test_token_permission_safety_function(app) -> None:
    token = app.installed_tokens_path()
    token.parent.mkdir(parents=True, exist_ok=True)
    token.write_text("driver='telegram'\n", encoding="utf-8")
    token.chmod(0o644)
    assert app.is_token_permissions_safe(token) is False
    token.chmod(0o600)
    assert app.is_token_permissions_safe(token) is True
