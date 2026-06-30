param(
  [string]$Target = 'emo-vision-train',
  [Parameter(Mandatory = $true)]
  [string]$ReleaseTag,
  [string]$ReleaseRepo = '',
  [string]$SourceRoot = $env:SOURCE_ROOT,
  [string]$SourceRef = 'local',
  [string]$PreviousSourceRef = '',
  [string]$ReleaseBodyPath = '',
  [string]$Notes = '',
  [string]$ManifestName = 'manifest.json',
  [switch]$Mandatory,
  [switch]$SkipBuild,
  [switch]$NotesOnly
)

$ErrorActionPreference = 'Stop'
$MaxGithubReleaseAssetBytes = 2147483647

function Get-AssetSha256 {
  param([Parameter(Mandatory = $true)][string]$Path)

  $getFileHash = Get-Command Get-FileHash -ErrorAction SilentlyContinue
  if ($getFileHash) {
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
  }

  $stream = [System.IO.File]::OpenRead($Path)
  try {
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
      $hashBytes = $sha256.ComputeHash($stream)
      return -join ($hashBytes | ForEach-Object { $_.ToString('x2') })
    }
    finally {
      $sha256.Dispose()
    }
  }
  finally {
    $stream.Dispose()
  }
}

function Compress-ReleaseArchive {
  param(
    [Parameter(Mandatory = $true)][string]$DistDir,
    [Parameter(Mandatory = $true)][string]$AssetPath
  )

  $sevenZip = Get-Command 7z -ErrorAction SilentlyContinue
  if ($sevenZip) {
    $distParent = Split-Path -Parent $DistDir
    $distName = Split-Path -Leaf $DistDir
    Push-Location -LiteralPath $distParent
    try {
      & $sevenZip.Source a -tzip -mm=LZMA -mx=9 -mmt=on $AssetPath $distName |
        ForEach-Object { Write-Host $_ }
      if ($LASTEXITCODE -ne 0) {
        throw "7z failed with exit code $LASTEXITCODE"
      }
    }
    finally {
      Pop-Location
    }
    return 'zip/lzma'
  }

  Write-Warning '7z was not found; falling back to Compress-Archive. Large GPU builds may exceed the GitHub Release asset size limit.'
  Compress-Archive -LiteralPath $DistDir -DestinationPath $AssetPath -Force
  return 'zip/deflate'
}

function Assert-ReleaseAssetSize {
  param([Parameter(Mandatory = $true)][string]$Path)

  $asset = Get-Item -LiteralPath $Path
  if ($asset.Length -gt $MaxGithubReleaseAssetBytes) {
    $sizeMb = [math]::Round($asset.Length / 1MB, 1)
    throw "Release asset is $sizeMb MB, but GitHub requires assets smaller than 2048 MB: $Path"
  }
}

function Invoke-SourceGit {
  param(
    [Parameter(Mandatory = $true)][string]$SourceRootPath,
    [Parameter(Mandatory = $true)][string[]]$Arguments,
    [switch]$AllowFailure
  )

  $output = & git -C $SourceRootPath @Arguments 2>&1
  $exitCode = $LASTEXITCODE
  if ($exitCode -ne 0) {
    if ($AllowFailure) {
      return $null
    }

    $message = ($output | Out-String).Trim()
    throw "git $($Arguments -join ' ') failed in $SourceRootPath. $message"
  }

  return ($output | Out-String).Trim()
}

function Test-SourceCommitish {
  param(
    [Parameter(Mandatory = $true)][string]$SourceRootPath,
    [Parameter(Mandatory = $true)][string]$Ref
  )

  $commit = Invoke-SourceGit `
    -SourceRootPath $SourceRootPath `
    -Arguments @('rev-parse', '--verify', "$Ref^{commit}") `
    -AllowFailure
  return [bool]$commit
}

function Get-ResolvedSourceRef {
  param(
    [Parameter(Mandatory = $true)][string]$SourceRootPath,
    [Parameter(Mandatory = $true)][string]$RequestedSourceRef,
    [Parameter(Mandatory = $true)][string]$SourceCommit
  )

  $trimmedSourceRef = $RequestedSourceRef.Trim()
  if ($trimmedSourceRef -and $trimmedSourceRef -ne 'local') {
    return $trimmedSourceRef
  }

  $branch = Invoke-SourceGit `
    -SourceRootPath $SourceRootPath `
    -Arguments @('branch', '--show-current') `
    -AllowFailure
  if ($branch) {
    return $branch
  }

  return $SourceCommit
}

