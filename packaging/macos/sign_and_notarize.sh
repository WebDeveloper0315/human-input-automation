#!/usr/bin/env bash
# Sign, notarise and staple a macOS build.
#
# Runs only when signing credentials are present. Without them the release is
# still produced - unsigned - and is labelled as such. There is no mode in which
# this script pretends to have signed something it did not.
#
# Required environment (from CI secrets, never from the repository):
#   MACOS_SIGN_IDENTITY   "Developer ID Application: Name (TEAMID)"
#   MACOS_NOTARY_PROFILE  a notarytool keychain profile name
# or, for notarytool without a stored profile:
#   MACOS_NOTARY_APPLE_ID, MACOS_NOTARY_PASSWORD, MACOS_NOTARY_TEAM_ID
#
# Usage: packaging/macos/sign_and_notarize.sh dist/HumanInputAutomation.app dist/App.dmg
set -euo pipefail

APP_BUNDLE="${1:?path to the .app bundle is required}"
DMG="${2:-}"
ENTITLEMENTS="$(dirname "$0")/entitlements.plist"

if [[ -z "${MACOS_SIGN_IDENTITY:-}" ]]; then
  echo "MACOS_SIGN_IDENTITY is not set: leaving the build UNSIGNED."
  echo "Unsigned builds show Gatekeeper warnings and must be labelled as unsigned."
  exit 0
fi

echo "==> Signing $APP_BUNDLE"
codesign --force --deep --options runtime --timestamp \
  --entitlements "$ENTITLEMENTS" \
  --sign "$MACOS_SIGN_IDENTITY" "$APP_BUNDLE"
codesign --verify --strict --verbose=2 "$APP_BUNDLE"

if [[ -z "$DMG" ]]; then
  echo "==> No disk image given; signing only."
  exit 0
fi

echo "==> Signing $DMG"
codesign --force --timestamp --sign "$MACOS_SIGN_IDENTITY" "$DMG"

if [[ -n "${MACOS_NOTARY_PROFILE:-}" ]]; then
  NOTARY_ARGS=(--keychain-profile "$MACOS_NOTARY_PROFILE")
elif [[ -n "${MACOS_NOTARY_APPLE_ID:-}" ]]; then
  NOTARY_ARGS=(--apple-id "$MACOS_NOTARY_APPLE_ID"
               --password "$MACOS_NOTARY_PASSWORD"
               --team-id "$MACOS_NOTARY_TEAM_ID")
else
  echo "No notarisation credentials: the build is signed but NOT notarised."
  exit 0
fi

echo "==> Notarising"
xcrun notarytool submit "$DMG" "${NOTARY_ARGS[@]}" --wait

echo "==> Stapling"
xcrun stapler staple "$DMG"
xcrun stapler validate "$DMG"
spctl --assess --type open --context context:primary-signature -vv "$DMG"
echo "==> Signed, notarised and stapled."
