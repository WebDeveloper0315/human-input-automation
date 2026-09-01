"""Profile storage: atomic writes, safe filenames, corruption handling.

Every test uses a temporary directory. Nothing here touches the user's real
profile directory.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from human_input_automation.application.profiles import (
    Profile,
    ProfileFormatError,
    ProfileNotFoundError,
    ProfileRepository,
    ProfileStorageError,
    TargetIdentity,
    default_profile_directory,
    new_profile_id,
    profile_to_dict,
)
from human_input_automation.core.actions import TypeText, Wait
from human_input_automation.core.plan import AutomationPlan
from human_input_automation.core.target import PlatformName

from .fakes import make_target


@pytest.fixture
def repository(tmp_path: Path) -> ProfileRepository:
    return ProfileRepository(tmp_path / "profiles")


def make_profile(name: str = "Test profile") -> Profile:
    return Profile(
        name=name,
        description="a profile",
        target=TargetIdentity(platform=PlatformName.LINUX, process_name="editor"),
        plan=AutomationPlan(make_target(), [TypeText(text="hi"), Wait(duration_ms=100)]),
    )


# -- basic operations -----------------------------------------------------
def test_save_then_load_round_trips(repository: ProfileRepository) -> None:
    saved = repository.save(make_profile())
    loaded = repository.load(saved.id)
    assert loaded.name == "Test profile"
    assert loaded.plan is not None and len(loaded.plan.actions) == 2
    assert loaded.target.process_name == "editor"


def test_save_sets_timestamps_and_keeps_created_at(repository: ProfileRepository) -> None:
    first = repository.save(make_profile())
    assert first.created_at and first.updated_at
    second = repository.save(first.with_changes(name="Renamed"))
    assert second.created_at == first.created_at
    assert repository.load(first.id).name == "Renamed"


def test_the_directory_is_created_on_demand(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b" / "profiles"
    repository = ProfileRepository(nested)
    repository.save(make_profile())
    assert nested.is_dir()


def test_list_is_empty_when_nothing_is_stored(repository: ProfileRepository) -> None:
    assert repository.list() == ()


def test_list_returns_summaries_sorted_by_name(repository: ProfileRepository) -> None:
    repository.save(make_profile("Zebra"))
    repository.save(make_profile("apple"))
    assert [summary.name for summary in repository.list()] == ["apple", "Zebra"]


def test_exists_and_delete(repository: ProfileRepository) -> None:
    saved = repository.save(make_profile())
    assert repository.exists(saved.id)
    repository.delete(saved.id)
    assert not repository.exists(saved.id)
    assert repository.list() == ()


def test_deleting_a_missing_profile_is_an_error(repository: ProfileRepository) -> None:
    with pytest.raises(ProfileNotFoundError):
        repository.delete(new_profile_id())


def test_loading_a_missing_profile_is_an_error(repository: ProfileRepository) -> None:
    with pytest.raises(ProfileNotFoundError):
        repository.load(new_profile_id())


def test_two_profiles_with_the_same_name_are_separate_files(
    repository: ProfileRepository,
) -> None:
    """Names are display text; ids are identity."""
    first = repository.save(make_profile("Duplicate"))
    second = repository.save(make_profile("Duplicate"))
    assert first.id != second.id
    assert len(repository.list()) == 2


# -- filenames and traversal ----------------------------------------------
@pytest.mark.parametrize(
    "hostile_name",
    [
        "../../etc/passwd",
        "..\\..\\windows\\system32\\config",
        "CON",
        "NUL",
        "name/with/slashes",
        "name\\with\\backslashes",
        "a" * 500,
        ".",
        "..",
        "",
    ],
)
def test_hostile_display_names_never_reach_the_filesystem(
    repository: ProfileRepository, hostile_name: str
) -> None:
    saved = repository.save(make_profile().with_changes(name=hostile_name or "x"))
    files = list(repository.directory.iterdir())
    assert len(files) == 1
    assert files[0].name == f"{saved.id}.json"
    assert files[0].parent == repository.directory


@pytest.mark.parametrize(
    "bad_id", ["../escape", "not-hex", "ABCDEF", "", "4f3e", "/absolute", "a" * 33]
)
def test_invalid_ids_are_refused_before_any_file_access(
    repository: ProfileRepository, bad_id: str
) -> None:
    with pytest.raises(ProfileStorageError):
        repository.save(make_profile().with_changes(id=bad_id))
    assert not repository.exists(bad_id)


def test_files_are_named_by_id(repository: ProfileRepository) -> None:
    saved = repository.save(make_profile())
    assert (repository.directory / f"{saved.id}.json").is_file()


# -- corruption and partial writes ----------------------------------------
def test_a_corrupt_profile_is_listed_with_its_error(repository: ProfileRepository) -> None:
    repository.save(make_profile("Good"))
    broken = repository.directory / f"{new_profile_id()}.json"
    broken.write_text("{not json", encoding="utf-8")

    summaries = repository.list()
    assert len(summaries) == 2, "one bad file must not hide the others"
    bad = next(summary for summary in summaries if not summary.is_readable)
    assert "not valid JSON" in (bad.error or "")


def test_an_empty_file_is_reported_as_such(repository: ProfileRepository) -> None:
    path = repository.directory
    path.mkdir(parents=True, exist_ok=True)
    profile_id = new_profile_id()
    (path / f"{profile_id}.json").write_text("", encoding="utf-8")
    with pytest.raises(ProfileFormatError) as excinfo:
        repository.load(profile_id)
    assert "empty" in str(excinfo.value)


def test_an_unsupported_schema_on_disk_is_rejected(repository: ProfileRepository) -> None:
    saved = repository.save(make_profile())
    path = repository.directory / f"{saved.id}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["schema"] = 99
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ProfileFormatError):
        repository.load(saved.id)


def test_files_that_are_not_profiles_are_ignored(repository: ProfileRepository) -> None:
    repository.save(make_profile())
    repository.directory.joinpath("notes.txt").write_text("hello", encoding="utf-8")
    repository.directory.joinpath("random-name.json").write_text("{}", encoding="utf-8")
    assert len(repository.list()) == 1


def test_an_interrupted_write_leaves_the_previous_profile_intact(
    repository: ProfileRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Simulates a crash between writing the temp file and replacing the target."""
    saved = repository.save(make_profile("Original"))
    path = repository.directory / f"{saved.id}.json"
    original = path.read_text(encoding="utf-8")

    def explode(source: object, destination: object) -> None:
        raise OSError("power lost")

    monkeypatch.setattr(os, "replace", explode)
    with pytest.raises(ProfileStorageError):
        repository.save(saved.with_changes(name="Replacement"))

    assert path.read_text(encoding="utf-8") == original
    assert repository.load(saved.id).name == "Original"


