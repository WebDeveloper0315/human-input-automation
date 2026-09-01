"""Profile service: the one thing the UI talks to about profiles.

It combines storage, target resolution and the *existing* domain validation.
It deliberately adds no validation of its own: structural checks live in
:mod:`.serialization`, domain checks are
:func:`~...core.validation.validate_plan`, and this module only sequences them.

Nothing here sends input. Loading, importing, resolving and validating a
profile are all side-effect free with respect to the keyboard and mouse; only
the existing run path can start automation.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from ...core.errors import ValidationIssue, ValidationResult
from ...core.plan import AutomationPlan
from ...core.screen import ScreenGeometry
from ...core.target import PlatformName, PlatformReport, TargetWindow
from ...core.validation import validate_plan
from .repository import ProfileRepository
from .resolver import ResolutionResult, TargetResolver
from .schema import (
    Profile,
    ProfileFormatError,
    ProfileState,
    ProfileStorageError,
    ProfileSummary,
    TargetIdentity,
    new_profile_id,
)
from .serialization import profile_from_dict, profile_to_dict


@dataclass(frozen=True)
class LoadedProfile:
    """A profile plus everything known about whether it can run right now."""

    profile: Profile
    state: ProfileState
    message: str = ""
    resolution: ResolutionResult | None = None
    issues: tuple[ValidationIssue, ...] = field(default_factory=tuple)
    plan: AutomationPlan | None = None

    @property
    def is_runnable(self) -> bool:
        """Only a resolved target with a valid plan may be started."""
        return self.state.is_runnable and self.plan is not None

    @property
    def target(self) -> TargetWindow | None:
        return self.resolution.target if self.resolution else None

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "error")

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "warning")


class ProfileService:
    """Storage, resolution and validation of profiles."""

    def __init__(
        self,
        repository: ProfileRepository | None = None,
        resolver: TargetResolver | None = None,
    ) -> None:
        self._repository = repository or ProfileRepository()
        self._resolver = resolver or TargetResolver()

    @property
    def repository(self) -> ProfileRepository:
        return self._repository

    @property
    def directory(self) -> Path:
        return self._repository.directory

    # -- storage -----------------------------------------------------------
    def list(self) -> Sequence[ProfileSummary]:
        return self._repository.list()

    def load(self, profile_id: str) -> Profile:
        """Read a profile. Reading never resolves a target or runs anything."""
        return self._repository.load(profile_id)

    def save(self, profile: Profile) -> Profile:
        return self._repository.save(profile)

    def delete(self, profile_id: str) -> None:
        self._repository.delete(profile_id)

    def exists(self, profile_id: str) -> bool:
        return self._repository.exists(profile_id)

    def duplicate(self, profile: Profile, name: str | None = None) -> Profile:
        """A copy with a fresh id, not yet saved."""
        return profile.with_changes(
            id=new_profile_id(),
            name=name or f"{profile.name} (copy)",
            created_at=None,
            updated_at=None,
        )

    # -- building ----------------------------------------------------------
    def build(
        self,
        name: str,
        plan: AutomationPlan,
        target: TargetWindow | None = None,
        *,
        profile_id: str | None = None,
        description: str = "",
        title_pattern: str | None = None,
    ) -> Profile:
        """Turn the current plan and target into a saveable profile.

        Only the persistent parts of the target are kept: handles, process ids
        and capabilities are runtime state and are not written out.
        """
        identity = (
            TargetIdentity.from_target(target) if target is not None else TargetIdentity()
        )
        if title_pattern:
            identity = identity.with_changes(title_pattern=title_pattern)
        return Profile(
            id=profile_id or new_profile_id(),
            name=name,
            description=description,
            target=identity,
            plan=plan,
        )

    # -- resolution and validation ----------------------------------------
    def resolve(
        self,
        profile: Profile,
        windows: Sequence[TargetWindow],
        host_platform: PlatformName | None = None,
    ) -> ResolutionResult:
        """Find the profile's window among ``windows``. Never runs anything."""
        return self._resolver.resolve(profile.target, windows, host_platform)

    def prepare(
        self,
        profile: Profile,
        windows: Sequence[TargetWindow],
        host: PlatformReport | None = None,
        screen: ScreenGeometry | None = None,
    ) -> LoadedProfile:
        """Resolve the target, then validate the plan against this host.

        The result explains precisely why a profile cannot run - an unresolved
        or ambiguous target, a blocked capability, or a plan the host rejects -
        rather than collapsing them into one error.
        """
        if profile.plan is None:
            return LoadedProfile(
                profile,
                ProfileState.PROFILE_INVALID,
                "The profile contains no automation plan.",
            )

        resolution = self.resolve(profile, windows, host.platform if host else None)
        if not resolution.is_resolved or resolution.target is None:
            return LoadedProfile(
                profile, resolution.state, resolution.message, resolution=resolution
            )

        plan = profile.plan.with_changes(target=resolution.target, name=profile.name)
        result: ValidationResult = validate_plan(plan, host=host, screen=screen)
        if not result.ok:
            return LoadedProfile(
                profile,
                ProfileState.PROFILE_INVALID,
                "; ".join(issue.message for issue in result.errors),
                resolution=resolution,
                issues=result.issues,
            )
        return LoadedProfile(
            profile,
            ProfileState.TARGET_RESOLVED,
            resolution.message,
            resolution=resolution,
            issues=result.issues,
            plan=plan,
        )

    # -- import / export ---------------------------------------------------
    def export(self, profile: Profile, path: Path | str) -> Path:
        """Write a profile to an arbitrary file the user chose."""
        destination = Path(path)
        payload = json.dumps(
            profile_to_dict(profile), indent=2, ensure_ascii=False, allow_nan=False
        )
        try:
            destination.write_text(payload + "\n", encoding="utf-8")
        except OSError as error:
            raise ProfileStorageError(f"Could not export the profile: {error}") from error
        return destination

    def import_file(self, path: Path | str, *, save: bool = True) -> Profile:
        """Read and validate a profile file, optionally storing it.

        Importing never executes anything: the file is parsed, structurally
        validated and stored. A clashing id is replaced with a fresh one so an
        import cannot overwrite an existing profile.
        """
        source = Path(path)
        try:
            text = source.read_text(encoding="utf-8")
        except OSError as error:
            raise ProfileStorageError(f"Could not read {source.name}: {error}") from error
        if not text.strip():
            raise ProfileFormatError(f"{source.name} is empty")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as error:
            raise ProfileFormatError(f"{source.name} is not valid JSON: {error}") from error

        profile = profile_from_dict(data)
        if self._repository.exists(profile.id):
            profile = profile.with_changes(id=new_profile_id())
        return self._repository.save(profile) if save else profile

    def validate_file(self, path: Path | str) -> Profile:
        """Parse and structurally validate a file without storing it.

        Used by ``--validate-profile``; sends no input and writes nothing.
        """
        return self.import_file(path, save=False)
