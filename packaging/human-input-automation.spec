# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification.

One spec for all three platforms; the platform-specific parts (icon format, the
macOS bundle, the console flag) branch on ``sys.platform``.

Two design points worth knowing:

* **Hidden imports live here, not in the application.** The adapters import
  pynput, pywinctl and Xlib lazily and by platform, which is deliberate - the
  core must stay importable on a headless machine. PyInstaller cannot see the
  backend modules those libraries select at runtime, so they are declared below
  instead of being force-imported in application code.
* **Only the current platform's backends are collected.** Bundling the Windows
  and macOS backends into a Linux build would add weight for code that can
  never run there.

Build with:  pyinstaller packaging/human-input-automation.spec --noconfirm
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

SPEC_DIRECTORY = Path(SPECPATH).resolve()
PROJECT_ROOT = SPEC_DIRECTORY.parent
PACKAGE_ROOT = PROJECT_ROOT / "src" / "human_input_automation"
ICON_DIRECTORY = PACKAGE_ROOT / "resources" / "icons"

sys.path.insert(0, str(PROJECT_ROOT / "src"))
from human_input_automation.metadata import METADATA  # noqa: E402

IS_WINDOWS = sys.platform.startswith("win")
IS_MACOS = sys.platform == "darwin"
IS_LINUX = not IS_WINDOWS and not IS_MACOS

# Resources that must exist inside the bundle at their package-relative paths.
datas = [
    (str(ICON_DIRECTORY), "human_input_automation/resources/icons"),
    (str(PACKAGE_ROOT / "py.typed"), "human_input_automation"),
]

# Backends the libraries import dynamically, per platform.
hiddenimports = [
    "human_input_automation.adapters.pynput_input",
    "human_input_automation.adapters.pynput_hotkey",
    "human_input_automation.adapters.pywinctl_windows",
    "human_input_automation.adapters.x11_windows",
    "human_input_automation.adapters.screens",
]
if IS_WINDOWS:
    hiddenimports += ["pynput.keyboard._win32", "pynput.mouse._win32", "pywinctl", "pymonctl"]
elif IS_MACOS:
    hiddenimports += [
        "pynput.keyboard._darwin",
        "pynput.mouse._darwin",
        "pywinctl",
        "pymonctl",
        # Optional: used only to *check* macOS permissions, never to bypass them.
        "ApplicationServices",
        "Quartz",
    ]
else:
    hiddenimports += [
        "pynput.keyboard._xorg",
        "pynput.mouse._xorg",
        "Xlib",
        "Xlib.display",
        "Xlib.ext.xtest",
        "pymonctl",
    ]
    hiddenimports += collect_submodules("Xlib.ext")

# Development-only and unused-subsystem modules. Excluding these keeps the
# bundle to what the application actually runs.
excludes = [
    "pytest",
    "_pytest",
    "mypy",
    "ruff",
    "PyInstaller",
    "setuptools",
    "pip",
    "tkinter",
    "test",
    "distutils",
    "IPython",
    "numpy",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtQuick",
    "PySide6.QtQuick3D",
    "PySide6.QtQml",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtPositioning",
    "PySide6.QtSql",
    "PySide6.QtTest",
    "PySide6.QtDesigner",
    "PySide6.QtHelp",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtWebSockets",
    "PySide6.QtWebChannel",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "shiboken6.support",
]

icon_file = None
if IS_WINDOWS and (ICON_DIRECTORY / "app.ico").is_file():
    icon_file = str(ICON_DIRECTORY / "app.ico")
elif IS_MACOS and (ICON_DIRECTORY / "app.icns").is_file():
    icon_file = str(ICON_DIRECTORY / "app.icns")
elif (ICON_DIRECTORY / "app.png").is_file():
    icon_file = str(ICON_DIRECTORY / "app.png")

