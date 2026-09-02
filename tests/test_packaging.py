"""Packaging support: metadata, paths, resources, logging and start-up errors.

These test the *logic* packaging depends on. Whether a PyInstaller bundle
actually runs is proved by the real smoke test (`--smoke-test`) in
`packaging/build.py`, not by anything here - a unit test cannot verify a frozen
binary.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

import pytest

from human_input_automation import __version__
from human_input_automation.logging_setup import (
    LOG_FILENAME,
    RedactingFilter,
    configure_logging,
)
from human_input_automation.metadata import METADATA, ApplicationMetadata
from human_input_automation.paths import (
    ApplicationPaths,
    bundle_directory,
    is_frozen,
    resource_path,
    user_data_directory,
    user_log_directory,
)
from human_input_automation.startup import (
    MISSING_GUI,
    NO_DISPLAY,
    data_directory_problem,
    has_display,
    qt_plugin_problem,
)

ROOT = Path(__file__).resolve().parents[1]


# -- metadata -------------------------------------------------------------
def test_the_version_has_one_source_of_truth() -> None:
    """pyproject.toml and the package must never disagree."""
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version = "([^"]+)"', text, re.MULTILINE)
    assert match is not None
    assert match.group(1) == __version__ == METADATA.version


def test_metadata_is_complete() -> None:
    for field in ("name", "slug", "identifier", "version", "description", "publisher"):
        assert getattr(METADATA, field), f"{field} must not be empty"
    assert "." in METADATA.identifier, "the bundle identifier should be reverse-DNS"
    assert " " not in METADATA.slug and " " not in METADATA.executable


def test_artifact_names_state_the_architecture_they_were_built_for() -> None:
    metadata = ApplicationMetadata(version="1.2.3")
    assert (
        metadata.artifact_name("linux", "x86_64", ".AppImage")
        == "HumanInputAutomation-1.2.3-linux-x86_64.AppImage"
    )
    assert metadata.artifact_name("macos", "arm64", ".dmg").endswith("-macos-arm64.dmg")


# -- resources ------------------------------------------------------------
def test_the_application_icon_is_shipped_in_the_package() -> None:
    icons = ROOT / "src" / "human_input_automation" / "resources" / "icons"
    for name in ("app.png", "app.ico", "app.icns"):
        path = icons / name
        assert path.is_file(), f"{name} is missing"
        assert path.stat().st_size > 0


def test_resource_lookup_uses_the_package_directory_when_not_frozen() -> None:
    assert not is_frozen()
    assert bundle_directory().name == "human_input_automation"
    assert resource_path("resources", "icons", "app.png").is_file()


def test_resource_lookup_follows_meipass_when_frozen(monkeypatch: pytest.MonkeyPatch) -> None:
    """A bundle keeps the package-relative layout under sys._MEIPASS."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", "/tmp/bundle", raising=False)
    assert is_frozen()
    assert bundle_directory() == Path("/tmp/bundle/human_input_automation")
    assert resource_path("resources", "icons", "app.png") == Path(
        "/tmp/bundle/human_input_automation/resources/icons/app.png"
    )


# -- user directories -----------------------------------------------------
@pytest.mark.parametrize(
    ("platform_id", "env", "expected"),
    [
        ("win32", {"APPDATA": "C:/Users/x/AppData/Roaming"}, "AppData/Roaming"),
        ("darwin", {}, "Library/Application Support"),
        ("linux", {"XDG_DATA_HOME": "/custom"}, "custom"),
        ("linux", {}, ".local/share"),
    ],
)
def test_data_directory_follows_platform_conventions(
    platform_id: str, env: dict[str, str], expected: str
) -> None:
    path = user_data_directory(platform_id, env, home=Path("/home/tester"))
    assert expected in path.as_posix()
    assert path.name == "human-input-automation"


@pytest.mark.parametrize(
    ("platform_id", "env", "expected"),
    [
        ("darwin", {}, "Library/Logs"),
        ("linux", {"XDG_STATE_HOME": "/state"}, "/state"),
        ("linux", {}, ".local/state"),
        ("win32", {"APPDATA": "C:/Users/x/AppData/Roaming"}, "AppData/Roaming"),
    ],
)
def test_log_directory_follows_platform_conventions(
    platform_id: str, env: dict[str, str], expected: str
) -> None:
    path = user_log_directory(platform_id, env, home=Path("/home/tester"))
    assert expected in path.as_posix()


def test_user_data_never_lives_in_the_installation_directory() -> None:
    """An installed application may sit in a read-only location."""
    paths = ApplicationPaths.for_host(
        "linux", {"XDG_DATA_HOME": "/home/t/.local/share"}, Path("/home/t")
    )
    assert ROOT not in paths.data.parents
    assert bundle_directory() not in paths.profiles.parents


