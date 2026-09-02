"""Target re-resolution: deterministic matching, never a guess."""

from __future__ import annotations

from dataclasses import replace

import pytest

from human_input_automation.application.profiles import (
    ProfileState,
    TargetIdentity,
    TargetResolver,
)
from human_input_automation.core.target import (
    DisplayServer,
    PlatformName,
    TargetWindow,
    WindowCapabilities,
)


def window(
    handle: str = "0x1",
    title: str = "Document - Editor",
    process: str | None = "editor",
    app_id: str | None = "org.example.editor",
    pid: int | None = 100,
    capabilities: WindowCapabilities | None = None,
) -> TargetWindow:
    return TargetWindow(
        handle=handle,
        title=title,
        platform=PlatformName.LINUX,
        display_server=DisplayServer.X11,
        process_name=process,
        process_id=pid,
        app_id=app_id,
        capabilities=capabilities or WindowCapabilities.full(),
    )


def identity(**changes: object) -> TargetIdentity:
    base = TargetIdentity(
        platform=PlatformName.LINUX,
        display_server=DisplayServer.X11,
        process_name="editor",
        app_id="org.example.editor",
        title="Document - Editor",
        handle_hint="0x1",
    )
    return replace(base, **changes)  # type: ignore[arg-type]


RESOLVER = TargetResolver()


# -- successful matches ---------------------------------------------------
def test_a_confirmed_handle_hint_resolves_first() -> None:
    result = RESOLVER.resolve(identity(), [window()])
    assert result.state is ProfileState.TARGET_RESOLVED
    assert result.target is not None and result.target.handle == "0x1"
    assert "handle hint" in result.matched_by


def test_an_app_id_match_resolves_after_a_restart() -> None:
    """The window id changed (the app restarted); the app id did not."""
    restarted = window(handle="0x999", pid=555)
    result = RESOLVER.resolve(identity(), [restarted])
    assert result.state is ProfileState.TARGET_RESOLVED
    assert result.target is not None and result.target.handle == "0x999"
    assert result.matched_by == "application id"


def test_a_process_name_match_is_used_when_no_app_id_was_saved() -> None:
    result = RESOLVER.resolve(
        identity(app_id=None, handle_hint=None), [window(handle="0x7", app_id=None)]
    )
    assert result.state is ProfileState.TARGET_RESOLVED
    assert result.matched_by == "process name"


def test_matching_is_case_insensitive() -> None:
    result = RESOLVER.resolve(
        identity(app_id="ORG.EXAMPLE.EDITOR", handle_hint=None), [window()]
    )
    assert result.state is ProfileState.TARGET_RESOLVED


def test_a_title_pattern_narrows_several_windows_of_one_application() -> None:
    windows = [
        window(handle="0x1", title="notes.txt - Editor"),
        window(handle="0x2", title="report.pdf - Editor"),
    ]
    result = RESOLVER.resolve(
        identity(handle_hint=None, title=None, title_pattern=r"^report\.pdf"), windows
    )
    assert result.state is ProfileState.TARGET_RESOLVED
    assert result.target is not None and result.target.handle == "0x2"
    assert result.matched_by == "window title pattern"


def test_an_exact_title_narrows_when_no_pattern_was_saved() -> None:
    windows = [
        window(handle="0x1", title="notes.txt - Editor"),
        window(handle="0x2", title="Document - Editor"),
    ]
    result = RESOLVER.resolve(identity(handle_hint=None), windows)
    assert result.target is not None and result.target.handle == "0x2"


def test_a_changed_title_still_resolves_by_application() -> None:
    """Titles change constantly; that must not orphan a profile."""
    result = RESOLVER.resolve(
        identity(handle_hint=None), [window(handle="0x3", title="something else entirely")]
    )
    assert result.state is ProfileState.TARGET_RESOLVED


def test_a_title_only_identity_can_still_match() -> None:
    result = RESOLVER.resolve(
        TargetIdentity(platform=PlatformName.LINUX, title="Document - Editor"), [window()]
    )
    assert result.state is ProfileState.TARGET_RESOLVED
    assert result.matched_by == "exact window title"


# -- refusals -------------------------------------------------------------
def test_a_stale_handle_pointing_at_another_application_is_not_trusted() -> None:
    """The id was reused by something else: never type into it."""
    stranger = window(handle="0x1", process="banking-app", app_id="com.bank.app", title="Bank")
    result = RESOLVER.resolve(identity(), [stranger])
    assert result.state is ProfileState.TARGET_UNRESOLVED
    assert result.target is None


