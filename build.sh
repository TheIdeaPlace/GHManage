#!/bin/bash
# ── GHManage macOS build script ───────────────────────────────────────
# The counterpart to build.bat. Run from the repo root.
#
# Usage:
#   ./build.sh              — build dist/GHManage.app
#   ./build.sh installer    — also pack the Velopack .pkg, portable zip,
#                             update feed, and the drag-to-Applications DMG
#   ./build.sh clean        — remove build artifacts first, then build
#
# Apple Silicon only. wxPython and velopack both publish per-architecture
# wheels with no universal2 build, so a fat binary is not available without
# building both from source; see docs/INSTALLER.md.
#
# The build is --onedir, not --onefile, for the same reason as Windows:
# Velopack replaces an app folder in place, and a onefile binary re-extracts
# the whole bundle on every launch — including the short-lived hook processes
# Velopack runs during an update — and makes deltas worthless.
#
# ── Signing (opt-in, exactly like the Windows Azure gate) ─────────────
#   GHM_SIGN_CODE=1          Sign with a Developer ID Application certificate
#   GHM_NOTARIZE=1           Notarize and staple (implies GHM_SIGN_CODE=1)
#   GHM_SIGNING_IDENTITY     "Developer ID Application: Name (TEAMID)"
#   GHM_INSTALLER_IDENTITY   "Developer ID Installer: Name (TEAMID)"
#   GHM_KEYCHAIN             Keychain to search (CI uses a throwaway one)
#   GHM_NOTARY_PROFILE       Existing notarytool profile name. If unset and
#                            NOTARY_KEY_* are set, one is created below.
#   NOTARY_KEY_PATH / NOTARY_KEY_ID / NOTARY_ISSUER_ID
#                            App Store Connect API key, used to create the
#                            profile and to notarize the DMG.
#
# With nothing set, the build produces an ad-hoc signed app: it runs on the
# machine that built it, and macOS refuses to open it after a download. That
# is the right default for local work and useless for publishing.
# ─────────────────────────────────────────────────────────────────────

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

APP_NAME="GHManage"
APP_BUNDLE="dist/$APP_NAME.app"
BUNDLE_ID="com.ghmanage.app"

if [ "$(uname -s)" != "Darwin" ]; then
    echo "Error: build.sh builds the macOS app. On Windows use build.bat."
    exit 1
fi

if [ "$(uname -m)" != "arm64" ]; then
    echo "Error: expected an Apple Silicon Mac (arm64), got $(uname -m)."
    echo "       Releases are Apple Silicon only. See docs/INSTALLER.md."
    exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
    echo "Error: python3 not found. Install Python 3.9+ and retry."
    exit 1
fi

MODE="${1:-}"

if [ "$MODE" = "clean" ]; then
    echo "Cleaning build artifacts..."
    rm -rf dist build "$APP_NAME.spec"
    echo "Done."
    MODE=""
fi

