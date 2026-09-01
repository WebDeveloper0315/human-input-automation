"""Finding a saved target again.

A profile stores what stays true across restarts (platform, application, window
title), not what does not (handles, process ids, capabilities). Turning that
back into a live window is this module's job, and it follows one rule above all:

**Never choose a window on the user's behalf when the answer is not obvious.**

An automation profile types into whatever it is pointed at, so guessing between
two plausible windows - or falling back to whatever happens to be focused - is
the one outcome that must never happen. Ambiguity is reported, not resolved.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from ...core.target import PlatformName, TargetWindow
from .schema import ProfileState, TargetIdentity


class MatchRule(str):
    """Marker type for the rule that produced a match (used in messages)."""


#: Matching priority, highest first. Documented in docs/PROFILE-FORMAT.md.
#: There is no fuzzy matching: every rule is an exact or explicit-pattern match.
MATCH_PRIORITY = (
    "handle hint confirmed by application identity",
    "application id",
    "process name",
    "window title pattern",
    "exact window title",
)


@dataclass(frozen=True)
class ResolutionResult:
    """The outcome of trying to find a saved target.

    ``target`` is set only for :attr:`ProfileState.TARGET_RESOLVED`; every other
    state carries a message the UI can show and, where useful, the candidates
    that caused the ambiguity.
    """

    state: ProfileState
    target: TargetWindow | None = None
    message: str = ""
    candidates: tuple[TargetWindow, ...] = field(default_factory=tuple)
    matched_by: str = ""

    @property
    def is_resolved(self) -> bool:
        return self.state is ProfileState.TARGET_RESOLVED and self.target is not None

    def describe(self) -> str:
        return self.message or self.state.value


def _matches_text(saved: str | None, candidate: str | None) -> bool:
    """Case-insensitive exact comparison; ``None`` never matches anything."""
    if not saved or not candidate:
        return False
    return saved.strip().casefold() == candidate.strip().casefold()


class TargetResolver:
    """Resolves a :class:`TargetIdentity` against the live window list.

    Priority (see :data:`MATCH_PRIORITY`):

    1. **Handle hint** - accepted only when the window it points at *also*
       matches the saved application identity. A handle alone is never trusted:
       ids get reused, and the window behind one after a restart may belong to
       something else entirely.
    2. **Application id** (bundle id / WM_CLASS), exact, case-insensitive.
    3. **Process name**, exact, case-insensitive.
    4. **Title pattern** (regex) or exact title. When the profile records an
       application, the title only *narrows* that application's windows and can
       never widen the search - a window of a different program that happens to
       share a title is not the target. A title is used on its own only when the
       profile records no application identity at all.

    Zero candidates is ``TARGET_UNRESOLVED``; more than one is
    ``TARGET_AMBIGUOUS``. The currently focused window is never a fallback.
    """

    def resolve(
        self,
        identity: TargetIdentity,
        windows: Sequence[TargetWindow],
        host_platform: PlatformName | None = None,
    ) -> ResolutionResult:
        if host_platform is not None and identity.platform not in (
            PlatformName.UNKNOWN,
            host_platform,
        ):
            return ResolutionResult(
                ProfileState.TARGET_UNRESOLVED,
                message=(
                    f"This profile was saved on {identity.platform.value}, "
                    f"but this computer is {host_platform.value}."
                ),
            )

        if not identity.has_application_identity and not (identity.title or identity.title_pattern):
            return ResolutionResult(
                ProfileState.TARGET_UNRESOLVED,
                message="The profile does not record enough information to find its window.",
            )

        hinted = self._by_handle_hint(identity, windows)
        if hinted is not None:
            return self._finish(identity, hinted, MATCH_PRIORITY[0])

        if identity.has_application_identity:
            # Title is only ever used to narrow *within* the saved application.
            # A window that merely shares a title but belongs to something else
            # is not the target - matching it could type into another program.
            candidates = self._by_application(identity, windows)
            matched_by = MATCH_PRIORITY[1] if identity.app_id else MATCH_PRIORITY[2]
            narrowed = self._by_title(identity, candidates)
            if narrowed:
                candidates = narrowed
                if identity.title_pattern:
                    matched_by = MATCH_PRIORITY[3]
        else:
            # No application identity was saved, so the title is all there is.
            candidates = self._by_title(identity, windows)
            matched_by = MATCH_PRIORITY[3] if identity.title_pattern else MATCH_PRIORITY[4]

        if not candidates:
            return ResolutionResult(
                ProfileState.TARGET_UNRESOLVED,
                message=f"{identity.describe()} is not currently running.",
            )
        if len(candidates) > 1:
            titles = ", ".join(repr(window.title) for window in candidates[:4])
            more = "" if len(candidates) <= 4 else f" and {len(candidates) - 4} more"
            return ResolutionResult(
                ProfileState.TARGET_AMBIGUOUS,
                message=(
                    f"{len(candidates)} windows match {identity.describe()}: {titles}{more}. "
                    "Select the intended window."
                ),
                candidates=tuple(candidates),
                matched_by=matched_by,
            )
        return self._finish(identity, candidates[0], matched_by)

    # -- rules -------------------------------------------------------------
    def _by_handle_hint(
        self, identity: TargetIdentity, windows: Sequence[TargetWindow]
    ) -> TargetWindow | None:
        if not identity.handle_hint or not identity.has_application_identity:
            return None
        for window in windows:
            if window.handle != identity.handle_hint:
                continue
            if self._same_application(identity, window):
                return window
            return None  # the id survived, the application behind it did not
        return None

    def _same_application(self, identity: TargetIdentity, window: TargetWindow) -> bool:
        if identity.app_id and _matches_text(identity.app_id, window.app_id):
            return True
        return bool(
            identity.process_name and _matches_text(identity.process_name, window.process_name)
        )

    def _by_application(
        self, identity: TargetIdentity, windows: Sequence[TargetWindow]
    ) -> list[TargetWindow]:
        if not identity.has_application_identity:
            return []
        return [window for window in windows if self._same_application(identity, window)]

    def _by_title(
        self, identity: TargetIdentity, windows: Sequence[TargetWindow]
    ) -> list[TargetWindow]:
        if identity.title_pattern:
            try:
                pattern = re.compile(identity.title_pattern)
            except re.error:  # validated on load; treat a bad pattern as no match
                return []
            return [window for window in windows if pattern.search(window.title or "")]
        if identity.title:
            return [window for window in windows if _matches_text(identity.title, window.title)]
        return []

    def _finish(
        self, identity: TargetIdentity, window: TargetWindow, matched_by: str
    ) -> ResolutionResult:
        """Resolved - unless the platform will not let us drive that window."""
        if not window.capabilities.can_send_synthetic_input:
            return ResolutionResult(
                ProfileState.TARGET_CAPABILITY_BLOCKED,
                target=None,
                message=(
                    f"{window.describe()} was found, but this platform cannot send input to it. "
                    "See the capability banner for details."
                ),
                candidates=(window,),
                matched_by=matched_by,
            )
        return ResolutionResult(
            ProfileState.TARGET_RESOLVED,
            target=window,
            message=f"Target resolved by {matched_by}: {window.describe()}",
            candidates=(window,),
            matched_by=matched_by,
        )
