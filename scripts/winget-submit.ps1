<#
.SYNOPSIS
    Opens the microsoft/winget-pkgs pull request for one GHManage version, from the
    manifests scripts/winget-manifest.ps1 wrote. Called by .github/workflows/winget-submit.yml.

.DESCRIPTION
    Needs GH_TOKEN set to a classic personal access token with the public_repo scope.

    Everything goes through the GitHub API: nothing is cloned and the fork is never synced.
    Syncing a fork whose upstream changed .github/workflows needs the `workflow` scope, which
    this token deliberately lacks, and winget-pkgs changes its workflows about monthly. A fork
    shares its upstream's object network, so a branch in the fork can point straight at a
    commit built on upstream's current master. wingetcreate and Komac work the same way.

.PARAMETER NoPullRequest
    Stop after pushing the branch. For testing the API steps.

.EXAMPLE
    pwsh scripts/winget-submit.ps1 -Version 1.2.1 -ManifestDir out/1.2.1
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $Version,
    [Parameter(Mandatory)] [string] $ManifestDir,
    [switch] $NoPullRequest
)

$ErrorActionPreference = 'Stop'
# Also what makes $branch safe to put inside the jq filter below.
if ($Version -notmatch '^\d+\.\d+\.\d+(-test)?$') { throw "Version '$Version' is not X.Y.Z." }
$upstream = 'microsoft/winget-pkgs'
$id = 'TheIdeaPlace.GHManage'
$pkgRoot = 'manifests/t/TheIdeaPlace/GHManage'
$pkgDir = "$pkgRoot/$Version"
$branch = "$id-$Version"

# Returns gh's stdout as one string. stderr is kept apart: merged in, a warning on a call
# that succeeded would end up inside a sha or a URL.
function Invoke-Gh {
    $errFile = New-TemporaryFile
    try {
        $out = & gh @args 2>$errFile
        $code = $LASTEXITCODE
        $err = "$(Get-Content -Raw -LiteralPath $errFile)".Trim()
        if ($code -ne 0) { throw "gh $($args -join ' ') failed: $err $out" }
        if ($err) { Write-Host "gh $($args[0]) said on stderr: $err" }
        return (@($out) -join "`n").Trim()
    } finally { Remove-Item $errFile -ErrorAction SilentlyContinue }
}

# True if the API path exists, false on 404, and an error for anything else, so a rate
# limit or an outage is never mistaken for "not there".
function Test-GhPath([string] $Path) {
    $out = & gh api $Path --silent 2>&1
    if ($LASTEXITCODE -eq 0) { return $true }
    if ("$out" -match 'HTTP 404') { return $false }
    throw "gh api $Path failed: $out"
}

# POST/PATCH a JSON body; returns the response's field.
function Send-GhJson([string] $Method, [string] $Path, $Body, [string] $Field) {
    $file = New-TemporaryFile
    try {
        [IO.File]::WriteAllText($file, ($Body | ConvertTo-Json -Depth 5 -Compress), [Text.UTF8Encoding]::new($false))
        # @() around the whole if: a one-element array would otherwise unroll to a string,
        # and splatting a string passes it one character at a time.
        [string[]] $jq = @(if ($Field) { '--jq', ".$Field" } else { '--silent' })
        return Invoke-Gh api -X $Method $Path --input $file @jq
    } finally { Remove-Item $file -ErrorAction SilentlyContinue }
}

$files = @(Get-ChildItem -LiteralPath $ManifestDir -Filter '*.yaml')
if ($files.Count -ne 3) { throw "Expected 3 manifests in $ManifestDir, found $($files.Count)." }

$login = Invoke-Gh api user --jq .login
$fork = "$login/winget-pkgs"

# An open pull request from this branch means a run for this version already got that far,
# and the branch may since carry fixes a moderator asked for. Never push over it. An exact
# check on the head branch, unlike the workflow's title search, which lags behind pull
# requests opened minutes ago.
# No --author: with it gh switches to the search API, which lags the same way and matches
# --head as a prefix. --head alone queries pullRequests(headRefName:) directly; the owner
# is matched here, since other forks can use the same branch name.
# The --json list must stay quoted: unquoted it is a PowerShell array, which Invoke-Gh's
# @args hands to gh as the text "System.Object[]".
$existing = Invoke-Gh pr list -R $upstream --head $branch --state open --json 'url,headRefName,headRepositoryOwner' `
    --jq "[.[] | select(.headRefName == `"$branch`" and .headRepositoryOwner.login == `"$login`")][0].url // empty"
if ($existing) {
    Write-Host "::notice::A pull request is already open for ${branch}: $existing"
    return
}