def test_first_run_creates_the_directories_once(tmp_path: Path) -> None:
    paths = ApplicationPaths(
        data=tmp_path / "data", profiles=tmp_path / "data" / "profiles", logs=tmp_path / "logs"
    )
    assert paths.is_first_run
    created = paths.ensure()
    assert set(created) == {paths.data, paths.profiles, paths.logs}
    assert all(path.is_dir() for path in created)

    assert paths.ensure() == (), "a second run creates nothing"
    assert paths.is_first_run, "still first run until it is marked"
    paths.mark_initialised()
    assert not paths.is_first_run


def test_an_unwritable_data_directory_raises_rather_than_losing_profiles(tmp_path: Path) -> None:
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory", encoding="utf-8")
    paths = ApplicationPaths(data=blocker / "data", profiles=blocker / "p", logs=blocker / "l")
    with pytest.raises(OSError):
        paths.ensure()


# -- logging --------------------------------------------------------------
def test_logging_writes_a_rotating_file(tmp_path: Path) -> None:
    path = configure_logging(log_directory=tmp_path)
    assert path is not None and path.name == LOG_FILENAME
    logging.getLogger("test").warning("hello from the test")
    for handler in logging.getLogger().handlers:
        handler.flush()
    assert "hello from the test" in path.read_text(encoding="utf-8")
    configure_logging(to_file=False)


def test_logging_survives_an_unwritable_directory(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    assert configure_logging(log_directory=blocker / "logs") is None
    configure_logging(to_file=False)


@pytest.mark.parametrize(
    ("message", "must_not_contain"),
    [
        ("Action 1: type 'my banking password' (19 chars)", "banking"),
        ("TypeText(text='secret sentence', delay_after_ms=None)", "secret"),
        ('TypeText(text="double quoted secret")', "secret"),
    ],
)
def test_typed_text_is_redacted_from_logs(message: str, must_not_contain: str) -> None:
    """A log file must never become a transcript of what the user automated."""
    redacted = RedactingFilter.redact(message)
    assert must_not_contain not in redacted
    assert "redacted" in redacted


def test_redaction_keeps_the_diagnostic_value() -> None:
    redacted = RedactingFilter.redact("Action 1: type 'hello world' (11 chars)")
    assert "Action 1" in redacted
    assert "11 chars" in redacted


def test_redaction_leaves_ordinary_messages_alone() -> None:
    message = "pywinctl window enumeration failed: KeyError('id')"
    assert RedactingFilter.redact(message) == message


def test_the_filter_is_installed_on_every_handler(tmp_path: Path) -> None:
    configure_logging(log_directory=tmp_path)
    handlers = logging.getLogger().handlers
    assert handlers
    assert all(
        any(isinstance(f, RedactingFilter) for f in handler.filters) for handler in handlers
    )
    configure_logging(to_file=False)


# -- start-up failures ----------------------------------------------------
def test_startup_problems_read_as_advice_not_tracebacks() -> None:
    for problem in (MISSING_GUI, NO_DISPLAY):
        rendered = problem.render()
        assert "Traceback" not in rendered
        assert problem.headline in rendered
        assert len(problem.detail) > 40


def test_the_qt_plugin_problem_names_the_likely_cause() -> None:
    rendered = qt_plugin_problem(RuntimeError("xcb plugin not found")).render()
    assert "xcb plugin not found" in rendered
    assert "reinstall" in rendered.lower()


def test_the_data_directory_problem_names_the_path_and_the_override() -> None:
    rendered = data_directory_problem("/read/only", PermissionError("denied")).render()
    assert "/read/only" in rendered
    assert "XDG_DATA_HOME" in rendered


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"DISPLAY": ":0"}, True),
        ({"WAYLAND_DISPLAY": "wayland-0"}, True),
        ({"QT_QPA_PLATFORM": "offscreen"}, True),
        ({}, False),
    ],
)
def test_display_detection(env: dict[str, str], expected: bool) -> None:
    assert has_display(env, platform="linux") is expected


@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_macos_and_windows_always_have_a_display(platform: str) -> None:
    """DISPLAY is an X11 convention; asking about it elsewhere is meaningless.

    Checking it unconditionally made every macOS launch report "no graphical
    display was found" and refuse to open the window.
    """
    assert has_display({}, platform=platform) is True


# -- packaging configuration ----------------------------------------------
def test_the_spec_file_exists_and_uses_the_launcher() -> None:
    spec = (ROOT / "packaging" / "human-input-automation.spec").read_text(encoding="utf-8")
    assert "launcher.py" in spec
    assert "METADATA.executable" in spec, "the spec must take its name from the metadata"
    assert "codesign_identity=None" in spec, "signing comes from CI, never the spec"


