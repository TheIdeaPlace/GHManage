<#
.SYNOPSIS
    Installs, upgrades and uninstalls GHManage with winget from the manifests the release
    pipeline would submit, and checks what each step leaves behind. Run on a throwaway
    Windows runner by .github/workflows/winget-install-test.yml, never on a working machine.

.DESCRIPTION
    Uses the real release assets: the manifests come from scripts/winget-release.ps1 for two
    published releases, and winget downloads each release's installer itself.

    1. Fresh install of -NewVersion: winget install --manifest.
    2. winget list, and the Add/Remove Programs row Velopack wrote (key, DisplayName,
       Publisher, DisplayVersion, QuietUninstallString), against the manifest's
       AppsAndFeaturesEntries.
    3. winget uninstall: the row, the install folder and the Start Menu shortcut are gone.
    4. Upgrade: install -OldVersion, then -NewVersion over it (winget install --manifest,
       which runs Setup.exe --silent over the old copy, as `winget upgrade` will once the
       package is in the catalog). Exactly one row afterwards, at the new version. Also
       records what `winget upgrade --manifest` says, which before publication is expected
       to be "no installed package found" (winget finds the installed copy through the
       catalog).
    5. winget uninstall again.

    Every winget call has a time limit, so a SmartScreen prompt nobody can answer on a
    runner fails the step instead of hanging the job. Writes a Markdown report with every
    command and its output. Exits non-zero if any check failed.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $NewVersion,
    [Parameter(Mandatory)] [string] $OldVersion,
    [Parameter(Mandatory)] [string] $Report,
    [string] $Repo = 'TheIdeaPlace/GHManage',
    [int] $TimeoutSeconds = 300
)

$ErrorActionPreference = 'Stop'
$work = Join-Path ([IO.Path]::GetTempPath()) 'ghmanage-winget-test'
New-Item -ItemType Directory -Force -Path $work | Out-Null
$arpKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\GHManage'
$installDir = Join-Path $env:LOCALAPPDATA 'GHManage'
$shortcut = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\GHManage.lnk'
$script:failures = 0
$lines = [Collections.Generic.List[string]]::new()

function Add-Report([string] $Text) { $lines.Add($Text); Write-Host $Text }
function Check([bool] $Ok, [string] $Label) {
    if ($Ok) { Add-Report "- PASS: $Label" } else { Add-Report "- **FAIL**: $Label"; $script:failures++ }
}

