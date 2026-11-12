---
name: release
description: Cut a new GHManage release — pick the version, bump version.py, write the release notes, commit, push to main, tag, watch the CI build, and check the published release. Use when the user asks to make, cut, ship, tag or publish a release or new version of GHManage.
---

# Releasing GHManage

A release is a `v*` tag on `main`. Pushing the tag makes `.github/workflows/ghmanage.yml`
build, sign and package the Windows and macOS apps and publish the GitHub Release. The
installed apps update themselves from that release, so **a pushed tag reaches every user**.
Asking for a release authorizes pushing to `main` and pushing the tag; nothing else
outward-facing (no force pushes, no moving or deleting a pushed tag) without asking.

## 1. Check what is going out

- `git fetch origin` and confirm the release commit will fast-forward `origin/main`
  (`git rev-list --count HEAD..origin/main` is `0`). If `main` has moved, rebase first.
- The working tree holds only what belongs in the release. Commit the feature work on
  its own first, with a message describing the change.
- `git log --oneline <last tag>..HEAD` — this is what the notes must cover.
- `python -m py_compile ghviewer.py gh_data.py updater.py` passes, and so does
  `python -m pytest -q`.
- If the user has not tried the change in the running app, offer to launch it first
  (`python ghviewer.py` from the checkout).

## 2. Pick the version

Plain SemVer, three parts — `vpk pack` rejects four. Look at `git tag --sort=-creatordate`
and the "Current versions" list in `COPILOT.md` for precedent:

- **Minor** (0.7.0 → 0.8.0) — a new view, or a change to how the app is laid out or driven.
- **Patch** (0.7.0 → 0.7.1) — fixes, small additions to an existing feature, build or
  signing changes.

State the version you picked and why in one line; don't stop to ask unless it is
genuinely unclear.

## 3. Bump and write the notes

1. `version.py` → `__version__ = "X.Y.Z"`. CI fails the build if this and the tag disagree.
2. `docs/release-notes-vX.Y.Z.md` — **required**; the workflow uses it as both the vpk
   release notes and the release body, and a missing file fails the release.
   - Start from the most recent notes file and keep its shape: `# GHManage X.Y.Z`, the
     one-line description of the app, a short paragraph on what this release is about,
     a section per change, then the standing sections (Before you start / Updating /
     Downloads / Requirements) carried over and corrected.
   - Write for people using the app, not for the code: what they can now do, which keys,
     what behaves differently. Plain prose, no marketing, no internals.
   - Every key named must work as described, on every platform the release ships for.
     Call out Mac differences (e.g. `fn` for function keys).
   - The Downloads table must list exactly the files the workflow publishes.
3. `COPILOT.md` → add a line to "Current versions"; update any section the change made
   stale.

## 4. Commit, push, tag

```bash
git add -A
git commit -m "<what changed> (vX.Y.Z)"
git push origin HEAD:main
git tag vX.Y.Z
git push origin vX.Y.Z
```

Push `main` before the tag, so the tag never points at a commit `main` doesn't have.
From a worktree branch, `HEAD:main` pushes the branch to `main`; it must be a
fast-forward — never force it.

## 5. Watch the build

```bash
gh run list --workflow ghmanage.yml --limit 3
gh run watch <run-id> --exit-status
```

The tag run takes a while (Windows signing, macOS notarization). Run the watch in the
background and carry on. On failure: `gh run view <run-id> --log-failed`, report the
cause, and propose the fix. Re-running a failed job is fine. Moving or deleting the tag,
or deleting a release, needs the user's go-ahead.

## 6. Check the release

`gh release view vX.Y.Z --json name,isDraft,assets --jq '.name, .isDraft, [.assets[].name]'`

- Name is `GHManage vX.Y.Z`, not a draft, and marked Latest.
- Assets include `GHManage-win-Setup.exe`, `GHManage-X.Y.Z-win-winget-Setup.exe` (the
  winget-only copy, full releases only), `GHManage-win-Portable.zip`,
  `GHManage-osx.dmg`, `GHManage-osx-Portable.zip`, and the update feed (`*.nupkg`,
  `RELEASES`, `releases.win.json`, `assets.win.json`, `releases.osx.json`,
  `assets.osx.json`).
- Nothing else — no files from the repository itself (v0.7.1 once shipped its `assets/`
  folder by accident).
- The tag run's `winget` job opened a winget-pkgs pull request for `TheIdeaPlace.GHManage`
  (its log ends with "Opened https://github.com/microsoft/winget-pkgs/pull/…"), or said why
  it skipped. A moderator merges it later; nothing to do unless validation fails there.
  See `installer/winget/README.md`.

## 7. Finish

Report the version, the release URL, and anything not verified. Offer to refresh the
projects page on theideaplace.net with the `projects-page` skill.
