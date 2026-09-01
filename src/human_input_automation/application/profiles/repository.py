"""JSON profile storage.

One file per profile, named by its opaque id, in a platform-appropriate
application data directory. Standard-library ``json`` only - no database, no
YAML requirement.

Two properties this module is responsible for:

* **Names never touch the filesystem.** Files are named by a 32-character hex
  id, so a profile called ``../../.bashrc`` or ``CON`` is stored as
  ``4f3e....json`` like any other. Path traversal is impossible by
  construction rather than by sanitising.
* **Writes are atomic.** Data is written to a temporary file in the same
  directory, flushed and fsynced, then moved into place with ``os.replace``.
  An interrupted save leaves the previous profile intact, never a truncated
  file.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from ...paths import user_data_directory
from .schema import (
    Profile,
    ProfileFormatError,
    ProfileNotFoundError,
    ProfileStorageError,
    ProfileSummary,
    is_valid_profile_id,
)
from .serialization import profile_from_dict, profile_to_dict

PROFILE_SUFFIX = ".json"

#: The platform data directory lives in :mod:`...paths`, so the application and
#: its packaging agree on one location.
default_data_directory = user_data_directory


def default_profile_directory(
    platform_id: str | None = None, env: dict[str, str] | None = None, home: Path | None = None
) -> Path:
    """Where profiles live by default. Never inside the source tree."""
    return default_data_directory(platform_id, env, home) / "profiles"


class ProfileRepository:
    """Stores profiles as JSON files in one directory."""

    def __init__(self, directory: Path | str | None = None) -> None:
        self._directory = Path(directory) if directory is not None else default_profile_directory()

    @property
    def directory(self) -> Path:
        return self._directory

    # -- reading -----------------------------------------------------------
    def list(self) -> Sequence[ProfileSummary]:
        """Every profile in the directory, newest name-sorted first.

        A file that will not parse is listed with its error rather than
        omitted, so one corrupt profile cannot silently hide the others.
        """
        if not self._directory.is_dir():
            return ()
        summaries: list[ProfileSummary] = []
        for path in sorted(self._directory.glob(f"*{PROFILE_SUFFIX}")):
            profile_id = path.stem
            if not is_valid_profile_id(profile_id):
                continue
            try:
                profile = self._read(path)
            except ProfileFormatError as error:
                summaries.append(
                    ProfileSummary(id=profile_id, name=path.name, error=str(error))
                )
            except ProfileStorageError as error:
                summaries.append(
                    ProfileSummary(id=profile_id, name=path.name, error=str(error))
                )
            else:
                summaries.append(
                    ProfileSummary(
                        id=profile.id,
                        name=profile.name,
                        description=profile.description,
                        updated_at=profile.updated_at,
                    )
                )
        return tuple(sorted(summaries, key=lambda summary: summary.name.lower()))

    def exists(self, profile_id: str) -> bool:
        return is_valid_profile_id(profile_id) and self._path_for(profile_id).is_file()

    def load(self, profile_id: str) -> Profile:
        """Read one profile. Raises rather than returning a partial object."""
        path = self._path_for(profile_id)
        if not path.is_file():
            raise ProfileNotFoundError(f"No profile with id {profile_id}")
        return self._read(path)

    # -- writing -----------------------------------------------------------
    def save(self, profile: Profile) -> Profile:
        """Write a profile atomically and return it with ``updated_at`` set.

        On failure the exception propagates and nothing is changed on disk, so
        the caller can honestly report that the profile was *not* saved.
        """
        if not is_valid_profile_id(profile.id):
            raise ProfileStorageError(f"Invalid profile id: {profile.id!r}")
        now = datetime.now(UTC).isoformat(timespec="seconds")
        stored = profile.with_changes(created_at=profile.created_at or now, updated_at=now)
        payload = json.dumps(
            profile_to_dict(stored), indent=2, ensure_ascii=False, allow_nan=False, sort_keys=False
        )
        self._atomic_write(self._path_for(stored.id), payload + "\n")
        return stored

    def delete(self, profile_id: str) -> None:
        path = self._path_for(profile_id)
        if not path.is_file():
            raise ProfileNotFoundError(f"No profile with id {profile_id}")
        try:
            path.unlink()
        except OSError as error:
            raise ProfileStorageError(f"Could not delete the profile: {error}") from error

    # -- internals ---------------------------------------------------------
    def _path_for(self, profile_id: str) -> Path:
        if not is_valid_profile_id(profile_id):
            # Ids are generated, never user text, so this is a programming error
            # or a tampered path - either way it must not reach the filesystem.
            raise ProfileStorageError(f"Invalid profile id: {profile_id!r}")
        return self._directory / f"{profile_id}{PROFILE_SUFFIX}"

    def _read(self, path: Path) -> Profile:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as error:
            raise ProfileStorageError(f"Could not read {path.name}: {error}") from error
        if not text.strip():
            raise ProfileFormatError(f"{path.name} is empty")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as error:
            raise ProfileFormatError(f"{path.name} is not valid JSON: {error}") from error
        return profile_from_dict(data)

    def _atomic_write(self, path: Path, payload: str) -> None:
        try:
            self._directory.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise ProfileStorageError(
                f"Could not create the profile directory {self._directory}: {error}"
            ) from error

        handle = None
        temporary: Path | None = None
        try:
            descriptor, name = tempfile.mkstemp(
                dir=self._directory, prefix=f"{path.stem}.", suffix=".tmp"
            )
            temporary = Path(name)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            temporary = None
        except OSError as error:
            raise ProfileStorageError(f"Could not save the profile: {error}") from error
        finally:
            if temporary is not None and temporary.exists():
                # Best effort: the write already failed, so a leftover temp file
                # must not mask the real error.
                with contextlib.suppress(OSError):
                    temporary.unlink()