function Get-PreviousManifestBaseRef {
  param(
    [Parameter(Mandatory = $true)][string]$ReleaseRepoName,
    [Parameter(Mandatory = $true)][string]$CurrentReleaseTag,
    [Parameter(Mandatory = $true)][string]$ManifestAssetName
  )

  $releaseJson = & gh release list `
    --repo $ReleaseRepoName `
    --limit 20 `
    --json tagName 2>$null
  if ($LASTEXITCODE -ne 0 -or -not $releaseJson) {
    return $null
  }

  $releases = @($releaseJson | ConvertFrom-Json)
  foreach ($release in $releases) {
    if (-not $release.tagName -or $release.tagName -eq $CurrentReleaseTag) {
      continue
    }

    $downloadDir = Join-Path ([System.IO.Path]::GetTempPath()) "release-manifest-$([System.Guid]::NewGuid().ToString('N'))"
    New-Item -ItemType Directory -Path $downloadDir | Out-Null
    try {
      & gh release download $release.tagName `
        --repo $ReleaseRepoName `
        --pattern $ManifestAssetName `
        --dir $downloadDir `
        --clobber *> $null
      if ($LASTEXITCODE -ne 0) {
        continue
      }

      $manifestPath = Join-Path $downloadDir $ManifestAssetName
      if (-not (Test-Path -LiteralPath $manifestPath)) {
        continue
      }

      $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
      if ($manifest.PSObject.Properties.Name -contains 'source_commit' -and $manifest.source_commit) {
        return [pscustomobject]@{
          BaseRef = [string]$manifest.source_commit
          Source = "previous release manifest ($($release.tagName))"
        }
      }
    }
    finally {
      if (Test-Path -LiteralPath $downloadDir) {
        Remove-Item -LiteralPath $downloadDir -Recurse -Force
      }
    }
  }

  return $null
}

function Get-LatestSourceTag {
  param([Parameter(Mandatory = $true)][string]$SourceRootPath)

  return Invoke-SourceGit `
    -SourceRootPath $SourceRootPath `
    -Arguments @('describe', '--tags', '--abbrev=0') `
    -AllowFailure
}

