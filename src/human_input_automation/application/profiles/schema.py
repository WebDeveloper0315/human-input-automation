"""Profile data model, schema version and failure states.

A profile is **pure data**: a name, a persistent way to find the target
application again, and the plan to run. It never contains code, commands or
anything executable, and loading one can never start automation.

Persistence lives in the application layer, not the core: the engine knows
nothing about files, and these types know nothing about Qt or the filesystem.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field, replace
from enum import StrEnum

from ...core.errors import AutomationError, ValidationIssue
from ...core.plan import AutomationPlan
from ...core.target import DisplayServer, PlatformName, TargetWindow

#: The only schema version this build writes and understands.
SCHEMA_VERSION = 1

#: Versions this build can read. Anything else is rejected explicitly rather
#: than being guessed at or silently downgraded.
SUPPORTED_SCHEMA_VERSIONS = frozenset({1})

_PROFILE_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


class ProfileState(StrEnum):
    """Why a profile can or cannot be run right now.

    Kept as distinct states rather than one generic error so the UI can say
    *which* problem it is: a bad file and a closed application need different
    responses from the user.
    """

    #: The file parsed, validated, and its target resolved to exactly one window.
    TARGET_RESOLVED = "target_resolved"
    #: Structurally and semantically fine, but not runnable as-is.
    PROFILE_VALID = "profile_valid"
    #: The file or its contents failed validation. Never runnable.
    PROFILE_INVALID = "profile_invalid"
    #: No window matches the saved identity (the application is not running).
    TARGET_UNRESOLVED = "target_unresolved"
    #: Several windows match; the user must pick one. Never chosen for them.
    TARGET_AMBIGUOUS = "target_ambiguous"
    #: The window exists, but this platform will not let us drive it.
    TARGET_CAPABILITY_BLOCKED = "target_capability_blocked"

    @property
    def is_runnable(self) -> bool:
        """Only a resolved target may be handed to the run path."""
        return self is ProfileState.TARGET_RESOLVED


class ProfileError(AutomationError):
    """Base class for profile persistence failures."""


class ProfileFormatError(ProfileError):
    """The profile data is malformed or fails validation."""

    def __init__(
        self, message: str, issues: tuple[ValidationIssue, ...] | list[ValidationIssue] = ()
    ) -> None:
        self.issues: tuple[ValidationIssue, ...] = tuple(issues)
        super().__init__(message)


class UnsupportedSchemaError(ProfileFormatError):
    """The profile was written by a version this build does not understand."""

    def __init__(self, version: object) -> None:
        self.version = version
        super().__init__(f"Unsupported profile schema version: {version}")


class ProfileNotFoundError(ProfileError):
    """No profile with that id exists."""


class ProfileStorageError(ProfileError):
    """The profile could not be read from or written to storage."""


def new_profile_id() -> str:
    """A fresh opaque profile id, safe to use as a filename."""
    return uuid.uuid4().hex


def is_valid_profile_id(value: str) -> bool:
    """Whether ``value`` is one of our ids.

    Ids are 32 lowercase hex characters, so they can never contain a path
    separator, ``..``, a Windows reserved device name, or anything else that
    would escape the profile directory.
    """
    return bool(_PROFILE_ID_PATTERN.match(value))


@dataclass(frozen=True)
class TargetIdentity:
    """How to find the target application again after a restart.

    This is deliberately *not* a :class:`TargetWindow`. Window handles, process
    ids, focus state and platform capabilities are all runtime facts that expire
    the moment the application closes; storing them as identity would mean
    happily typing into whatever inherited the handle. What is stored here is
    what stays true across restarts: the platform, the application, and how its
    window is titled.

    ``handle_hint`` is the one exception, and it is only ever a hint: the
    resolver accepts it only when the window it points at also matches the
    application identity.
    """

    platform: PlatformName = PlatformName.UNKNOWN
    display_server: DisplayServer = DisplayServer.UNKNOWN
    process_name: str | None = None
    app_id: str | None = None
    title: str | None = None
    title_pattern: str | None = None
    handle_hint: str | None = None

    @classmethod
    def from_target(cls, target: TargetWindow) -> TargetIdentity:
        """Extract the persistent parts of a live window."""
        return cls(
            platform=target.platform,
            display_server=target.display_server,
            process_name=target.process_name,
            app_id=target.app_id,
            title=target.title or None,
            title_pattern=None,
            handle_hint=target.handle or None,
        )

    @property
    def has_application_identity(self) -> bool:
        """Whether anything durable identifies the application."""
        return bool(self.app_id or self.process_name)

    def describe(self) -> str:
        """Short human-readable description for the UI."""
        parts = [part for part in (self.app_id, self.process_name) if part]
        label = parts[0] if parts else (self.title or "unknown application")
        if self.title_pattern:
            return f"{label} (title matching {self.title_pattern!r})"
        if self.title:
            return f"{label} - {self.title}"
        return label

    def with_changes(self, **changes: object) -> TargetIdentity:
        return replace(self, **changes)  # type: ignore[arg-type]


@dataclass(frozen=True)
class Profile:
    """A saved automation profile."""

    id: str = field(default_factory=new_profile_id)
    name: str = "Untitled profile"
    description: str = ""
    target: TargetIdentity = field(default_factory=TargetIdentity)
    plan: AutomationPlan | None = None
    created_at: str | None = None
    updated_at: str | None = None

    def with_changes(self, **changes: object) -> Profile:
        return replace(self, **changes)  # type: ignore[arg-type]

    def describe(self) -> str:
        actions = len(self.plan.actions) if self.plan is not None else 0
        return f"{self.name} ({actions} action(s)) -> {self.target.describe()}"


@dataclass(frozen=True)
class ProfileSummary:
    """A directory listing entry.

    A file that will not parse still appears, carrying its error, so a single
    corrupt profile cannot hide the rest of the list.
    """

    id: str
    name: str
    description: str = ""
    updated_at: str | None = None
    error: str | None = None

    @property
    def is_readable(self) -> bool:
        return self.error is None
