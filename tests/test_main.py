import importlib.util
import logging
from pathlib import Path

import pytest
try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib

EXAMPLE_CODEX_CONFIG = """personality = \"pragmatic\"\nmodel = \"gpt-5.3-codex\"\nmodel_reasoning_effort = \"medium\"\n\n[projects.\"/Users/coolguy/dev/codex-notify\"]\ntrust_level = \"trusted\"\n\n[sandbox_workspace_write]\nnetwork_access = true\n"""


@pytest.fixture(autouse=True)
def isolated_codex_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "custom-codex-home"
    monkeypatch.setenv("CODEX_HOME", str(home))
    return home


@pytest.fixture
def app(isolated_codex_home: Path):
    module_path = Path(__file__).resolve().parents[1] / "main.py"
    spec = importlib.util.spec_from_file_location("codex_notify_main", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._last_logged_codex_home = None
    return module


def test_codex_home_uses_env_override_and_logs(
    app, caplog: pytest.LogCaptureFixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    caplog.set_level(logging.INFO)
    override = tmp_path / "override-home"
    monkeypatch.setenv("CODEX_HOME", str(override))
    app._last_logged_codex_home = None

    actual = app.codex_home()

    assert actual == override
    assert any("Using CODEX_HOME override" in record.message for record in caplog.records)


def test_notify_line_uses_overridden_home(app) -> None:
    line = app.notify_line()
    assert line.startswith('notify = ["python3", "')
    assert str(app.installed_hook_path()) in line


def test_set_notify_config_inserts_notify_at_root_top(app, isolated_codex_home: Path) -> None:
    config = app.codex_config_path()
    isolated_codex_home.mkdir(parents=True, exist_ok=True)
    config.write_text(EXAMPLE_CODEX_CONFIG, encoding="utf-8")

    app.set_notify_config()

    updated = config.read_text(encoding="utf-8")
    first_line = updated.splitlines()[0]
    assert first_line == app.notify_line()
    assert "[projects.\"/Users/coolguy/dev/codex-notify\"]" in updated
    assert "[sandbox_workspace_write]" in updated


def test_set_notify_config_keeps_notify_at_root_before_first_section(app, isolated_codex_home: Path) -> None:
    config = app.codex_config_path()
    isolated_codex_home.mkdir(parents=True, exist_ok=True)
    config.write_text(EXAMPLE_CODEX_CONFIG, encoding="utf-8")

    app.set_notify_config()

    updated = config.read_text(encoding="utf-8")
    parsed = tomllib.loads(updated)
    first_section_index = updated.find("[")
    first_notify_index = updated.find("notify =")

    assert "notify" in parsed
    assert isinstance(parsed["notify"], list)
    assert first_notify_index != -1
    assert first_section_index != -1
    assert first_notify_index < first_section_index


def test_set_notify_config_replaces_root_notify_only(app, isolated_codex_home: Path) -> None:
    config = app.codex_config_path()
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        "notify = ['python3', '/tmp/old.py']\n\n[projects.\"x\"]\nnotify = ['python3', '/tmp/section.py']\n",
        encoding="utf-8",
    )

    app.set_notify_config()

    updated = config.read_text(encoding="utf-8")
    assert updated.splitlines()[0] == app.notify_line()
    assert "notify = ['python3', '/tmp/section.py']" in updated


def test_remove_notify_config_removes_root_notify_only(app, isolated_codex_home: Path) -> None:
    config = app.codex_config_path()
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(
        f"{app.notify_line()}\nmodel = 'x'\n\n[projects.\"x\"]\nnotify = ['python3', '/tmp/section.py']\n",
        encoding="utf-8",
    )

    app.remove_notify_config()

    updated = config.read_text(encoding="utf-8")
    assert app.notify_line() not in updated
    assert "notify = ['python3', '/tmp/section.py']" in updated


def test_network_access_state_variants(app) -> None:
    assert app.network_access_state("[sandbox_workspace_write]\nnetwork_access = true\n") is True
    assert app.network_access_state("[sandbox_workspace_write]\nnetwork_access = false\n") is False
    assert app.network_access_state("[projects.\"x\"]\ntrust_level = \"trusted\"\n") is None


def test_set_network_access_true_adds_missing_section(app) -> None:
    updated = app.set_network_access_true("model = \"x\"\n")
    assert "[sandbox_workspace_write]" in updated
    assert "network_access = true" in updated


def test_set_network_access_true_updates_existing_false(app) -> None:
    updated = app.set_network_access_true("[sandbox_workspace_write]\nnetwork_access = false\n")
    assert "network_access = true" in updated
    assert "network_access = false" not in updated


def test_ensure_network_access_enabled_without_prompt_when_already_true(
    app, isolated_codex_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = app.codex_config_path()
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("[sandbox_workspace_write]\nnetwork_access = true\n", encoding="utf-8")

    def fail_confirm(_: str) -> bool:
        raise AssertionError("confirm should not be called")

    monkeypatch.setattr(app, "confirm", fail_confirm)
    assert app.ensure_network_access_enabled() is True


def test_ensure_network_access_enabled_updates_after_confirm(
    app, isolated_codex_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = app.codex_config_path()
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("model = \"x\"\n", encoding="utf-8")
    monkeypatch.setattr(app, "confirm", lambda _: True)

    assert app.ensure_network_access_enabled() is True
    assert "network_access = true" in config.read_text(encoding="utf-8")


def test_install_hook_with_no_overwrite_keeps_existing_tokens(
    app, isolated_codex_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_hook = isolated_codex_home / "source-notify-hook.py"
    source_hook.parent.mkdir(parents=True, exist_ok=True)
    source_hook.write_text("print('hook')\n", encoding="utf-8")
    monkeypatch.setattr(app, "SOURCE_HOOK", source_hook)

    tokens = app.installed_tokens_path()
    tokens.parent.mkdir(parents=True, exist_ok=True)
    tokens.write_text("driver = 'telegram'\n", encoding="utf-8")

    monkeypatch.setattr(app, "prompt_telegram_credentials", lambda: (_ for _ in ()).throw(AssertionError("prompt should not be called")))

    rc = app.install_hook(require_network_check=False, no_overwrite=True)

    assert rc == 0
    assert app.installed_hook_path().exists()
    assert tokens.read_text(encoding="utf-8") == "driver = 'telegram'\n"
    assert app.codex_config_path().read_text(encoding="utf-8").splitlines()[0] == app.notify_line()


def test_install_hook_returns_error_when_source_missing(app, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app, "SOURCE_HOOK", tmp_path / "does-not-exist.py")
    assert app.install_hook(require_network_check=False) == 1


def test_remove_hook_deletes_files_and_notify_config(app, isolated_codex_home: Path) -> None:
    hook = app.installed_hook_path()
    tokens = app.installed_tokens_path()
    config = app.codex_config_path()

    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("print('hook')\n", encoding="utf-8")
    tokens.write_text("driver = 'telegram'\n", encoding="utf-8")
    config.write_text(f"{app.notify_line()}\n{EXAMPLE_CODEX_CONFIG}", encoding="utf-8")

    rc = app.remove_hook()

    assert rc == 0
    assert not hook.exists()
    assert not tokens.exists()
    assert app.notify_line() not in config.read_text(encoding="utf-8")


def test_status_reports_current_state(app, isolated_codex_home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    hook = app.installed_hook_path()
    tokens = app.installed_tokens_path()
    config = app.codex_config_path()

    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("print('hook')\n", encoding="utf-8")
    tokens.write_text("driver = 'telegram'\n", encoding="utf-8")
    config.write_text(f"{app.notify_line()}\n[sandbox_workspace_write]\nnetwork_access = true\n", encoding="utf-8")

    rc = app.status()
    output = capsys.readouterr().out

    assert rc == 0
    assert "알림 설정 여부: 예" in output
    assert "샌드박스 network_access: true" in output
    assert "훅 스크립트:" in output
    assert "토큰 파일:" in output