function Get-ChangelogRange {
  param(
    [Parameter(Mandatory = $true)][string]$SourceRootPath,
    [Parameter(Mandatory = $true)][string]$ReleaseRepoName,
    [Parameter(Mandatory = $true)][string]$CurrentReleaseTag,
    [Parameter(Mandatory = $true)][string]$ManifestAssetName,
    [string]$RequestedBaseRef = ''
  )

  $trimmedRequestedBaseRef = $RequestedBaseRef.Trim()
  if ($trimmedRequestedBaseRef) {
    if (-not (Test-SourceCommitish -SourceRootPath $SourceRootPath -Ref $trimmedRequestedBaseRef)) {
      throw "PreviousSourceRef was not found in source repository history: $trimmedRequestedBaseRef"
    }

    return [pscustomobject]@{
      BaseRef = $trimmedRequestedBaseRef
      Source = 'PreviousSourceRef'
      Limit = 0
    }
  }

  $manifestBase = Get-PreviousManifestBaseRef `
    -ReleaseRepoName $ReleaseRepoName `
    -CurrentReleaseTag $CurrentReleaseTag `
    -ManifestAssetName $ManifestAssetName
  if ($manifestBase -and (Test-SourceCommitish -SourceRootPath $SourceRootPath -Ref $manifestBase.BaseRef)) {
    return [pscustomobject]@{
      BaseRef = $manifestBase.BaseRef
      Source = $manifestBase.Source
      Limit = 0
    }
  }

  if ($manifestBase) {
    Write-Warning "Previous manifest source_commit was not found locally: $($manifestBase.BaseRef). Falling back to source tags."
  }

  $latestTag = Get-LatestSourceTag -SourceRootPath $SourceRootPath
  if ($latestTag) {
    return [pscustomobject]@{
      BaseRef = $latestTag
      Source = 'latest source tag'
      Limit = 0
    }
  }

  return [pscustomobject]@{
    BaseRef = ''
    Source = 'latest 30 commits fallback'
    Limit = 30
  }
}

function Get-SourceCommits {
  param(
    [Parameter(Mandatory = $true)][string]$SourceRootPath,
    [string]$BaseRef = '',
    [int]$Limit = 30
  )

  $arguments = @('log', '--pretty=format:%H%x1f%s')
  if ($BaseRef) {
    $arguments += "$BaseRef..HEAD"
  } else {
    $arguments += @('-n', [string]$Limit, 'HEAD')
  }

  $rawLog = Invoke-SourceGit -SourceRootPath $SourceRootPath -Arguments $arguments
  if (-not $rawLog) {
    return @()
  }

  $commits = @()
  foreach ($line in ($rawLog -split "`r?`n")) {
    if (-not $line) {
      continue
    }

    $separatorIndex = $line.IndexOf([char]31)
    if ($separatorIndex -lt 1) {
      continue
    }

    $hash = $line.Substring(0, $separatorIndex)
    $subject = $line.Substring($separatorIndex + 1)
    $commits += [pscustomobject]@{
      Hash = $hash
      ShortHash = $hash.Substring(0, [math]::Min(7, $hash.Length))
      Subject = $subject
      Bucket = Get-ReleaseNotesBucket -Subject $subject
    }
  }

  return $commits
}

function Get-ReleaseNotesBucket {
  param([Parameter(Mandatory = $true)][string]$Subject)

  if ($Subject -match '(?i)(^|[^A-Za-z])pose([^A-Za-z]|$)|keypoint|skeleton') {
    return 'pose'
  }
  if ($Subject -match '(?i)AnyLabeling|labeling|label') {
    return 'labeling'
  }
  if ($Subject -match '(?i)Kaggle|training|GPU|resume') {
    return 'training'
  }
  if ($Subject -match '(?i)update|release|manifest|auto update') {
    return 'packaging'
  }
  if ($Subject -match '(?i)fix|harden|guard|collision|cleanup') {
    return 'fixes'
  }

  return 'unknown'
}

function New-SourceCompareUrl {
  param(
    [Parameter(Mandatory = $true)][string]$SourceRepoName,
    [Parameter(Mandatory = $true)][string]$HeadCommit,
    [string]$BaseRef = ''
  )

  if (-not $BaseRef) {
    return ''
  }

  $encodedBaseRef = [System.Uri]::EscapeDataString($BaseRef)
  return "https://github.com/$SourceRepoName/compare/$encodedBaseRef...$HeadCommit"
}

function New-ReleaseNotesMarkdown {
  param(
    [Parameter(Mandatory = $true)][string]$TargetName,
    [Parameter(Mandatory = $true)][string]$VersionTag,
    [Parameter(Mandatory = $true)][string]$SourceRepoName,
    [Parameter(Mandatory = $true)][string]$ResolvedSourceRef,
    [Parameter(Mandatory = $true)][string]$SourceCommit,
    [Parameter(Mandatory = $true)][object]$RangeInfo,
    [Parameter(Mandatory = $true)][object[]]$Commits,
    [string]$CompareUrl = '',
    [string]$ArchiveCompression = '',
    [switch]$NotesOnly
  )

  $bucketLabels = @{
    pose = 'Pose workflow updates'
    labeling = 'Labeling workflow updates'
    training = 'Training and remote execution updates'
    packaging = 'Update and packaging updates'
    fixes = 'Fixes and reliability improvements'
  }

  $lines = [System.Collections.Generic.List[string]]::new()
  $lines.Add("# $VersionTag") | Out-Null
  $lines.Add('') | Out-Null
  $lines.Add("Release notes are generated from $SourceRepoName git history with deterministic rules.") | Out-Null
  $lines.Add('') | Out-Null

  $lines.Add("## What's New") | Out-Null
  $featureCount = 0
  foreach ($bucket in @('pose', 'labeling', 'training', 'packaging')) {
    $bucketCommits = @($Commits | Where-Object { $_.Bucket -eq $bucket })
    foreach ($commit in $bucketCommits) {
      $lines.Add("- $($bucketLabels[$bucket]): $($commit.Subject)") | Out-Null
      $featureCount += 1
    }
  }
  if ($featureCount -eq 0) {
    $lines.Add('- No grouped feature updates detected in this range.') | Out-Null
  }
  $lines.Add('') | Out-Null

  $lines.Add('## Fixes and Improvements') | Out-Null
  $fixCommits = @($Commits | Where-Object { $_.Bucket -eq 'fixes' })
  if ($fixCommits.Count -gt 0) {
    foreach ($commit in $fixCommits) {
      $lines.Add("- $($bucketLabels.fixes): $($commit.Subject)") | Out-Null
    }
  } else {
    $lines.Add('- No grouped fix or reliability commits detected in this range.') | Out-Null
  }
  $lines.Add('') | Out-Null

  $rangeLabel = 'latest 30 commits'
  if ($RangeInfo.BaseRef) {
    $rangeLabel = "$($RangeInfo.BaseRef)..HEAD"
  }

  $lines.Add('## Build Notes') | Out-Null
  $lines.Add('- Target: `' + $TargetName + '`') | Out-Null
  $lines.Add('- Source repository: `' + $SourceRepoName + '`') | Out-Null
  $lines.Add('- Source ref: `' + $ResolvedSourceRef + '`') | Out-Null
  $lines.Add('- Source commit: `' + $SourceCommit + '`') | Out-Null
  $lines.Add('- Changelog range: `' + $rangeLabel + '` (' + $RangeInfo.Source + ')') | Out-Null
  if ($ArchiveCompression) {
    $lines.Add('- Archive compression: `' + $ArchiveCompression + '`') | Out-Null
  }
  if ($NotesOnly) {
    $lines.Add('- Existing release assets were not rebuilt or reuploaded.') | Out-Null
  }
  if ($CompareUrl) {
    $lines.Add('- Compare: ' + $CompareUrl) | Out-Null
  }
  $lines.Add('- Summary method: deterministic rule-based grouping, no AI/API call.') | Out-Null
  $lines.Add('') | Out-Null

  $lines.Add('## Full Commit List') | Out-Null
  if ($Commits.Count -gt 0) {
    foreach ($commit in $Commits) {
      $lines.Add('- `' + $commit.ShortHash + '` ' + $commit.Subject) | Out-Null
    }
  } else {
    $lines.Add('- No commits found in this range.') | Out-Null
  }

  return ($lines -join [Environment]::NewLine)
}

function New-ReleaseNotesFile {
  param(
    [Parameter(Mandatory = $true)][string]$TargetName,
    [Parameter(Mandatory = $true)][string]$VersionTag,
    [Parameter(Mandatory = $true)][string]$SourceRepoName,
    [Parameter(Mandatory = $true)][string]$ResolvedSourceRef,
    [Parameter(Mandatory = $true)][string]$SourceCommit,
    [Parameter(Mandatory = $true)][object]$RangeInfo,
    [Parameter(Mandatory = $true)][object[]]$Commits,
    [string]$CompareUrl = '',
    [string]$ArchiveCompression = '',
    [string]$OverrideBodyPath = '',
    [switch]$NotesOnly
  )

  $trimmedOverrideBodyPath = $OverrideBodyPath.Trim()
  if ($trimmedOverrideBodyPath) {
    if (-not (Test-Path -LiteralPath $trimmedOverrideBodyPath)) {
      throw "ReleaseBodyPath not found: $trimmedOverrideBodyPath"
    }

    return (Resolve-Path -LiteralPath $trimmedOverrideBodyPath).Path
  }

  $releaseNotes = New-ReleaseNotesMarkdown `
    -TargetName $TargetName `
    -VersionTag $VersionTag `
    -SourceRepoName $SourceRepoName `
    -ResolvedSourceRef $ResolvedSourceRef `
    -SourceCommit $SourceCommit `
    -RangeInfo $RangeInfo `
    -Commits $Commits `
    -CompareUrl $CompareUrl `
    -ArchiveCompression $ArchiveCompression `
    -NotesOnly:$NotesOnly
  $releaseNotesPath = Join-Path ([System.IO.Path]::GetTempPath()) "release-notes-$TargetName-$VersionTag.md"
  $releaseNotes | Set-Content -LiteralPath $releaseNotesPath -Encoding UTF8
  return $releaseNotesPath
}

function Test-GhReleaseExists {
  param(
    [Parameter(Mandatory = $true)][string]$ReleaseRepoName,
    [Parameter(Mandatory = $true)][string]$VersionTag
  )

  & gh release view $VersionTag --repo $ReleaseRepoName *> $null
  return $LASTEXITCODE -eq 0
}

function Set-GhReleaseNotes {
  param(
    [Parameter(Mandatory = $true)][string]$ReleaseRepoName,
    [Parameter(Mandatory = $true)][string]$VersionTag,
    [Parameter(Mandatory = $true)][string]$NotesPath
  )

  & gh release edit $VersionTag --repo $ReleaseRepoName --notes-file $NotesPath
  if ($LASTEXITCODE -ne 0) {
    throw "Failed to update release notes for $ReleaseRepoName release $VersionTag"
  }
}

if ($Target -notmatch '^[A-Za-z0-9_.-]+$') {
  throw "Invalid target name: $Target"
}

if ($ReleaseTag -notmatch '^v[0-9]+(\.[0-9]+){1,3}([-.][A-Za-z0-9._-]+)?$') {
  throw "ReleaseTag must look like v1.2.3, got: $ReleaseTag"
}

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$configPath = Join-Path $repoRoot "configs\$Target.json"
if (-not (Test-Path -LiteralPath $configPath)) {
  throw "Target config not found: $configPath"
}

if (-not $SourceRoot) {
  throw 'SourceRoot is required. Pass -SourceRoot or set SOURCE_ROOT.'
}

$sourceRootPath = Resolve-Path -LiteralPath $SourceRoot
$config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json
foreach ($field in @('name', 'release_asset_name', 'source_repo')) {
  if (-not $config.$field) {
    throw "Missing required config field: $field"
  }
}

$assetName = $config.release_asset_name
$assetName = $assetName.Replace('${RELEASE_TAG}', $ReleaseTag)
$assetName = $assetName.Replace('${TARGET}', $Target)
$version = $ReleaseTag.TrimStart('v')
if (-not $Notes) {
  $Notes = $version
}

$resolvedReleaseRepo = $ReleaseRepo.Trim()
if (-not $resolvedReleaseRepo -and $config.PSObject.Properties.Name -contains 'release_repo') {
  $resolvedReleaseRepo = [string]$config.release_repo
  $resolvedReleaseRepo = $resolvedReleaseRepo.Trim()
}

if (-not $resolvedReleaseRepo) {
  $resolvedReleaseRepo = gh repo view --json nameWithOwner --jq '.nameWithOwner'
  if ($LASTEXITCODE -ne 0 -or -not $resolvedReleaseRepo) {
    throw 'Unable to resolve current GitHub repository with gh. Pass -ReleaseRepo owner/repo.'
  }
}

if ($resolvedReleaseRepo -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') {
  throw "ReleaseRepo must look like owner/repo, got: $resolvedReleaseRepo"
}

$sourceCommit = Invoke-SourceGit `
  -SourceRootPath $sourceRootPath.Path `
  -Arguments @('rev-parse', 'HEAD')
$resolvedSourceRef = Get-ResolvedSourceRef `
  -SourceRootPath $sourceRootPath.Path `
  -RequestedSourceRef $SourceRef `
  -SourceCommit $sourceCommit
$rangeInfo = Get-ChangelogRange `
  -SourceRootPath $sourceRootPath.Path `
  -ReleaseRepoName $resolvedReleaseRepo `
  -CurrentReleaseTag $ReleaseTag `
  -ManifestAssetName $ManifestName `
  -RequestedBaseRef $PreviousSourceRef
$sourceCommits = @(Get-SourceCommits `
  -SourceRootPath $sourceRootPath.Path `
  -BaseRef $rangeInfo.BaseRef `
  -Limit $rangeInfo.Limit)
