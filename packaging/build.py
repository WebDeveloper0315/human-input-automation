"""Build the distributable artifact for the current platform.

One entry point for all three platforms:

    python packaging/build.py                # build for this platform
    python packaging/build.py --skip-icons   # reuse the committed icons

It runs PyInstaller against ``packaging/human-input-automation.spec``, then does
the platform-specific packaging step (AppImage, DMG, or leaving the Windows
directory for the installer), verifies the result actually runs, and writes
checksums.

It never signs or notarises implicitly: those need credentials and are handled
by the release workflow, which only attempts them when the secrets exist.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "packaging" / "human-input-automation.spec"
DIST = ROOT / "dist"
WORK = ROOT / "build" / "pyinstaller"

sys.path.insert(0, str(ROOT / "src"))
from human_input_automation.metadata import METADATA  # noqa: E402

IS_WINDOWS = sys.platform.startswith("win")
IS_MACOS = sys.platform == "darwin"


def platform_tag() -> str:
    if IS_WINDOWS:
        return "windows"
    if IS_MACOS:
        return "macos"
    return "linux"


def architecture_tag() -> str:
    """The architecture actually being built for - never assumed universal."""
    machine = platform.machine().lower()
    return {"amd64": "x64", "x86_64": "x64" if IS_WINDOWS else "x86_64"}.get(machine, machine)


def run(command: list[str], **kwargs: object) -> None:
    print(f"$ {' '.join(command)}", flush=True)
    subprocess.run(command, check=True, **kwargs)  # type: ignore[arg-type]


def build_icons() -> None:
    run([sys.executable, str(ROOT / "packaging" / "common" / "make_icons.py")])


def build_bundle() -> Path:
    """Run PyInstaller and return the produced directory or .app bundle."""
    if DIST.exists():
        shutil.rmtree(DIST)
    run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            str(SPEC),
            "--noconfirm",
            "--distpath",
            str(DIST),
            "--workpath",
            str(WORK),
            "--log-level",
            "WARN",
        ]
    )
    bundle = DIST / (f"{METADATA.executable}.app" if IS_MACOS else METADATA.executable)
    if not bundle.exists():
        raise SystemExit(f"PyInstaller did not produce {bundle}")
    return bundle


def executable_in(bundle: Path) -> Path:
    if IS_MACOS and bundle.suffix == ".app":
        return bundle / "Contents" / "MacOS" / METADATA.executable
    name = f"{METADATA.executable}.exe" if IS_WINDOWS else METADATA.executable
    return bundle / name


def verify(executable: Path) -> None:
    """Prove the artifact runs before it is shipped.

    ``--smoke-test`` opens the real window and round-trips a profile; it sends
    no keyboard or mouse input, so it is safe in CI.
    """
    environment = dict(os.environ)
    environment.setdefault("QT_QPA_PLATFORM", "offscreen")
    run([str(executable), "--version"])
    run([str(executable), "--smoke-test"], env=environment)
    print("artifact verification passed", flush=True)


def build_appimage(bundle: Path) -> Path | None:
    """Package the Linux bundle as an AppImage, if appimagetool is available."""
    tool = shutil.which("appimagetool")
    if tool is None:
        print("appimagetool not found: skipping the AppImage step", flush=True)
        return None

    appdir = ROOT / "build" / f"{METADATA.executable}.AppDir"
    if appdir.exists():
        shutil.rmtree(appdir)
    (appdir / "usr").mkdir(parents=True)
    shutil.copytree(bundle, appdir / "usr" / "bin")

    icons = ROOT / "src" / "human_input_automation" / "resources" / "icons"
    shutil.copy(icons / "app.png", appdir / f"{METADATA.slug}.png")
    applications = appdir / "usr" / "share" / "applications"
    applications.mkdir(parents=True)
    desktop = ROOT / "packaging" / "linux" / f"{METADATA.slug}.desktop"
    shutil.copy(desktop, appdir / f"{METADATA.slug}.desktop")
    shutil.copy(desktop, applications / f"{METADATA.slug}.desktop")
    shutil.copy(ROOT / "packaging" / "linux" / "AppRun", appdir / "AppRun")
    (appdir / "AppRun").chmod(0o755)

    output = DIST / METADATA.artifact_name(platform_tag(), architecture_tag(), ".AppImage")
    environment = dict(os.environ, ARCH=platform.machine())
    run([tool, "--no-appstream", str(appdir), str(output)], env=environment)
    return output


def build_dmg(bundle: Path) -> Path | None:
    """Wrap the .app in a DMG using hdiutil (macOS only)."""
    if not IS_MACOS or shutil.which("hdiutil") is None:
        return None
    output = DIST / METADATA.artifact_name(platform_tag(), architecture_tag(), ".dmg")
    staging = ROOT / "build" / "dmg"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    shutil.copytree(bundle, staging / bundle.name, symlinks=True)
    (staging / "Applications").symlink_to("/Applications")
    run(
        [
            "hdiutil",
            "create",
            "-volname",
            METADATA.name,
            "-srcfolder",
            str(staging),
            "-ov",
            "-format",
            "UDZO",
            str(output),
        ]
    )
    return output


def archive_directory(bundle: Path) -> Path:
    """Zip the plain application directory (Windows, and as a Linux fallback)."""
    base = DIST / METADATA.artifact_name(platform_tag(), architecture_tag(), "")
    archive = shutil.make_archive(str(base), "zip", root_dir=bundle.parent, base_dir=bundle.name)
    return Path(archive)


def write_checksums(paths: list[Path]) -> Path:
    """SHA256SUMS, computed from the artifacts - never typed by hand."""
    lines = []
    for path in sorted(paths):
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {path.name}")
    output = DIST / "SHA256SUMS"
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines), flush=True)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-icons", action="store_true", help="reuse the committed icons")
    parser.add_argument("--skip-verify", action="store_true", help="skip the artifact smoke test")
    arguments = parser.parse_args()

    if not arguments.skip_icons:
        build_icons()

    bundle = build_bundle()
    executable = executable_in(bundle)
    if not arguments.skip_verify:
        verify(executable)

    artifacts: list[Path] = []
    if IS_MACOS:
        dmg = build_dmg(bundle)
        if dmg is not None:
            artifacts.append(dmg)
    elif IS_WINDOWS:
        artifacts.append(archive_directory(bundle))
    else:
        appimage = build_appimage(bundle)
        artifacts.append(appimage if appimage is not None else archive_directory(bundle))

    checksums = write_checksums(artifacts)
    print(f"\nArtifacts in {DIST}:", flush=True)
    for path in [*artifacts, checksums]:
        size = path.stat().st_size / 1_048_576
        print(f"  {path.name}  ({size:.1f} MB)" if path != checksums else f"  {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