@pytest.mark.parametrize("excluded", ["pytest", "mypy", "ruff", "PyInstaller", "setuptools"])
def test_development_tooling_is_excluded_from_bundles(excluded: str) -> None:
    spec = (ROOT / "packaging" / "human-input-automation.spec").read_text(encoding="utf-8")
    assert f'"{excluded}"' in spec.split("excludes = [")[1].split("]")[0]


def test_no_signing_material_is_committed() -> None:
    """Credentials belong in CI secrets, never in the repository."""
    packaging = ROOT / "packaging"
    for path in packaging.rglob("*"):
        if path.is_file():
            assert path.suffix not in {".p12", ".pfx", ".cer", ".key", ".mobileprovision"}
    script = (packaging / "macos" / "sign_and_notarize.sh").read_text(encoding="utf-8")
    assert "MACOS_SIGN_IDENTITY" in script
    assert "UNSIGNED" in script, "an unsigned build must be labelled, not disguised"


def test_the_macos_entitlements_request_nothing_unnecessary() -> None:
    """Check the declared keys, not the prose explaining what is not declared."""
    import plistlib

    path = ROOT / "packaging" / "macos" / "entitlements.plist"
    entitlements = plistlib.loads(path.read_bytes())
    for key in entitlements:
        for forbidden in ("camera", "microphone", "location", "addressbook", "photos", "files"):
            assert forbidden not in key.lower(), f"unnecessary entitlement: {key}"
    assert "com.apple.security.cs.disable-library-validation" in entitlements
    assert len(entitlements) <= 3, "hardened-runtime essentials only"


def test_the_windows_installer_does_not_request_administrator_rights() -> None:
    text = (ROOT / "packaging" / "windows" / "installer.iss").read_text(encoding="utf-8")
    assert "PrivilegesRequired=lowest" in text
    assert "requireAdministrator" not in text
    assert "{localappdata}" in text, "a per-user install location"


def test_uninstall_keeps_user_profiles() -> None:
    text = (ROOT / "packaging" / "windows" / "installer.iss").read_text(encoding="utf-8")
    assert "[UninstallDelete]" not in text, "the uninstaller must not delete user data"
    assert "will be kept" in text


def test_the_desktop_entry_is_well_formed() -> None:
    text = (ROOT / "packaging" / "linux" / "human-input-automation.desktop").read_text(
        encoding="utf-8"
    )
    assert text.startswith("[Desktop Entry]")
    for key in ("Type=Application", "Name=", "Exec=", "Icon=", "Categories="):
        assert key in text


def test_the_apprun_script_does_not_force_a_display_server() -> None:
    """Forcing X11 would hide the Wayland restrictions the app exists to report."""
    text = (ROOT / "packaging" / "linux" / "AppRun").read_text(encoding="utf-8")
    assert "QT_QPA_PLATFORM=xcb" not in text
    assert "HumanInputAutomation" in text


def test_the_wheel_declares_the_icons_as_package_data() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'resources/icons/*' in text
    assert '"py.typed"' in text


def test_json_is_still_the_only_profile_format_dependency() -> None:
    """Packaging must not have quietly made PyYAML mandatory."""
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    dependencies = text.split("dependencies = [")[1].split("]")[0]
    assert dependencies.strip() == "", "the core must stay dependency-free"
    assert 'yaml = ["PyYAML' in text, "YAML stays optional"
    assert json is not None


def test_the_packaging_spec_is_not_excluded_from_version_control() -> None:
    """Regression: `.gitignore` had a blanket `*.spec`.

    PyInstaller writes a `.spec` next to the script when invoked without one,
    which is what that rule was for - but it also excluded the project's own
    hand-written spec, so the packaging configuration was never committed and a
    fresh clone could not build.
    """
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "*.spec" not in ignore, "a blanket *.spec rule hides packaging/*.spec"
    assert any(line.strip() == "!packaging/*.spec" for line in ignore)
    assert (ROOT / "packaging" / "human-input-automation.spec").is_file()


def test_the_macos_bundle_declares_the_apple_events_permission() -> None:
    """Window control on macOS is an Apple Event; without the key it is refused.

    pywinctl's macOS backend drives getAllWindows, getActiveWindow and activate
    through AppleScript to System Events. macOS rejects that outright unless the
    bundle declares a usage description.
    """
    spec = (ROOT / "packaging" / "human-input-automation.spec").read_text(encoding="utf-8")
    assert "NSAppleEventsUsageDescription" in spec
    # ...and still nothing it does not use.
    for forbidden in ("NSCameraUsageDescription", "NSMicrophoneUsageDescription",
                      "NSLocationUsageDescription", "NSContactsUsageDescription"):
        assert forbidden not in spec
