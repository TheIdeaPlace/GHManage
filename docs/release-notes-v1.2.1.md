# GHManage 1.2.1

GHManage is a desktop app for reading and managing your GitHub repositories from
a fast, keyboard-driven list.

This release fixes GHManage sometimes failing to start on Windows, with an
"Unhandled exception in script" box, on PCs where Windows checks every program
file before letting it run (#142).

## Fixed

- On Windows 11 with Smart App Control turned on, or on a PC whose organization
  sets an App Control policy, GHManage could stop before its window opened. The
  box said "An Application Control policy has blocked this file". Some of the
  files GHManage is built from weren't digitally signed, and Windows decides
  about unsigned files with an online check, so it could work one day and fail
  the next. Every program file in GHManage is now signed.
- If GHManage ever fails to start, the error is now written to `ghmanage.log`,
  with the full details, so it can be sent in a bug report. **Help → Open Log
  Folder** shows where that is. On Windows it's
  `%APPDATA%\ghmanage\logs\ghmanage.log`.

## Before you start

GHManage drives the [GitHub CLI](https://cli.github.com/), so install it and sign
in first:

```
gh auth login
```

GHManage never asks for or stores credentials of its own — every request goes
through `gh`.

## Updating

If you already have GHManage installed you do not need to download anything; this
version will arrive on its own. If you've turned off **Help → Automatic Updates**,
choose **Help → Check for Updates…** to get it.

## Downloads

| File | Use it if |
|------|-----------|
| `GHManage-win-Setup.exe` | Windows, installed and updating itself |
| `GHManage-win-Portable.zip` | Windows, a folder to run from anywhere, no install, no updates |
| `GHManage-osx.dmg` | macOS, drag to Applications |
| `GHManage-osx-Portable.zip` | macOS, unzip it yourself |

The remaining files (`*.nupkg`, `RELEASES`, `releases.win.json`,
`assets.win.json`, `releases.osx.json`, `assets.osx.json`) are the update feed
the installed app reads. Leave them alone.

## Requirements

- Windows 10 or 11, 64-bit — or an Apple Silicon Mac on macOS 11 or newer
- The [GitHub CLI](https://cli.github.com/), installed and authenticated with
  `gh auth login`
