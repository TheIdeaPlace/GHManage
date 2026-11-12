<#
.SYNOPSIS
    Checks scripts/winget-manifest.ps1 and the installer/winget template on every pull
    request, so a template or script change that breaks the winget submission fails here and
    not after a release is already out. Run by the winget-manifest job in ghmanage.yml.

    pwsh scripts/winget-manifest.tests.ps1     # exits with the number of failures
#>
$ErrorActionPreference = 'Stop'
$script = Join-Path $PSScriptRoot 'winget-manifest.ps1'
$template = Join-Path $PSScriptRoot '..' 'installer' 'winget'
$root = Join-Path ([IO.Path]::GetTempPath()) "winget-manifest-tests-$PID"
$failures = 0

function Pass($label) { Write-Host "ok   $label" }
function Fail($label) { Write-Host "FAIL $label"; $script:failures++ }

function New-Params {
    @{ Version = '1.2.3'; InstallerAsset = 'GHManage-1.2.3-win-winget-Setup.exe'; Sha256 = ('a' * 64)
       ReleaseDate = '2026-11-12'; OutDir = (Join-Path $root "out-$([guid]::NewGuid())") }
}

# A copy of the template with one edit to one file.
function New-Template([string] $File, [scriptblock] $Edit) {
    $dir = Join-Path $root "tpl-$([guid]::NewGuid())"
    New-Item -ItemType Directory -Force $dir | Out-Null
    Copy-Item (Join-Path $template '*.yaml') $dir
    $path = Join-Path $dir $File
    $before = [IO.File]::ReadAllText($path)
    $after = & $Edit $before
    if ($after -eq $before) { throw "The edit to $File changed nothing; the test would prove nothing." }
    [IO.File]::WriteAllText($path, $after)
    return $dir
}

function Expect-Refused([string] $Label, [hashtable] $Params) {
    try { & $script @Params *> $null; Fail "accepted: $Label" }
    catch { Pass "refused: $Label ($($_.Exception.Message))" }
}

function Read-Out([hashtable] $Params, [string] $File) {
    [IO.File]::ReadAllText((Join-Path $Params.OutDir $File))
}

$installer = 'TheIdeaPlace.GHManage.installer.yaml'
$locale = 'TheIdeaPlace.GHManage.locale.en-US.yaml'