if (-not (Test-GhPath "repos/$fork")) {
    Invoke-Gh repo fork $upstream --clone=false --default-branch-only | Out-Null
    # A new fork answers on repos/<fork> before its git data is ready, so wait on a ref.
    $ready = $false
    foreach ($i in 1..30) {
        if (Test-GhPath "repos/$fork/git/ref/heads/master") { $ready = $true; break }
        Start-Sleep -Seconds 5
    }
    if (-not $ready) { throw "The fork $fork was created but its master branch is not there yet. Run this again in a few minutes." }
}

$base = Invoke-Gh api "repos/$upstream/git/ref/heads/master" --jq .object.sha
$baseTree = Invoke-Gh api "repos/$upstream/git/commits/$base" --jq .tree.sha

# The first version in the catalog is a new package, which winget-pkgs titles and reviews
# differently from a new version of one already there.
# While the first one is still in review, a later version is an update to it, not a second
# new package for the same identifier.
$isNew = -not (Test-GhPath "repos/$upstream/contents/$pkgRoot")
if ($isNew) {
    $pending = Invoke-Gh pr list -R $upstream --author $login --state open --search "$id in:title" `
        --json title --jq "[.[] | select(.title | startswith(`"New package: $id `"))] | length"
    if ([int]"$pending" -gt 0) { $isNew = $false }
}

# One commit holding the three files, on top of upstream's master.
$entries = foreach ($f in $files) {
    @{ path = "$pkgDir/$($f.Name)"; mode = '100644'; type = 'blob'
       content = [IO.File]::ReadAllText($f.FullName) }
}
$tree = Send-GhJson POST "repos/$fork/git/trees" @{ base_tree = $baseTree; tree = @($entries) } 'sha'
$commit = Send-GhJson POST "repos/$fork/git/commits" @{
    message = "$(if ($isNew) { 'New package' } else { 'New version' }): $id version $Version"; tree = $tree; parents = @($base) } 'sha'

# The branch is new, or left over from a run that failed before opening its pull request
# (checked above). A leftover is deleted, not moved: moving it from an older upstream base
# changes every workflow file upstream changed in between, which GitHub refuses without the
# `workflow` scope this token lacks. Creating a ref on upstream's current commit is fine.
if (Test-GhPath "repos/$fork/git/ref/heads/$branch") {
    Invoke-Gh api -X DELETE "repos/$fork/git/refs/heads/$branch" --silent | Out-Null
}
Send-GhJson POST "repos/$fork/git/refs" @{ ref = "refs/heads/$branch"; sha = $commit } | Out-Null
Write-Host "Pushed $commit to ${fork}:$branch"

if ($NoPullRequest) { return }

$description = if ($isNew) {
    "New package: $id $Version. GHManage is a keyboard-first desktop app for GitHub (https://github.com/TheIdeaPlace/GHManage). The installer is Velopack's Setup.exe (per-user, ``--silent``, no elevation); the Add/Remove Programs entry it writes is the key ``GHManage``, which ``AppsAndFeaturesEntries`` names as its ProductCode. Submitted by GHManage's release workflow from the template in installer/winget/."
} else {
    "Update $id to $Version. Submitted by GHManage's release workflow from the same template as every earlier version, changing only the version, the release date, the installer URL and its SHA256 hash, and ReleaseNotesUrl."
}
$title = if ($isNew) { "New package: $id version $Version" } else { "Update: $id to $Version" }
$body = @"
## 📖 Description

$description

## ✅ Checklist

- [x] Signed the [Contributor License Agreement](https://cla.opensource.microsoft.com)
- [ ] Linked to an issue (if applicable)

## 📦 Manifest Checklist

- [x] Checked that there aren't other open [pull requests](https://github.com/microsoft/winget-pkgs/pulls) for the same manifest update/change
- [x] This PR only modifies one (1) manifest
- [ ] Validated manifest locally with ``winget validate --manifest <path>``: the workflow runs on Linux; the template it fills passes ``winget validate`` (checked by GHManage's winget install test workflow).
- [ ] Tested manifest locally with ``winget install --manifest <path>``: not for this exact file; the same template is installed, upgraded and uninstalled with winget on a Windows runner on every change to it.
- [x] Manifest conforms to the [1.28 schema](https://github.com/microsoft/winget-pkgs/tree/master/doc/manifest/schema/1.28.0)
"@
$bodyFile = New-TemporaryFile
[IO.File]::WriteAllText($bodyFile, $body, [Text.UTF8Encoding]::new($false))
$url = Invoke-Gh pr create -R $upstream --base master --head "${login}:$branch" `
    --title $title --body-file $bodyFile
Write-Host "::notice::Opened $url"
if ($env:GITHUB_STEP_SUMMARY) { Add-Content -LiteralPath $env:GITHUB_STEP_SUMMARY -Value "winget pull request: $url" }
