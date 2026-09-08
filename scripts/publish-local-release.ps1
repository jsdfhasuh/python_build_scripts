param(
  [string]$Target = 'emo-vision-train',
  [Parameter(Mandatory = $true)][string]$ReleaseTag,
  [string]$ReleaseRepo = '',
  [string]$SourceRoot = $env:SOURCE_ROOT,
  [string]$SourceRef = 'local',
  [string]$PreviousSourceRef = '',
  [string]$ReleaseBodyPath = '',
  [string]$Notes = '',
  [string]$ManifestName = 'manifest.json',
  [string]$OutputDirectory = '',
  [switch]$Mandatory,
  [switch]$SkipBuild,
  [switch]$NotesOnly,
  [switch]$BuildOnly,
  [string]$BrandingProfile,
  [string]$ProgramName,
  [string]$IconPath,
  [string]$ReleaseAssetName,
  [string]$BuildRecordPath,
  [switch]$DryRun,
  [switch]$Publish,
  [string]$PythonExecutable = 'python'
)

$ErrorActionPreference = 'Stop'
$brandingFields = @('BrandingProfile', 'ProgramName', 'IconPath', 'ReleaseAssetName')
$hasBranding = $false
foreach ($field in $brandingFields) {
  if ($PSBoundParameters.ContainsKey($field)) { $hasBranding = $true }
}
$hasPortableArgument = $hasBranding
foreach ($field in @('DryRun', 'Publish', 'BuildRecordPath', 'PythonExecutable')) {
  if ($PSBoundParameters.ContainsKey($field)) { $hasPortableArgument = $true }
}
if ($NotesOnly -and ($hasPortableArgument -or $BuildOnly -or $SkipBuild)) {
  throw 'NotesOnly cannot be combined with branding, build or preview arguments'
}
if ($Publish -and $BuildOnly) { throw 'Publish and BuildOnly cannot be combined' }
if ($hasPortableArgument -or ($Target -eq 'emo-vision-train' -and $BuildOnly)) {
  if ($Target -ne 'emo-vision-train') {
    throw 'Portable branding is supported only for emo-vision-train'
  }
  if (-not $SourceRoot) { throw 'Pass SourceRoot or set SOURCE_ROOT' }
  $arguments = @(
    '-X', 'utf8', (Join-Path $PSScriptRoot 'publish_visionworkshop.py'),
    "--target=$Target", "--source-root=$SourceRoot", "--source-ref=$SourceRef",
    "--release-tag=$ReleaseTag", "--release-repo=$ReleaseRepo",
    "--manifest-name=$ManifestName", "--notes=$Notes"
  )
  $mapping = @{
    BrandingProfile = 'branding-profile'; ProgramName = 'program-name'; IconPath = 'icon-path'
    ReleaseAssetName = 'release-asset-name'; BuildRecordPath = 'build-record-path'
    OutputDirectory = 'output-directory'; PreviousSourceRef = 'previous-source-ref'
    ReleaseBodyPath = 'release-body-path'
  }
  foreach ($field in $mapping.Keys) {
    if ($PSBoundParameters.ContainsKey($field)) {
      $arguments += "--$($mapping[$field])=$($PSBoundParameters[$field])"
    }
  }
  if ($SkipBuild) { $arguments += '--skip-build' }
  if ($DryRun) { $arguments += '--dry-run' }
  if ($Mandatory) { $arguments += '--mandatory' }
  if ($Publish) { $arguments += '--publish' } else { $arguments += '--build-only' }
  & $PythonExecutable @arguments
  if ($LASTEXITCODE -ne 0) { throw "Portable build failed with exit code $LASTEXITCODE" }
  return
}

# The old publisher is retained byte-for-byte under a new filename in this directory.
# Its PSScriptRoot, existing parameter defaults and installer behavior are unchanged.
if ($PSBoundParameters.ContainsKey('PythonExecutable')) {
  throw 'PythonExecutable applies to the new portable branding path only'
}
$legacyArguments = @{}
foreach ($field in $PSBoundParameters.Keys) {
  if ($field -ne 'Publish') { $legacyArguments[$field] = $PSBoundParameters[$field] }
}
& (Join-Path $PSScriptRoot 'publish-local-release-legacy.ps1') @legacyArguments
