<#
.SYNOPSIS
    Writes the three winget manifests for one GHManage release from the template in
    installer/winget/.

.DESCRIPTION
    The template is the record of every choice in GHManage's winget package (see
    installer/winget/README.md). This fills its placeholders, strips its explanatory comments
    (keeping each file's schema line, as published manifests do), and refuses to write
    anything that breaks the rules those choices depend on: Velopack's Setup.exe as an exe
    installer with --silent, user scope, the one ProductCode GHManage (Velopack's Add/Remove
    Programs key), no UpgradeCode, and an InstallerUrl on this release's tag.

    Deliberately not wingetcreate, Komac or winget-releaser; see installer/winget/README.md.

    Used by scripts/winget-release.ps1 (and so by .github/workflows/winget-submit.yml and
    winget-install-test.yml), and by hand the same way.

.PARAMETER InstallerAsset
    The release asset the manifest installs: GHManage-<Version>-win-winget-Setup.exe, the
    winget-only copy, or GHManage-win-Setup.exe for a release that predates the copy.

.EXAMPLE
    pwsh scripts/winget-manifest.ps1 -Version 1.2.0 -InstallerAsset GHManage-1.2.0-win-winget-Setup.exe -Sha256 4bed... -ReleaseDate 2026-11-11 -OutDir out/1.2.0
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $Version,
    [Parameter(Mandatory)] [string] $InstallerAsset,
    [Parameter(Mandatory)] [string] $Sha256,
    [Parameter(Mandatory)] [string] $ReleaseDate,
    [Parameter(Mandatory)] [string] $OutDir,
    [string] $TemplateDir = (Join-Path $PSScriptRoot '..' 'installer' 'winget')
)

$ErrorActionPreference = 'Stop'

if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw "Version '$Version' is not X.Y.Z (no leading v)." }
$allowed = "GHManage-$Version-win-winget-Setup.exe", 'GHManage-win-Setup.exe'
if ($InstallerAsset -cnotin $allowed) {
    throw "InstallerAsset '$InstallerAsset' is not $($allowed -join ' or ')."
}
if ($Sha256 -notmatch '^[0-9A-Fa-f]{64}$') { throw "'$Sha256' is not a SHA256 hash." }
if ($ReleaseDate -notmatch '^\d{4}-\d{2}-\d{2}$') { throw "ReleaseDate '$ReleaseDate' is not YYYY-MM-DD." }

$id = 'TheIdeaPlace.GHManage'
$files = "$id.yaml", "$id.installer.yaml", "$id.locale.en-US.yaml"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

foreach ($name in $files) {
    $source = Join-Path $TemplateDir $name
    $kept = foreach ($line in (Get-Content -LiteralPath $source -Encoding utf8)) {
        # Keep the schema line; drop every other comment line. Only column-0 '#' lines: an
        # indented one could be text inside the Description block, which must survive, so
        # the templates keep every comment at column 0.
        if ($line -match '^#' -and $line -notmatch '^# yaml-language-server:') { continue }
        $line.TrimEnd()
    }
    $text = ($kept -join "`n") + "`n"
    $text = $text.Replace('<VERSION>', $Version).
                  Replace('<INSTALLER-ASSET>', $InstallerAsset).
                  Replace('<SHA256>', $Sha256.ToUpperInvariant()).
                  Replace('<RELEASE-DATE>', $ReleaseDate)

    if ($text -match '<[A-Z0-9-]+>') { throw "$name still has a placeholder: $($Matches[0])" }
    if ($text -notmatch "(?m)^PackageIdentifier: $([regex]::Escape($id))$") { throw "$name is not for $id." }
    if ($text -notmatch "(?m)^PackageVersion: $([regex]::Escape($Version))$") { throw "$name has the wrong PackageVersion." }

    if ($name -like '*.installer.yaml') {
        # The rules installer/winget/README.md explains. Breaking any of them gives users
        # phantom upgrades, a duplicate install, or an install that waits on a wizard.
        if ($text -match 'UpgradeCode') { throw 'Installer manifest has an UpgradeCode.' }
        if ($text -match '(?i)\.msi\b') { throw 'Installer manifest points at an MSI; GHManage ships only Setup.exe.' }
        $productCodes = @([regex]::Matches($text, '(?m)^\s*ProductCode:.*$') | ForEach-Object { $_.Value.Trim() })
        if ($productCodes.Count -ne 1 -or $productCodes[0] -ne 'ProductCode: GHManage') {
            throw "Installer manifest must have exactly one ProductCode, GHManage, in AppsAndFeaturesEntries; found: $($productCodes -join ', ')"
        }
        foreach ($required in 'InstallerType: exe', 'Scope: user', 'UpgradeBehavior: install',
                               '  Silent: --silent', '  SilentWithProgress: --silent',
                               '- Architecture: x64', '  Publisher: Kelly Ford', '- DisplayName: GHManage') {
            if ($text -notmatch "(?m)^$([regex]::Escape($required))$") { throw "Installer manifest is missing '$required'." }
        }
        $archs = @([regex]::Matches($text, '(?m)^- Architecture:.*$'))
        if ($archs.Count -ne 1) { throw "Installer manifest must have exactly one installer (x64); found $($archs.Count)." }
        $url = "https://github.com/TheIdeaPlace/GHManage/releases/download/v$Version/$InstallerAsset"
        if (-not $text.Contains("InstallerUrl: $url`n")) { throw "Installer manifest has no InstallerUrl $url." }
    }

    $target = Join-Path $OutDir $name
    [System.IO.File]::WriteAllText($target, $text, [System.Text.UTF8Encoding]::new($false))
    Write-Host "Wrote $target"
}