$sourceCompareUrl = New-SourceCompareUrl `
  -SourceRepoName $config.source_repo `
  -HeadCommit $sourceCommit `
  -BaseRef $rangeInfo.BaseRef

$env:SOURCE_ROOT = $sourceRootPath.Path
$env:RELEASE_TAG = $ReleaseTag

Push-Location -LiteralPath $repoRoot
try {
  if ($NotesOnly) {
    $releaseNotesPath = New-ReleaseNotesFile `
      -TargetName $Target `
      -VersionTag $ReleaseTag `
      -SourceRepoName $config.source_repo `
      -ResolvedSourceRef $resolvedSourceRef `
      -SourceCommit $sourceCommit `
      -RangeInfo $rangeInfo `
      -Commits $sourceCommits `
      -CompareUrl $sourceCompareUrl `
      -OverrideBodyPath $ReleaseBodyPath `
      -NotesOnly

    if (-not (Test-GhReleaseExists -ReleaseRepoName $resolvedReleaseRepo -VersionTag $ReleaseTag)) {
      throw "Release does not exist for notes-only update: $resolvedReleaseRepo $ReleaseTag"
    }

    Set-GhReleaseNotes `
      -ReleaseRepoName $resolvedReleaseRepo `
      -VersionTag $ReleaseTag `
      -NotesPath $releaseNotesPath
    Write-Host "Updated release notes for $resolvedReleaseRepo release $ReleaseTag"
    Write-Host "Source commit: $sourceCommit"
    if ($sourceCompareUrl) {
      Write-Host "Compare URL: $sourceCompareUrl"
    }
    return
  }

  if (-not $SkipBuild) {
    python build.py --config $configPath --clean
    if ($LASTEXITCODE -ne 0) {
      throw "Build failed with exit code $LASTEXITCODE"
    }
  }

  $distDir = Join-Path $repoRoot "dist\$($config.name)"
  if (-not (Test-Path -LiteralPath $distDir)) {
    throw "Dist directory not found: $distDir"
  }

  $assetPath = Join-Path ([System.IO.Path]::GetTempPath()) $assetName
  if (Test-Path -LiteralPath $assetPath) {
    Remove-Item -LiteralPath $assetPath -Force
  }

  $archiveCompression = Compress-ReleaseArchive -DistDir $distDir -AssetPath $assetPath
  Assert-ReleaseAssetSize -Path $assetPath
  $assetSha256 = Get-AssetSha256 -Path $assetPath

  $releaseNotesPath = New-ReleaseNotesFile `
    -TargetName $Target `
    -VersionTag $ReleaseTag `
    -SourceRepoName $config.source_repo `
    -ResolvedSourceRef $resolvedSourceRef `
    -SourceCommit $sourceCommit `
    -RangeInfo $rangeInfo `
    -Commits $sourceCommits `
    -CompareUrl $sourceCompareUrl `
    -ArchiveCompression $archiveCompression `
    -OverrideBodyPath $ReleaseBodyPath

  $encodedAssetName = [System.Uri]::EscapeDataString($assetName)
  $downloadUrl = "https://github.com/$resolvedReleaseRepo/releases/download/$ReleaseTag/$encodedAssetName"
  $manifest = [ordered]@{
    mandatory = [bool]$Mandatory
    notes = $Notes
    sha256 = $assetSha256
    url = $downloadUrl
    version = $version
    source_repo = [string]$config.source_repo
    source_ref = $resolvedSourceRef
    source_commit = $sourceCommit
    source_base_ref = [string]$rangeInfo.BaseRef
    source_compare_url = $sourceCompareUrl
    archive_compression = $archiveCompression
  }

  $manifestPath = Join-Path ([System.IO.Path]::GetTempPath()) $ManifestName
  $manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

  $releaseExists = Test-GhReleaseExists -ReleaseRepoName $resolvedReleaseRepo -VersionTag $ReleaseTag

  if ($releaseExists) {
    gh release upload $ReleaseTag $assetPath --repo $resolvedReleaseRepo --clobber
    if ($LASTEXITCODE -ne 0) {
      throw "Failed to upload $assetName to $resolvedReleaseRepo release $ReleaseTag"
    }
    gh release upload $ReleaseTag $manifestPath --repo $resolvedReleaseRepo --clobber
    if ($LASTEXITCODE -ne 0) {
      throw "Failed to upload $ManifestName to $resolvedReleaseRepo release $ReleaseTag"
    }
    Set-GhReleaseNotes `
      -ReleaseRepoName $resolvedReleaseRepo `
      -VersionTag $ReleaseTag `
      -NotesPath $releaseNotesPath
  } else {
    gh release create $ReleaseTag $assetPath $manifestPath `
      --repo $resolvedReleaseRepo `
      --title $ReleaseTag `
      --notes-file $releaseNotesPath
    if ($LASTEXITCODE -ne 0) {
      throw "Failed to create $resolvedReleaseRepo release $ReleaseTag"
    }
  }

  Write-Host "Uploaded $assetName to $resolvedReleaseRepo release $ReleaseTag"
  Write-Host "Uploaded $ManifestName to $resolvedReleaseRepo release $ReleaseTag"
  Write-Host "Manifest URL: https://github.com/$resolvedReleaseRepo/releases/latest/download/$ManifestName"
  Write-Host "Package URL: $downloadUrl"
  Write-Host "Package SHA256: $assetSha256"
  Write-Host "Source commit: $sourceCommit"
  if ($sourceCompareUrl) {
    Write-Host "Compare URL: $sourceCompareUrl"
  }
}
finally {
  Pop-Location
}
