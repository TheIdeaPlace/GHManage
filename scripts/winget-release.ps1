<#
.SYNOPSIS
    Writes the winget manifests for one published GHManage release, straight from the
    release on GitHub: picks its installer asset, downloads and hashes it, and calls
    scripts/winget-manifest.ps1.

.DESCRIPTION
    Needs `gh` signed in (GH_TOKEN in CI) with read access to the repository.

    The installer is GHManage-<version>-win-winget-Setup.exe, the winget-only copy that
    ghmanage.yml publishes from the release after 1.2.0 on, so its download count measures
    winget installs. A release without that copy (1.2.0 and earlier) uses
    GHManage-win-Setup.exe, the same bytes, whose URL is just as stable because the tag is in
    it. When both are present they must be byte-identical (their GitHub digests are
    compared, and the one downloaded is hashed) or nothing is written.

    Refuses a draft or a pre-release: only published releases go to winget.

.EXAMPLE
    pwsh scripts/winget-release.ps1 -Version 1.2.0 -OutDir out/1.2.0
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)] [string] $Version,
    [Parameter(Mandatory)] [string] $OutDir,
    [string] $Repo = 'TheIdeaPlace/GHManage',
    [string] $DownloadDir = (Join-Path ([IO.Path]::GetTempPath()) "ghmanage-winget-$PID")
)

$ErrorActionPreference = 'Stop'
if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw "Version '$Version' is not X.Y.Z (no leading v)." }
$tag = "v$Version"

$json = & gh release view $tag -R $Repo --json isDraft,isPrerelease,publishedAt,assets 2>&1
if ($LASTEXITCODE -ne 0) { throw "gh release view $tag failed: $json" }
$release = "$json" | ConvertFrom-Json
if ($release.isDraft) { throw "$tag is a draft; only published releases go to winget." }
if ($release.isPrerelease) { throw "$tag is a pre-release; only full releases go to winget." }
if (-not $release.publishedAt) { throw "$tag has no publish date." }

$wingetName = "GHManage-$Version-win-winget-Setup.exe"
$plainName = 'GHManage-win-Setup.exe'
$winget = $release.assets | Where-Object name -ceq $wingetName
$plain = $release.assets | Where-Object name -ceq $plainName
if ($winget) {
    $asset = $winget
    if ($plain -and $plain.digest -and $winget.digest -and $plain.digest -ne $winget.digest) {
        throw "$wingetName ($($winget.digest)) is not byte-identical to $plainName ($($plain.digest))."
    }
} elseif ($plain) {
    $asset = $plain
    Write-Host "::notice::$tag has no $wingetName (it predates the winget-only copy); the manifest uses $plainName."
} else {
    throw "$tag has neither $wingetName nor $plainName."
}

New-Item -ItemType Directory -Force -Path $DownloadDir | Out-Null
$out = & gh release download $tag -R $Repo -D $DownloadDir -p $asset.name --clobber 2>&1
if ($LASTEXITCODE -ne 0) { throw "gh release download failed: $out" }
$file = Join-Path $DownloadDir $asset.name
$sha = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash
if ($asset.digest -and $asset.digest -ne "sha256:$($sha.ToLowerInvariant())") {
    throw "Downloaded $($asset.name) hashes to $sha, but GitHub's digest is $($asset.digest)."
}
Remove-Item -LiteralPath $file

$date = ([datetime]$release.publishedAt).ToUniversalTime().ToString('yyyy-MM-dd')
& (Join-Path $PSScriptRoot 'winget-manifest.ps1') -Version $Version -InstallerAsset $asset.name `
    -Sha256 $sha -ReleaseDate $date -OutDir $OutDir
