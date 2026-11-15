#!/bin/bash
# ============================================================================
# Notarize and staple a GHManage macOS distributable
# ============================================================================
# Submits a .dmg (or .pkg / .zip) to Apple's notary service, waits for the
# verdict, and staples the ticket so the app validates offline -- on a laptop
# opening the download on a plane, or behind a firewall that blocks Apple's
# OCSP endpoint.
#
# Usage:
#   bash scripts/notarize_macos.sh <path-to-.dmg-.pkg-or-.zip>
#
# Credentials -- one of these three sets must be present, tried in this order.
#
#   notarytool keychain profile (what `vpk pack --notaryProfile` also uses):
#     NOTARY_PROFILE      Profile name stored by `notarytool store-credentials`
#     NOTARY_KEYCHAIN     Optional keychain holding it (CI uses a throwaway one)
#
#   App Store Connect API key:
#     NOTARY_KEY_PATH     Path to the API key's .p8 file
#     NOTARY_KEY_ID       The 10-character Key ID
#     NOTARY_ISSUER_ID    The issuer UUID from App Store Connect
#
#   Apple ID (fallback for local use):
#     NOTARY_APPLE_ID     Apple ID email
#     NOTARY_PASSWORD     App-specific password (NOT the account password)
#     NOTARY_TEAM_ID      Team ID, e.g. P887QF74N8
#
# Local default: on a Mac with the signing kit, nothing needs setting. When
# none of NOTARY_PROFILE, NOTARY_KEY_PATH or NOTARY_APPLE_ID is set and the
# kit's API key exists (~/.signing-kit/asc-api-key.p8, or $SIGNING_KIT/...),
# the script uses it, with Key ID 38ANZ53D9L and issuer
# d36bb41d-a198-401d-b36c-2e4fd15163e1 unless NOTARY_KEY_ID or
# NOTARY_ISSUER_ID say otherwise. To recreate the kit on a Mac, run
# `python3 signing/sync-secrets.py pull-kit` from
# kellylford/The-Idea-Place-Projects; its signing/README.md explains the kit.
# CI never uses this default: it passes NOTARY_PROFILE or NOTARY_KEY_* itself.
#
# Stapling note: `stapler` works on .app, .dmg and .pkg, but NOT on a bare
# executable or a .zip. A zip gets its ticket by way of the .app inside it
# having been stapled before it was zipped, which is what `vpk pack` does.
# ============================================================================

set -euo pipefail