try {
    # The real template, filled, is accepted and comes out with no comments or placeholders.
    $p = New-Params
    & $script @p | Out-Null
    $files = Get-ChildItem $p.OutDir -Filter *.yaml
    if ($files.Count -eq 3) { Pass 'writes three manifests' } else { Fail "wrote $($files.Count) manifests" }
    $all = ($files | ForEach-Object { [IO.File]::ReadAllText($_.FullName) }) -join "`n"
    if ($all -notmatch '(?m)^#(?! yaml-language-server:)') { Pass 'strips comments, keeps schema lines' } else { Fail 'a comment survived' }
    if (([regex]::Matches($all, '(?m)^# yaml-language-server:')).Count -eq 3) { Pass 'one schema line per file' } else { Fail 'schema lines lost' }
    if ($all -notmatch '<[A-Z0-9-]+>') { Pass 'fills every placeholder' } else { Fail 'a placeholder survived' }
    if ($all -notmatch "`r") { Pass 'LF line endings' } else { Fail 'CR in output' }
    $inst = Read-Out $p $installer
    if ($inst.Contains('InstallerSha256: ' + ('A' * 64))) { Pass 'upper-cases the hash' } else { Fail 'hash not upper-cased' }
    if ($inst.Contains('InstallerUrl: https://github.com/TheIdeaPlace/GHManage/releases/download/v1.2.3/GHManage-1.2.3-win-winget-Setup.exe')) {
        Pass 'points at the winget-only copy on the version tag'
    } else { Fail 'wrong InstallerUrl for the winget copy' }
    if ($inst.Contains('ReleaseDate: 2026-11-12')) { Pass 'fills the release date' } else { Fail 'release date missing' }
    if ((Read-Out $p $locale).Contains('ReleaseNotesUrl: https://github.com/TheIdeaPlace/GHManage/releases/tag/v1.2.3')) {
        Pass 'release notes URL on the version tag'
    } else { Fail 'wrong ReleaseNotesUrl' }

    # A release from before the winget-only copy uses the ordinary Setup.exe.
    $p = New-Params; $p.InstallerAsset = 'GHManage-win-Setup.exe'
    & $script @p | Out-Null
    if ((Read-Out $p $installer).Contains('InstallerUrl: https://github.com/TheIdeaPlace/GHManage/releases/download/v1.2.3/GHManage-win-Setup.exe')) {
        Pass 'falls back to GHManage-win-Setup.exe when asked'
    } else { Fail 'fallback InstallerUrl wrong' }

    # Bad inputs.
    $p = New-Params; $p.Version = 'v1.2.3'; Expect-Refused 'version with a leading v' $p
    $p = New-Params; $p.Version = '1.2.3-beta.1'; $p.InstallerAsset = 'GHManage-1.2.3-beta.1-win-winget-Setup.exe'; Expect-Refused 'a pre-release version' $p
    $p = New-Params; $p.Sha256 = 'xyz'; Expect-Refused 'a malformed hash' $p
    $p = New-Params; $p.ReleaseDate = '11/12/2026'; Expect-Refused 'a date not in YYYY-MM-DD' $p
    $p = New-Params; $p.InstallerAsset = 'GHManage-1.2.2-win-winget-Setup.exe'; Expect-Refused 'another version''s winget copy' $p
    $p = New-Params; $p.InstallerAsset = 'GHManage-win-Portable.zip'; Expect-Refused 'the portable zip' $p
    $p = New-Params; $p.InstallerAsset = 'ghmanage-win-setup.exe'; Expect-Refused 'a differently cased asset name' $p

    # Templates that break the package's rules (installer/winget/README.md).
    $p = New-Params; $p.TemplateDir = New-Template $installer { param($t) $t -replace 'ProductCode: GHManage', "ProductCode: GHManage`n  UpgradeCode: '{1234}'" }
    Expect-Refused 'an UpgradeCode' $p
    $p = New-Params; $p.TemplateDir = New-Template $installer { param($t) $t -replace '(?m)^Installers:', "ProductCode: '{ABCD}'`nInstallers:" }
    Expect-Refused 'an installer-level ProductCode' $p
    $p = New-Params; $p.TemplateDir = New-Template $installer { param($t) $t -replace 'ProductCode: GHManage', 'ProductCode: MSI:GHManage' }
    Expect-Refused 'the wrong ProductCode' $p
    $p = New-Params; $p.TemplateDir = New-Template $installer { param($t) $t -replace 'Scope: user', 'Scope: machine' }
    Expect-Refused 'machine scope' $p
    $p = New-Params; $p.TemplateDir = New-Template $installer { param($t) $t -replace 'Silent: --silent', 'Silent: /S' }
    Expect-Refused 'a silent switch that is not --silent' $p
    $p = New-Params; $p.TemplateDir = New-Template $installer { param($t) $t -replace 'InstallerType: exe', 'InstallerType: nullsoft' }
    Expect-Refused 'an installer type that is not exe' $p
    $p = New-Params; $p.TemplateDir = New-Template $installer { param($t) $t -replace 'UpgradeBehavior: install', 'UpgradeBehavior: uninstallPrevious' }
    Expect-Refused 'UpgradeBehavior uninstallPrevious' $p
    $p = New-Params; $p.TemplateDir = New-Template $installer { param($t) $t -replace 'Publisher: Kelly Ford', 'Publisher: TheIdeaPlace' }
    Expect-Refused 'a Publisher Add/Remove Programs does not show' $p
    $p = New-Params; $p.TemplateDir = New-Template $installer { param($t) $t -replace '<INSTALLER-ASSET>', 'GHManage-<VERSION>-win.msi' }
    Expect-Refused 'an MSI installer' $p
    $p = New-Params; $p.TemplateDir = New-Template $installer { param($t) $t -replace 'releases/download/v<VERSION>/', 'releases/latest/download/' }
    Expect-Refused 'a URL that is not on the version tag' $p
    $p = New-Params; $p.TemplateDir = New-Template $installer { param($t) $t -replace '- Architecture: x64', '- Architecture: x86' }
    Expect-Refused 'an x86 installer' $p
    $p = New-Params; $p.TemplateDir = New-Template $installer { param($t) $t -replace '(?s)(- Architecture: x64.*?InstallerSha256: <SHA256>\r?\n)', "`$1`$1" }
    Expect-Refused 'two installers' $p
    $p = New-Params; $p.TemplateDir = New-Template $installer { param($t) $t -replace 'ReleaseDate: <RELEASE-DATE>', 'ReleaseDate: <NEW-THING>' }
    Expect-Refused 'an unknown placeholder' $p
    $p = New-Params; $p.TemplateDir = New-Template 'TheIdeaPlace.GHManage.yaml' { param($t) $t -replace 'TheIdeaPlace.GHManage', 'KellyLford.GHManage' }
    Expect-Refused 'another package identifier' $p

    # An indented '#' line is text inside a block scalar, not a comment, and must survive.
    $p = New-Params; $p.TemplateDir = New-Template $locale { param($t) $t -replace '(?m)^(Description: \|-\r?\n)', "`$1  # Features`n" }
    & $script @p | Out-Null
    if ((Read-Out $p $locale).Contains("  # Features")) {
        Pass 'keeps an indented # line inside Description'
    } else { Fail 'dropped an indented # line inside Description' }
}
finally {
    Remove-Item -Recurse -Force $root -ErrorAction SilentlyContinue
}

Write-Host "$failures failure(s)"
exit $failures