# ── Virtual environment ───────────────────────────────────────────────
if [ ! -d .venv ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

VENV_PY=".venv/bin/python"
if [ ! -x "$VENV_PY" ]; then
    echo "Error: $VENV_PY not found. The venv is broken; delete .venv and retry."
    exit 1
fi
echo "Using venv: $(cd .venv && pwd)"

echo "Installing dependencies..."
"$VENV_PY" -m pip install --upgrade pip
"$VENV_PY" -m pip install -r requirements.txt
"$VENV_PY" -m pip install pyinstaller

# Read the version from version.py so there is one source of truth.
APP_VERSION=$("$VENV_PY" -c "from version import __version__; print(__version__)")
if [ -z "$APP_VERSION" ]; then
    echo "Error: could not read version from version.py."
    exit 1
fi
echo "Building $APP_NAME $APP_VERSION..."

# ── PyInstaller ───────────────────────────────────────────────────────
# --windowed produces the .app bundle (and suppresses the console), which is
# what Velopack packages on macOS.
#
# --hidden-import velopack: updater.py imports it lazily inside functions so
# the app still runs from source without it, which hides it from PyInstaller.
# --hidden-import yaml: same reason — gh_data imports it inside
# _parse_dispatch_spec, so it is only needed when setting up a manual run.
# Neither omission fails the build; both fail at runtime, in the packaged app
# only, which is why they are spelled out here and in build.bat.
# --hidden-import wx.dataview: the macOS item list. ghviewer imports it behind
# an `if IS_MAC`, and a missing wx.dataview would take the whole app down at
# startup rather than degrade — spelled out so it cannot be dropped.
"$VENV_PY" -m PyInstaller --windowed --onedir --name "$APP_NAME" \
    --icon assets/ghmanage.icns \
    --osx-bundle-identifier "$BUNDLE_ID" \
    --hidden-import velopack --hidden-import yaml \
    --hidden-import wx.dataview launch.py -y

if [ ! -d "$APP_BUNDLE" ]; then
    echo "Error: PyInstaller did not produce $APP_BUNDLE."
    exit 1
fi

# ── Info.plist ────────────────────────────────────────────────────────
# PyInstaller's command line has no equivalent of --version-file, so the
# bundle ships CFBundleShortVersionString "0.0.0" unless it is set here. That
# string is what Finder's Get Info shows and what a user reads back when asked
# which build they are running.
PLIST="$APP_BUNDLE/Contents/Info.plist"
plist_set() {
    /usr/libexec/PlistBuddy -c "Set :$1 $2" "$PLIST" 2>/dev/null \
        || /usr/libexec/PlistBuddy -c "Add :$1 $3 $2" "$PLIST"
}
plist_set CFBundleShortVersionString "$APP_VERSION" string
plist_set CFBundleVersion "$APP_VERSION" string
plist_set NSHumanReadableCopyright "Copyright (c) Kelly Ford. MIT License." string
plist_set NSHighResolutionCapable true bool
# Velopack's updater needs to write next to the bundle and request elevation,
# neither of which the App Sandbox permits, and GHManage shells out to `gh`,
# which a sandbox would block. Recorded here so nobody adds the entitlement.
plist_set LSMinimumSystemVersion "11.0" string
echo "Stamped Info.plist with version $APP_VERSION."

# Re-sign after editing Info.plist. PyInstaller ad-hoc signs the bundle it
# builds — on Apple Silicon an unsigned binary will not run at all — and the
# plist is covered by that signature, so the edits above invalidate it:
#   codesign --verify => "invalid Info.plist (plist or signature have been
#   modified)"
# macOS then refuses to launch the app, reporting it as damaged, which reads
# as a broken build rather than a broken signature. Ad-hoc is the right level
# here; when GHM_SIGN_CODE=1, sign_macos.sh replaces this below with the real
# Developer ID signature.
codesign --force --sign - "$APP_BUNDLE"
codesign --verify --verbose=2 "$APP_BUNDLE" 2>&1 | tail -2

if [ "$MODE" != "installer" ]; then
    echo ""
    echo "Build complete: $APP_BUNDLE"
    echo "Run './build.sh installer' to also pack the installer and DMG."
    exit 0
fi

# ── Signing setup ─────────────────────────────────────────────────────
SIGN_CODE="${GHM_SIGN_CODE:-0}"
NOTARIZE="${GHM_NOTARIZE:-0}"
if [ "$NOTARIZE" = "1" ]; then
    SIGN_CODE=1
fi

if [ "$SIGN_CODE" = "1" ]; then
    # Sign the bundle BEFORE vpk pack, and pass --signDisableDeep below.
    # Velopack's own signing path uses `codesign --deep`, which Apple
    # deprecated: it applies the app's entitlements to every nested binary and
    # silently skips code it does not recognise. sign_macos.sh signs
    # inside-out instead, which is what a wxPython bundle's ~100 nested
    # libraries need. Velopack then copies the bundle with `cp -a`, preserving
    # these signatures, and signs only the UpdateMac binary it injects plus
    # the outer bundle.
    echo ""
    echo "Signing the app bundle (inside-out, hardened runtime)..."
    bash scripts/sign_macos.sh "$APP_BUNDLE"
else
    echo ""
    echo "Code signing disabled. Set GHM_SIGN_CODE=1 to enable."
    echo "  The app keeps PyInstaller's ad-hoc signature: it runs here, and"
    echo "  macOS refuses to open it after a download."
fi

# A notarytool keychain profile is the only credential form `vpk pack` accepts,
# so derive one from the API key when the caller has not supplied a profile.
NOTARY_PROFILE="${GHM_NOTARY_PROFILE:-}"
if [ "$NOTARIZE" = "1" ] && [ -z "$NOTARY_PROFILE" ]; then
    if [ -n "${NOTARY_KEY_PATH:-}" ] && [ -n "${NOTARY_KEY_ID:-}" ] && [ -n "${NOTARY_ISSUER_ID:-}" ]; then
        NOTARY_PROFILE="ghmanage-notary"
        echo "Storing notarytool credentials as profile '$NOTARY_PROFILE'..."
        xcrun notarytool store-credentials "$NOTARY_PROFILE" \
            --key "$NOTARY_KEY_PATH" \
            --key-id "$NOTARY_KEY_ID" \
            --issuer "$NOTARY_ISSUER_ID" \
            ${GHM_KEYCHAIN:+--keychain "$GHM_KEYCHAIN"}
    else
        echo "Error: GHM_NOTARIZE=1 but no notarization credentials."
        echo "       Set GHM_NOTARY_PROFILE, or NOTARY_KEY_PATH + NOTARY_KEY_ID"
        echo "       + NOTARY_ISSUER_ID. See scripts/notarize_macos.sh."
        exit 1
    fi
fi

# ── Velopack packaging ────────────────────────────────────────────────
# vpk is a .NET global tool, not a Python package.
if ! command -v vpk >/dev/null 2>&1; then
    echo "Error: vpk not found. Install it with: dotnet tool install -g vpk"
    exit 1
fi

VPK_ARGS=(
    pack
    --packId "$APP_NAME"
    --packVersion "$APP_VERSION"
    --packDir "$APP_BUNDLE"
    --mainExe "$APP_NAME"
    --packTitle "$APP_NAME"
    --packAuthors "Kelly Ford"
    --icon assets/ghmanage.icns
    --outputDir installer/Releases
)

if [ "$SIGN_CODE" = "1" ]; then
    # The file is named .entitlements, not .plist, because vpk validates the
    # extension and refuses anything else: "--signEntitlements does not have an
    # .entitlements extension". codesign itself does not care.
    VPK_ARGS+=(--signDisableDeep --signEntitlements assets/GHManage.entitlements)
    [ -n "${GHM_SIGNING_IDENTITY:-}" ] && VPK_ARGS+=(--signAppIdentity "$GHM_SIGNING_IDENTITY")
    [ -n "${GHM_INSTALLER_IDENTITY:-}" ] && VPK_ARGS+=(--signInstallIdentity "$GHM_INSTALLER_IDENTITY")
    [ -n "${GHM_KEYCHAIN:-}" ] && VPK_ARGS+=(--keychain "$GHM_KEYCHAIN")
    [ -n "$NOTARY_PROFILE" ] && VPK_ARGS+=(--notaryProfile "$NOTARY_PROFILE")
fi

# Release notes are optional locally and required in CI, where the tag names
# the file.
NOTES="docs/release-notes-v$APP_VERSION.md"
if [ -f "$NOTES" ]; then
    VPK_ARGS+=(--releaseNotes "$NOTES")
fi

echo ""
echo "Packing the Velopack installer and update feed..."
vpk "${VPK_ARGS[@]}"

# ── DMG ───────────────────────────────────────────────────────────────
GHM_SIGN_CODE="$SIGN_CODE" \
GHM_NOTARIZE="$NOTARIZE" \
NOTARY_PROFILE="$NOTARY_PROFILE" \
NOTARY_KEYCHAIN="${GHM_KEYCHAIN:-}" \
    bash scripts/make_dmg.sh

echo ""
echo "========================================================================"
echo "Build complete: $APP_NAME $APP_VERSION"
echo "========================================================================"
ls -la installer/Releases
echo ""
echo "Note: vpk overwrites GHManage-osx-Setup.pkg on each pack. To test an"
echo "upgrade, copy the old .pkg aside before packing the new version."