if [ $# -ne 1 ]; then
    echo "Usage: $0 <path-to-.dmg-.pkg-or-.zip>"
    exit 2
fi

TARGET="$1"

if [ ! -e "$TARGET" ]; then
    echo "ERROR: not found: $TARGET"
    exit 1
fi

# ----------------------------------------------------------------------------
# Build credential arguments
# ----------------------------------------------------------------------------
CRED_ARGS=()

# The signing kit's App Store Connect API key, used only when the caller chose
# no credentials at all.
KIT_KEY="${SIGNING_KIT:-$HOME/.signing-kit}/asc-api-key.p8"
if [ -z "${NOTARY_PROFILE:-}" ] && [ -z "${NOTARY_KEY_PATH:-}" ] \
        && [ -z "${NOTARY_APPLE_ID:-}" ] && [ -f "$KIT_KEY" ]; then
    echo "Using the signing kit's API key: $KIT_KEY"
    NOTARY_KEY_PATH="$KIT_KEY"
    NOTARY_KEY_ID="${NOTARY_KEY_ID:-38ANZ53D9L}"
    NOTARY_ISSUER_ID="${NOTARY_ISSUER_ID:-d36bb41d-a198-401d-b36c-2e4fd15163e1}"
fi

if [ -n "${NOTARY_PROFILE:-}" ]; then
    echo "Using notarytool keychain profile: $NOTARY_PROFILE"
    CRED_ARGS=(--keychain-profile "$NOTARY_PROFILE")
    if [ -n "${NOTARY_KEYCHAIN:-}" ]; then
        CRED_ARGS+=(--keychain "$NOTARY_KEYCHAIN")
    fi

elif [ -n "${NOTARY_KEY_PATH:-}" ] && [ -n "${NOTARY_KEY_ID:-}" ] && [ -n "${NOTARY_ISSUER_ID:-}" ]; then
    if [ ! -f "$NOTARY_KEY_PATH" ]; then
        echo "ERROR: NOTARY_KEY_PATH set but file does not exist: $NOTARY_KEY_PATH"
        exit 1
    fi
    echo "Using App Store Connect API key (Key ID: $NOTARY_KEY_ID)"
    CRED_ARGS=(--key "$NOTARY_KEY_PATH" --key-id "$NOTARY_KEY_ID" --issuer "$NOTARY_ISSUER_ID")

elif [ -n "${NOTARY_APPLE_ID:-}" ] && [ -n "${NOTARY_PASSWORD:-}" ] && [ -n "${NOTARY_TEAM_ID:-}" ]; then
    echo "Using Apple ID credentials ($NOTARY_APPLE_ID)"
    CRED_ARGS=(--apple-id "$NOTARY_APPLE_ID" --password "$NOTARY_PASSWORD" --team-id "$NOTARY_TEAM_ID")

else
    echo "ERROR: No notarization credentials found."
    echo ""
    echo "Set one of:"
    echo "  NOTARY_PROFILE                                       (keychain profile)"
    echo "  NOTARY_KEY_PATH + NOTARY_KEY_ID + NOTARY_ISSUER_ID   (API key)"
    echo "  NOTARY_APPLE_ID + NOTARY_PASSWORD + NOTARY_TEAM_ID   (Apple ID)"
    echo "or put the signing kit at ${SIGNING_KIT:-$HOME/.signing-kit}"
    echo "(sync-secrets.py pull-kit, in kellylford/The-Idea-Place-Projects)."
    exit 1
fi

# ----------------------------------------------------------------------------
# Submit
# ----------------------------------------------------------------------------
echo ""
echo "========================================================================"
echo "SUBMITTING TO APPLE NOTARY SERVICE"
echo "========================================================================"
echo "File: $TARGET"
echo "This usually takes 2-15 minutes."
echo ""

SUBMIT_LOG=$(mktemp)
trap 'rm -f "$SUBMIT_LOG"' EXIT

# notarytool's exit code is swallowed deliberately: a rejection still prints a
# submission id, and that id is the only way to fetch the log that names the
# offending binary. The status check below is what decides success.
xcrun notarytool submit "$TARGET" "${CRED_ARGS[@]}" --wait 2>&1 | tee "$SUBMIT_LOG" || true

SUBMISSION_ID=$(grep -Eo '\bid: [0-9a-f-]{36}' "$SUBMIT_LOG" | head -1 | awk '{print $2}' || true)

if grep -q "status: Accepted" "$SUBMIT_LOG"; then
    echo ""
    echo "Notarization accepted."
else
    echo ""
    echo "========================================================================"
    echo "NOTARIZATION FAILED"
    echo "========================================================================"
    if [ -n "$SUBMISSION_ID" ]; then
        echo "Fetching the detailed log for submission $SUBMISSION_ID..."
        echo ""
        # This log names the exact offending binary and reason, which the
        # summary output above does not.
        xcrun notarytool log "$SUBMISSION_ID" "${CRED_ARGS[@]}" || true
    fi
    exit 1
fi

# ----------------------------------------------------------------------------
# Staple
# ----------------------------------------------------------------------------
echo ""
echo "Stapling the notarization ticket..."
xcrun stapler staple "$TARGET"
xcrun stapler validate "$TARGET"

echo ""
echo "========================================================================"
echo "NOTARIZED AND STAPLED: $TARGET"
echo "========================================================================"
echo ""
echo "Verify on a clean machine with:"
echo "  spctl --assess --type open --context context:primary-signature -v \"$TARGET\""
