param(
  [string]$Target = 'emo-vision-train',
  [Parameter(Mandatory = $true)]
  [string]$ReleaseTag,
  [string]$ReleaseRepo = '',
  [string]$SourceRoot = $env:SOURCE_ROOT,
  [string]$SourceRef = 'local',
  [string]$Notes = '',
  [string]$ManifestName = 'manifest.json',
  [switch]$Mandatory,
  [switch]$SkipBuild
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
      & $sevenZip.Source a -tzip -mm=LZMA -mx=9 -mmt=on $AssetPath $distName
      if ($LASTEXITCODE -ne 0) {
        throw "7z failed with exit code $LASTEXITCODE"
      }
    }
    finally {
      Pop-Location
    }
    return
  }

  Write-Warning '7z was not found; falling back to Compress-Archive. Large GPU builds may exceed the GitHub Release asset size limit.'
  Compress-Archive -LiteralPath $DistDir -DestinationPath $AssetPath -Force
}

function Assert-ReleaseAssetSize {
  param([Parameter(Mandatory = $true)][string]$Path)

  $asset = Get-Item -LiteralPath $Path
  if ($asset.Length -gt $MaxGithubReleaseAssetBytes) {
    $sizeMb = [math]::Round($asset.Length / 1MB, 1)
    throw "Release asset is $sizeMb MB, but GitHub requires assets smaller than 2048 MB: $Path"
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

$env:SOURCE_ROOT = $sourceRootPath.Path
$env:RELEASE_TAG = $ReleaseTag

Push-Location -LiteralPath $repoRoot
try {
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

  Compress-ReleaseArchive -DistDir $distDir -AssetPath $assetPath
  Assert-ReleaseAssetSize -Path $assetPath
  $assetSha256 = Get-AssetSha256 -Path $assetPath

  if (-not $resolvedReleaseRepo) {
    $resolvedReleaseRepo = gh repo view --json nameWithOwner --jq '.nameWithOwner'
    if ($LASTEXITCODE -ne 0 -or -not $resolvedReleaseRepo) {
      throw 'Unable to resolve current GitHub repository with gh. Pass -ReleaseRepo owner/repo.'
    }
  }

  if ($resolvedReleaseRepo -notmatch '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$') {
    throw "ReleaseRepo must look like owner/repo, got: $resolvedReleaseRepo"
  }

  $encodedAssetName = [System.Uri]::EscapeDataString($assetName)
  $downloadUrl = "https://github.com/$resolvedReleaseRepo/releases/download/$ReleaseTag/$encodedAssetName"
  $manifest = [ordered]@{
    mandatory = [bool]$Mandatory
    notes = $Notes
    sha256 = $assetSha256
    url = $downloadUrl
    version = $version
  }

  $manifestPath = Join-Path ([System.IO.Path]::GetTempPath()) $ManifestName
  $manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

  $notes = "Local Windows build for $Target from $($config.source_repo)@$SourceRef."
  gh release view $ReleaseTag --repo $resolvedReleaseRepo *> $null
  $releaseExists = $LASTEXITCODE -eq 0

  if ($releaseExists) {
    gh release upload $ReleaseTag $assetPath --repo $resolvedReleaseRepo --clobber
    if ($LASTEXITCODE -ne 0) {
      throw "Failed to upload $assetName to $resolvedReleaseRepo release $ReleaseTag"
    }
    gh release upload $ReleaseTag $manifestPath --repo $resolvedReleaseRepo --clobber
    if ($LASTEXITCODE -ne 0) {
      throw "Failed to upload $ManifestName to $resolvedReleaseRepo release $ReleaseTag"
    }
  } else {
    gh release create $ReleaseTag $assetPath $manifestPath `
      --repo $resolvedReleaseRepo `
      --title $ReleaseTag `
      --notes $notes
    if ($LASTEXITCODE -ne 0) {
      throw "Failed to create $resolvedReleaseRepo release $ReleaseTag"
    }
  }

  Write-Host "Uploaded $assetName to $resolvedReleaseRepo release $ReleaseTag"
  Write-Host "Uploaded $ManifestName to $resolvedReleaseRepo release $ReleaseTag"
  Write-Host "Manifest URL: https://github.com/$resolvedReleaseRepo/releases/latest/download/$ManifestName"
  Write-Host "Package URL: $downloadUrl"
  Write-Host "Package SHA256: $assetSha256"
}
finally {
  Pop-Location
}