def test_a_closed_application_is_unresolved_with_a_readable_message() -> None:
    result = RESOLVER.resolve(identity(), [window(handle="0x9", app_id="other", process="other")])
    assert result.state is ProfileState.TARGET_UNRESOLVED
    assert "not currently running" in result.message


def test_no_windows_at_all_is_unresolved() -> None:
    assert RESOLVER.resolve(identity(), []).state is ProfileState.TARGET_UNRESOLVED


def test_several_matching_windows_are_ambiguous_not_arbitrary() -> None:
    windows = [
        window(handle="0x1", title="a.txt - Editor"),
        window(handle="0x2", title="b.txt - Editor"),
        window(handle="0x3", title="c.txt - Editor"),
    ]
    result = RESOLVER.resolve(identity(handle_hint=None, title=None), windows)
    assert result.state is ProfileState.TARGET_AMBIGUOUS
    assert result.target is None, "the resolver must never pick one for the user"
    assert len(result.candidates) == 3
    assert "Select the intended window" in result.message


def test_ambiguity_survives_a_pattern_that_matches_everything() -> None:
    windows = [window(handle="0x1", title="a - Editor"), window(handle="0x2", title="b - Editor")]
    result = RESOLVER.resolve(
        identity(handle_hint=None, title=None, title_pattern="Editor"), windows
    )
    assert result.state is ProfileState.TARGET_AMBIGUOUS


def test_a_platform_mismatch_is_refused_with_an_explanation() -> None:
    result = RESOLVER.resolve(
        identity(platform=PlatformName.WINDOWS), [window()], PlatformName.LINUX
    )
    assert result.state is ProfileState.TARGET_UNRESOLVED
    assert "saved on windows" in result.message
    assert "linux" in result.message


def test_an_identity_with_nothing_to_match_on_is_unresolved() -> None:
    result = RESOLVER.resolve(TargetIdentity(platform=PlatformName.LINUX), [window()])
    assert result.state is ProfileState.TARGET_UNRESOLVED
    assert "not record enough information" in result.message


def test_a_window_without_input_capability_is_capability_blocked() -> None:
    blocked = window(capabilities=WindowCapabilities(can_enumerate=True, can_activate=True))
    result = RESOLVER.resolve(identity(), [blocked])
    assert result.state is ProfileState.TARGET_CAPABILITY_BLOCKED
    assert result.target is None, "a blocked target must not be runnable"
    assert "cannot send input" in result.message


def test_the_focused_window_is_never_a_fallback() -> None:
    """Even with a focused window present, a non-matching profile stays unresolved."""
    focused = TargetWindow.focused_window(
        platform=PlatformName.LINUX, capabilities=WindowCapabilities.full()
    )
    result = RESOLVER.resolve(identity(), [focused])
    assert result.state is ProfileState.TARGET_UNRESOLVED


def test_a_broken_saved_pattern_matches_nothing_rather_than_raising() -> None:
    result = RESOLVER.resolve(
        identity(handle_hint=None, app_id=None, process_name=None, title=None,
                 title_pattern="([unclosed"),
        [window()],
    )
    assert result.state is ProfileState.TARGET_UNRESOLVED


@pytest.mark.parametrize("state", list(ProfileState))
def test_only_a_resolved_target_is_runnable(state: ProfileState) -> None:
    assert state.is_runnable is (state is ProfileState.TARGET_RESOLVED)


def test_macos_style_application_names_are_coarse() -> None:
    """Observed on a real Mac: pywinctl reports the *process* name.

    A Python script's windows all report "Python", so several unrelated windows
    share one application identity. The resolver must call that ambiguous
    rather than picking one - which is exactly what it does.
    """
    windows = [
        window(handle="('Python', 'Target')", title="Target", process="Python", app_id="Python"),
        window(handle="('Python', 'Decoy')", title="Decoy", process="Python", app_id="Python"),
    ]
    result = RESOLVER.resolve(identity(app_id="Python", process_name="Python",
                                       title=None, handle_hint=None), windows)
    assert result.state is ProfileState.TARGET_AMBIGUOUS
    assert result.target is None


def test_a_coarse_application_name_is_narrowed_by_the_window_title() -> None:
    """The saved title disambiguates windows sharing one application name."""
    windows = [
        window(handle="('Python', 'Target')", title="Target", process="Python", app_id="Python"),
        window(handle="('Python', 'Decoy')", title="Decoy", process="Python", app_id="Python"),
    ]
    result = RESOLVER.resolve(
        identity(app_id="Python", process_name="Python", title="Target", handle_hint=None),
        windows,
    )
    assert result.state is ProfileState.TARGET_RESOLVED
    assert result.target is not None and result.target.title == "Target"