# Runs winget with a time limit and records the command and its output.
function Invoke-Winget([string[]] $WingetArgs) {
    $exe = (Get-Command winget -ErrorAction Stop).Source
    $outFile = Join-Path $work "winget-$([guid]::NewGuid()).out"
    $errFile = "$outFile.err"
    # Start-Process joins its arguments with spaces and quotes nothing.
    $quoted = $WingetArgs | ForEach-Object { if ($_ -match '\s') { "`"$_`"" } else { $_ } }
    $p = Start-Process -FilePath $exe -ArgumentList $quoted -NoNewWindow -PassThru `
        -RedirectStandardOutput $outFile -RedirectStandardError $errFile
    $null = $p.Handle   # without the handle cached, ExitCode can read as null after the wait
    $timedOut = -not $p.WaitForExit($TimeoutSeconds * 1000)
    if ($timedOut) {
        $smart = @(Get-Process smartscreen, CHXSmartScreen -ErrorAction SilentlyContinue).Count
        Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
        Get-Process GHManage-*Setup*, Setup, Update -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    }
    # winget draws progress with carriage returns and spinner characters; keep the text.
    $text = ((Get-Content -Raw $outFile -ErrorAction SilentlyContinue) + (Get-Content -Raw $errFile -ErrorAction SilentlyContinue))
    $text = ($text -split "`r?`n" | ForEach-Object { ($_ -split "`r")[-1] } |
        Where-Object { $_ -notmatch '^\s*[-\\|/]\s*$' -and $_.Trim() }) -join "`n"
    Add-Report ''
    Add-Report '```'
    Add-Report "> winget $($WingetArgs -join ' ')"
    Add-Report $text
    if ($timedOut) { Add-Report "(stopped after $TimeoutSeconds s; SmartScreen processes running: $smart)" }
    else { Add-Report "(exit code $($p.ExitCode))" }
    Add-Report '```'
    [pscustomobject]@{ ExitCode = if ($timedOut) { $null } else { $p.ExitCode }; Output = $text; TimedOut = $timedOut }
}

# Every Add/Remove Programs row named GHManage, in any hive, so a duplicate is seen.
function Get-ArpRows {
    $roots = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
             'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
             'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'
    @(foreach ($r in $roots) {
        Get-ChildItem $r -ErrorAction SilentlyContinue | ForEach-Object { Get-ItemProperty $_.PSPath } |
            Where-Object { $_.DisplayName -like '*GHManage*' } |
            ForEach-Object { [pscustomobject]@{ Key = $_.PSPath -replace '^.*::', ''; DisplayName = $_.DisplayName
                Publisher = $_.Publisher; DisplayVersion = $_.DisplayVersion; QuietUninstallString = $_.QuietUninstallString } }
    })
}

function Show-State([string] $Title) {
    Add-Report ''
    Add-Report "**$Title**"
    $rows = Get-ArpRows
    Add-Report ''
    Add-Report '```'
    if ($rows) { Add-Report (($rows | Format-List | Out-String).Trim()) } else { Add-Report '(no Add/Remove Programs row named GHManage)' }
    $exe = Get-ChildItem $installDir -Recurse -Filter ghmanage.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($exe) { Add-Report "ghmanage.exe: $($exe.FullName), file version $($exe.VersionInfo.FileVersion)" }
    Add-Report "Install folder $installDir exists: $(Test-Path $installDir)"
    Add-Report "Start Menu shortcut exists: $(Test-Path $shortcut)"
    Add-Report '```'
    return $rows
}

function Test-Installed([string] $Version, [string] $Label) {
    $rows = Show-State "State after $Label"
    Check ($rows.Count -eq 1) "$Label leaves exactly one Add/Remove Programs row (found $($rows.Count))"
    $row = $rows | Select-Object -First 1
    Check ($row.Key -like '*\CurrentVersion\Uninstall\GHManage' -and $row.Key -like 'HKEY_CURRENT_USER*') "the row is HKCU ...\Uninstall\GHManage, the manifest's ProductCode (is $($row.Key))"
    Check ($row.DisplayName -eq 'GHManage') "DisplayName is GHManage, as the manifest says (is '$($row.DisplayName)')"
    Check ($row.Publisher -eq 'Kelly Ford') "Publisher is Kelly Ford, as the manifest says (is '$($row.Publisher)')"
    Check ($row.DisplayVersion -eq $Version) "DisplayVersion is $Version (is '$($row.DisplayVersion)')"
    Check ($row.QuietUninstallString -match 'Update\.exe"? --uninstall --silent') "QuietUninstallString is Update.exe --uninstall --silent (is '$($row.QuietUninstallString)')"
    Check (Test-Path (Join-Path $installDir 'current\ghmanage.exe')) "ghmanage.exe is in $installDir\current"
    Check (Test-Path $shortcut) 'the Start Menu shortcut exists'
    $list = Invoke-Winget @('list', 'GHManage', '--accept-source-agreements', '--disable-interactivity')
    $listed = @($list.Output -split "`n" | Where-Object { $_ -match '\bGHManage\b' -and $_ -match [regex]::Escape($Version) })
    Check ($listed.Count -eq 1) "winget list shows one GHManage row at $Version"
}

function Test-Uninstalled([string] $Label) {
    $u = Invoke-Winget @('uninstall', 'GHManage', '--silent', '--accept-source-agreements', '--disable-interactivity')
    Check ($u.ExitCode -eq 0) "winget uninstall succeeds ($Label)"
    Start-Sleep -Seconds 5   # Update.exe --uninstall finishes removing its folder after it exits
    $rows = Show-State "State after uninstall ($Label)"
    Check ($rows.Count -eq 0) 'no Add/Remove Programs row is left'
    Check (-not (Test-Path (Join-Path $installDir 'current'))) 'the app folder is gone'
    Check (-not (Test-Path $shortcut)) 'the Start Menu shortcut is gone'
    $list = Invoke-Winget @('list', 'GHManage', '--accept-source-agreements', '--disable-interactivity')
    Check ($list.Output -notmatch '\bGHManage\b') 'winget list no longer shows GHManage'
}

# Passes on a clean validation, or on "succeeded with warnings" (exit code 0x8A150028,
# -1978335192) when every warning is the schema-header one. A runner's winget older than
# the manifests' schema (1.11 against 1.28) warns that the header URL "does not match the
# expected pattern"; winget-pkgs accepts that header, and a current winget gives no warning.
# Any other warning fails.
function Test-Validated($Result) {
    if ($Result.ExitCode -eq 0 -and $Result.Output -match 'validation succeeded') { return $true }
    if ($Result.ExitCode -ne -1978335192 -or $Result.Output -notmatch 'succeeded with warnings') { return $false }
    $warnings = @($Result.Output -split "`n" | Where-Object { $_ -match '^Manifest Warning:' })
    $other = @($warnings | Where-Object { $_ -notmatch 'schema header URL does not match the expected pattern' })
    return ($warnings.Count -gt 0 -and $other.Count -eq 0)
}

function Install-Manifest([string] $Dir, [string] $Label) {
    $r = Invoke-Winget @('install', '--manifest', $Dir, '--silent', '--accept-package-agreements',
                         '--accept-source-agreements', '--disable-interactivity')
    Check ($r.ExitCode -eq 0) "winget install --manifest succeeds ($Label)"
    return $r
}

try {
    Add-Report "# winget install test: TheIdeaPlace.GHManage $OldVersion -> $NewVersion"
    Add-Report ''
    Add-Report "Runner: $([Environment]::OSVersion.VersionString), $env:PROCESSOR_ARCHITECTURE, winget $(winget --version)"

    $newDir = Join-Path $work "manifests\$NewVersion"
    $oldDir = Join-Path $work "manifests\$OldVersion"
    & (Join-Path $PSScriptRoot 'winget-release.ps1') -Version $NewVersion -OutDir $newDir -Repo $Repo
    & (Join-Path $PSScriptRoot 'winget-release.ps1') -Version $OldVersion -OutDir $oldDir -Repo $Repo
    Add-Report ''
    Add-Report "## Manifests for $NewVersion"
    foreach ($f in Get-ChildItem $newDir) {
        Add-Report ''; Add-Report '```yaml'; Add-Report "# ----- $($f.Name)"; Add-Report (Get-Content -Raw $f.FullName).TrimEnd(); Add-Report '```'
    }

    Add-Report ''
    Add-Report '## Validate'
    foreach ($pair in @(@($newDir, $NewVersion), @($oldDir, $OldVersion))) {
        $v = Invoke-Winget @('validate', '--manifest', $pair[0], '--disable-interactivity')
        Check (Test-Validated $v) "winget validate passes for $($pair[1])"
    }

    $before = Show-State 'Before anything is installed'
    if ($before.Count) { throw 'GHManage is already installed on this machine; this test needs a clean one.' }

    Add-Report ''
    Add-Report "## 1. Fresh install of $NewVersion"
    Install-Manifest $newDir "fresh $NewVersion" | Out-Null
    Test-Installed $NewVersion "fresh install of $NewVersion"

    Add-Report ''
    Add-Report '## 2. Uninstall'
    Test-Uninstalled "fresh $NewVersion"

    Add-Report ''
    Add-Report "## 3. Upgrade from $OldVersion to $NewVersion"
    Install-Manifest $oldDir "$OldVersion" | Out-Null
    Test-Installed $OldVersion "install of $OldVersion"
    Add-Report ''
    Add-Report "What ``winget upgrade --manifest`` says before the package is in the catalog (recorded, not checked):"
    Invoke-Winget @('upgrade', '--manifest', $newDir, '--silent', '--accept-package-agreements',
                    '--accept-source-agreements', '--disable-interactivity') | Out-Null
    Show-State 'State after winget upgrade --manifest' | Out-Null
    Install-Manifest $newDir "$NewVersion over $OldVersion" | Out-Null
    Test-Installed $NewVersion "upgrade from $OldVersion to $NewVersion"

    Add-Report ''
    Add-Report '## 4. Uninstall after the upgrade'
    Test-Uninstalled "upgraded $NewVersion"
}
catch {
    Add-Report ''
    Add-Report "**ERROR**: $($_.Exception.Message)"
    $script:failures++
}
finally {
    Add-Report ''
    Add-Report "$script:failures check(s) failed."
    [IO.File]::WriteAllLines($Report, $lines)
    if ($env:GITHUB_STEP_SUMMARY) { Get-Content -Raw $Report | Add-Content -LiteralPath $env:GITHUB_STEP_SUMMARY }
}
exit $script:failures
