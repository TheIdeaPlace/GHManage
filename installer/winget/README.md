# winget manifest for `TheIdeaPlace.GHManage`

The three files here are the template for every GHManage version submitted to the
[Windows Package Manager community repository](https://github.com/microsoft/winget-pkgs)
(issue #137), and the record of every choice in them. The published manifests live in
winget-pkgs under `manifests/t/TheIdeaPlace/GHManage/<version>/`. Modelled on QuickMail's
package (`KellyLford.QuickMail`), minus the MSI questions, because GHManage ships only
Velopack's Setup.exe.

## What the choices mean

- **`InstallerType: exe`, Velopack's Setup.exe, `--silent`.** The only Windows installer
  GHManage ships. Measured on QuickMail's identical Velopack setup (its winget plan, Phase 1)
  and on GHManage's own releases (`winget-install-test.yml`): `Setup.exe --silent` installs
  per user to `%LocalAppData%\GHManage` in a few seconds, with no elevation and no UI, does
  not launch the app, makes the Start Menu shortcut, and writes one Add/Remove Programs row.
  Run over an existing install it overwrites it in place: no uninstall hook runs and the
  row is rewritten. That overwrite is the upgrade, so **`UpgradeBehavior: install`**, never
  `uninstallPrevious`. `winget uninstall` runs the row's `QuietUninstallString`,
  `Update.exe --uninstall --silent`.
- **`Scope: user`.** `vpk pack --instLocation PerUser`.
- **`AppsAndFeaturesEntries`: `DisplayName: GHManage`, `Publisher: Kelly Ford`,
  `ProductCode: GHManage`.** Velopack names the row's key after `--packId` and takes
  DisplayName from `--packTitle` and Publisher from `--packAuthors` (`ghmanage.yml`). For a
  row that is not an MSI's, winget's ProductCode is the key name, so winget lists the install
  as `ARP\User\X64\GHManage`. Velopack's self-updates keep the row's DisplayVersion current,
  so winget only offers an upgrade to a copy that is really behind. No `UpgradeCode`: there
  is no MSI. If `--packId`, `--packTitle` or `--packAuthors` ever change, change this entry
  and the locale's `Publisher` with them (`scripts/winget-manifest.ps1` checks the entry is
  this one).
- **One installer, `Architecture: x64`.** GHManage is built for x64 Windows only. Velopack's
  Setup.exe is an x86 PE image whatever it installs (measured for QuickMail), so the
  architecture is stated, never inferred from the binary, which is one reason this does not
  use wingetcreate, Komac or winget-releaser.
- **The installer is `GHManage-<version>-win-winget-Setup.exe`.** Every full release from
  1.2.0 on carries this byte-identical copy of `GHManage-win-Setup.exe`
  (`ghmanage.yml` makes it; the release job checks the two with `cmp`). Only the winget
  manifest points at it, so its download count on the release is the number of winget
  installs; the website keeps linking `GHManage-win-Setup.exe`. Same bytes, same signature.
  The URL carries the tag, so it stays valid for as long as the release exists, which
  winget-pkgs needs: it keeps older versions' manifests.
  (1.2.0 itself got the copy by hand, uploaded to its release after it was published.)
- **Releases without the copy (1.1.0 and earlier) use `GHManage-win-Setup.exe`.**
  `scripts/winget-release.ps1` falls back to it when the copy is missing and says so in the
  log. Their URL is just as stable; their winget installs just are not counted separately.
- **No `Dependencies: GitHub.cli`, by decision.** GHManage does everything through `gh`,
  but declaring it would make winget install the GitHub CLI first, whose package installs
  machine-wide and so may ask for elevation, and could add a second `gh` beside one from
  scoop or a zip. Users install `gh` themselves, as the user guide already says.
- **`Moniker: ghmanage`**, so `winget install ghmanage` works without the full id.
- **No `PrivacyUrl`.** GHManage has no privacy page; the field is optional.

## SmartScreen

Velopack's Setup.exe is signed (Azure Trusted Signing, "Kelly Ford"), but a new signer's
file has little reputation, and SmartScreen can still ask "Windows protected your PC"
before it runs. QuickMail measured that a winget install from a *local* manifest met
SmartScreen for its low-reputation installer; from the catalog the download is in a
different zone and whether the prompt appears was not measurable before publication.
GHManage's signed 1.1.0 and 1.2.0 Setup.exe both installed from a local manifest on a
Windows Server 2025 runner with no SmartScreen hold-up (install test, PR #138), but a
server image is not a desktop with SmartScreen's consumer settings. Check
it after the first version is in the catalog: on a machine that has never had GHManage,
`winget install ghmanage` and note whether a prompt appears and how a screen reader presents
it. An unattended install would wait on that prompt.

## Every release

Automatic. When a full `v*` tag's release is published, the `winget` job in `ghmanage.yml`
calls `.github/workflows/winget-submit.yml`, which:

1. skips the release if it is a draft or a pre-release, if winget-pkgs already has the
   version, or if a pull request for it is open;
2. runs `scripts/winget-release.ps1`: picks the release's installer (the winget copy, or the
   fallback above), downloads it, checks its hash against GitHub's digest, and calls
   `scripts/winget-manifest.ps1`, which fills these templates, strips their comments, and
   refuses to write a manifest that breaks the rules above;
3. runs `scripts/winget-submit.ps1`, which builds one commit with the three files on top of
   winget-pkgs' current master, points a branch in Kelly's fork at it, and opens the pull
   request (`New package: …` the first time, `Update: TheIdeaPlace.GHManage to <version>`
   after). All through the GitHub API: the fork is never synced, because syncing it after
   upstream changes its workflows needs the `workflow` scope, which the token does not have.
   It never pushes over a branch that already has an open pull request, which may carry fixes
   a moderator asked for.

Before that, the `winget-install-test` job installs the new release with winget from the
manifest the submission would send (so the winget-only copy is installed before it is
submitted), upgrades the previous release to it, and uninstalls it. If that fails, nothing
is submitted; the release itself stands.

Until `WINGET_TOKEN` exists, the automatic run writes and shows the manifests, warns that
nothing was submitted, and stays green.

A moderator then approves it. A failed submission leaves the release untouched: rerun the
job, or run **Submit to winget** by hand with the version, from `main` (the `winget`
environment admits only `main` and `v*` tags, dry runs included). With **dry_run** on (the
default) anyone can run it, and it only shows the manifests it would submit. Only Kelly can
run it for real, since the pull request is opened in his name.

By hand, the same way CI does it:

```
pwsh scripts/winget-release.ps1 -Version <v> -OutDir <folder>
winget validate --manifest <folder>
```

`scripts/winget-manifest.tests.ps1` runs on every push and pull request (the
`winget-manifest` job in `ghmanage.yml`). `.github/workflows/winget-install-test.yml` runs on
pull requests that change this folder or the winget scripts, and by hand: on a Windows
runner it installs the newest release fresh with `winget install --manifest`, uninstalls it,
installs the release before, upgrades it, and uninstalls again, checking the Add/Remove
Programs row, the install folder, the shortcut and `winget list` at each step.

Before the package is in the catalog, `winget upgrade` cannot see the installed copy (it
finds it through the catalog, so it says no installed package matches, even with
`--manifest`); the test upgrades with `winget install --manifest`, which runs the same
`Setup.exe --silent` over the old copy. Once the package is published, check
`winget upgrade ghmanage` on a machine with an older version installed.

## Setup (once)

1. The `winget` environment on TheIdeaPlace/GHManage, with deployment branches `main` and
   `v*` tags only. (Exists.)
2. `WINGET_TOKEN` in that environment: a classic personal access token of Kelly's with only
   the `public_repo` scope. A fine-grained token cannot open a pull request on
   microsoft/winget-pkgs. QuickMail's `WINGET_TOKEN` is the same kind of token and can be the
   same one. Classic tokens expire; when it does, the job fails with GitHub's "Bad
   credentials" and needs a new token in the same place.

   `public_repo` is not narrow: it is write access to every public repository Kelly owns or
   can push to. What keeps it in: only `main` and `v*` tag runs get it, both of which need
   Kelly's hands to change; the job runs nothing but checkout, the runner's own `gh`, and
   code-owned scripts; and no step prints it.
3. The first submission: run **Submit to winget** with the newest version and dry_run off.
   1.2.0 has the winget copy, so its manifest points at `GHManage-1.2.0-win-winget-Setup.exe`.
   The first pull request is a new package, so expect a moderator's review to take longer
   than an update's.