def test_a_failed_write_leaves_no_temporary_files_behind(
    repository: ProfileRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    saved = repository.save(make_profile())
    def explode(source: object, destination: object) -> None:
        raise OSError("interrupted")

    monkeypatch.setattr(os, "replace", explode)
    with pytest.raises(ProfileStorageError):
        repository.save(saved)
    assert [path.name for path in repository.directory.glob("*.tmp")] == []


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX permission semantics")
def test_a_read_only_directory_reports_a_storage_error(tmp_path: Path) -> None:
    directory = tmp_path / "profiles"
    directory.mkdir()
    directory.chmod(stat.S_IREAD | stat.S_IEXEC)
    try:
        with pytest.raises(ProfileStorageError):
            ProfileRepository(directory).save(make_profile())
    finally:
        directory.chmod(stat.S_IRWXU)


def test_an_unreadable_file_is_reported_not_raised_during_listing(
    repository: ProfileRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository.save(make_profile())

    def deny(self: Path, *args: object, **kwargs: object) -> str:
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "read_text", deny)
    summaries = repository.list()
    assert len(summaries) == 1 and not summaries[0].is_readable


# -- storage location -----------------------------------------------------
@pytest.mark.parametrize(
    ("platform_id", "env", "expected_part"),
    [
        ("win32", {"APPDATA": "C:\\Users\\x\\AppData\\Roaming"}, "AppData"),
        ("darwin", {}, "Library/Application Support"),
        ("linux", {"XDG_DATA_HOME": "/custom/data"}, "custom/data"),
        ("linux", {}, ".local/share"),
    ],
)
def test_the_default_directory_follows_platform_conventions(
    platform_id: str, env: dict[str, str], expected_part: str
) -> None:
    path = default_profile_directory(platform_id, env, home=Path("/home/tester"))
    assert expected_part.replace("/", os.sep) in str(path) or expected_part in str(path)
    assert path.name == "profiles"
    assert "human-input-automation" in str(path)


def test_the_default_directory_is_not_inside_the_source_tree() -> None:
    path = default_profile_directory("linux", {"XDG_DATA_HOME": "/x/data"}, home=Path("/home/t"))
    assert "src" not in path.parts
    assert Path.cwd() not in path.parents


def test_a_json_file_on_disk_is_human_readable(repository: ProfileRepository) -> None:
    saved = repository.save(make_profile("Readable"))
    text = (repository.directory / f"{saved.id}.json").read_text(encoding="utf-8")
    assert '"schema": 1' in text
    assert '"name": "Readable"' in text
    assert json.loads(text) == profile_to_dict(saved)