analysis = Analysis(
    [str(SPEC_DIRECTORY / "common" / "launcher.py")],
    pathex=[str(PROJECT_ROOT / "src")],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    # Collect only the Qt plugins this application uses. Notably this drops the
    # GTK platform theme, which otherwise drags the whole of GTK 3 into the
    # bundle for a Qt Widgets application that never uses it.
    hooksconfig={
        "PySide6": {
            "qt_plugins": [
                "platforms",
                "platforminputcontexts",
                "styles",
                "imageformats",
                "iconengines",
                "xcbglintegrations",
                "egldeviceintegrations",
                "wayland-decoration-client",
                "wayland-graphics-integration-client",
                "wayland-shell-integration",
                "generic",
            ]
        }
    },
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

# Qt subsystems this application does not use. The module excludes above stop
# the Python bindings being imported; these patterns drop the shared libraries
# that the Qt hook would otherwise copy alongside them.
UNUSED_QT_LIBRARIES = (
    "libQt6Quick",
    "libQt6Qml",
    "libQt6QmlModels",
    "libQt6QuickWidgets",
    "libQt6WebEngine",
    "libQt6Pdf",
    "libQt6Designer",
    "libQt6Charts",
    "libQt6DataVisualization",
    "libQt6Multimedia",
    "libQt6Sensors",
    "libQt6Positioning",
    "libQt6Bluetooth",
    "libQt6Nfc",
    "libQt6Sql",
    "libQt6Test",
    "libQt6Help",
    "Qt6Quick",
    "Qt6Qml",
)

# The GTK platform theme makes a Qt Widgets application look native on GNOME,
# at the cost of bundling all of GTK 3 (~13 MB). Qt falls back to its own theme
# when the plugin is absent, which is the right trade for a distributable
# artifact. Drop the plugin and the libraries only it needs.
UNUSED_QT_PLUGIN_DIRECTORIES = ("platformthemes",)
GTK_LIBRARIES = ("libgtk-3", "libgdk-3", "libgdk_pixbuf", "libglycin", "libgailutil")


def _is_unused(destination: str) -> bool:
    path = Path(destination)
    name = path.name
    if any(name.startswith(prefix) for prefix in UNUSED_QT_LIBRARIES + GTK_LIBRARIES):
        return True
    return any(part in UNUSED_QT_PLUGIN_DIRECTORIES for part in path.parts)


analysis.binaries = TOC(
    [entry for entry in analysis.binaries if not _is_unused(entry[0])]
)
analysis.datas = TOC([entry for entry in analysis.datas if not _is_unused(entry[0])])

pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name=METADATA.executable,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # A GUI application: no console window on Windows. The headless commands
    # still work when launched from a terminal.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    # Signing identity comes from the environment in CI, never from this file.
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_file,
)

collection = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=METADATA.executable,
)

if IS_MACOS:
    app = BUNDLE(
        collection,
        name=f"{METADATA.executable}.app",
        icon=icon_file,
        bundle_identifier=METADATA.identifier,
        version=METADATA.version,
        info_plist={
            "CFBundleName": METADATA.executable,
            "CFBundleDisplayName": METADATA.name,
            "CFBundleShortVersionString": METADATA.version,
            "CFBundleVersion": METADATA.version,
            "CFBundleIdentifier": METADATA.identifier,
            "NSHumanReadableCopyright": METADATA.publisher,
            "LSMinimumSystemVersion": "11.0",
            "LSApplicationCategoryType": "public.app-category.utilities",
            "NSHighResolutionCapable": True,
            # The one privacy key this application genuinely needs. Window
            # enumeration, activation and focus verification go through
            # AppleScript to System Events (pywinctl's macOS backend), which is
            # an Apple Event: without this key macOS refuses the request
            # outright rather than prompting. Accessibility and Input
            # Monitoring are granted in System Settings and need no key, and no
            # camera/microphone/location/contacts/files key is declared because
            # the application does not use any of them.
            "NSAppleEventsUsageDescription": (
                "Human Input Automation asks System Events to list and focus "
                "the window you select, so automation goes to the application "
                "you chose and not to whatever happens to be in front."
            ),
        },
    )
