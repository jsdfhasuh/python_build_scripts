# Read function definitions only: never run the publisher or contact GitHub.
$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $PSScriptRoot '../../scripts/publish-local-release-legacy.ps1'
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile(
  (Resolve-Path $scriptPath).Path, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
foreach ($function in $ast.FindAll({ param($node)
  $node -is [System.Management.Automation.Language.FunctionDefinitionAst]
}, $false)) {
  Invoke-Expression $function.Extent.Text
}
$script:sha = 'a' * 40
$script:otherSha = 'b' * 40
$script:scenario = 'lightweight'
$script:dirty = ''
$script:head = $script:sha
$script:requested = $script:sha
$script:ghCalls = @()
function gh {
  $script:ghCalls += ,@($args)
  $global:LASTEXITCODE = 0
  $path = [string]$args[1]
  if ($args[0] -eq 'api') {
    if ($script:scenario -eq 'network-failure') {
      $global:LASTEXITCODE = 1
      return
    }
    if ($path -match '/commits/') { return (@{ sha = $script:sha } | ConvertTo-Json) }
    if ($path -match '/git/tags/') {
      return (@{ object = @{ type = 'commit'; sha = $script:sha } } | ConvertTo-Json)
    }
    if ($path -match '/matching-refs/') {
      if ($script:scenario -eq 'absent') { return '[]' }
      $type = 'commit'
      $sha = $script:sha
      if ($script:scenario -eq 'annotated') { $type = 'tag'; $sha = $script:otherSha }
      if ($script:scenario -eq 'mismatch') { $sha = $script:otherSha }
      return (ConvertTo-Json -InputObject @(@{ ref = 'refs/tags/v0.6.1'; object = @{ type = $type; sha = $sha } }) -Depth 5)
    }
  }
  if ($args[0] -eq 'release' -and $args[1] -eq 'view') {
    return '{"assets":[{"name":"manifest.json"}]}'
  }
  throw "Unexpected gh invocation: $args"
}
function Invoke-SourceGit {
  param($SourceRootPath, $Arguments)
  if ($Arguments[0] -eq 'status') { return $script:dirty }
  if ($Arguments -contains '--verify') { return $script:requested }
  return $script:head
}
function Assert-Throws {
  param([scriptblock]$Action, [string]$Expected)
  $caught = $false
  try { & $Action } catch {
    $caught = $true
    if ($_.Exception.Message -notlike "*$Expected*") { throw }
  }
  if (-not $caught) { throw "Expected rejection containing: $Expected" }
}
function Test-Tag {
  Assert-MasterReleaseTag -ReleaseRepoName 'owner/source' -VersionTag 'v0.6.1' -SourceCommit $script:sha
}
foreach ($scenario in @('lightweight', 'annotated')) {
  $script:scenario = $scenario
  if (-not (Test-Tag)) { throw "Failed valid $scenario tag" }
}
$script:scenario = 'absent'
if (Test-Tag) { throw 'Absent tag treated as present' }
$script:scenario = 'mismatch'
Assert-Throws { Test-Tag } 'does not point to built source'
$script:scenario = 'network-failure'
Assert-Throws { Test-Tag } 'Unable to verify'
$script:scenario = 'lightweight'
Assert-Throws {
  Assert-MasterReleaseAssetsAvailable 'owner/source' 'v0.6.1' @('new.zip', 'manifest.json')
} 'already exists'
Assert-MasterReleaseAssetsAvailable 'owner/source' 'v0.6.1' @('new.zip')
$source = @{ SourceRootPath = '.'; SourceRepoName = 'owner/source'; ReleaseRepoName = 'owner/source'; SourceCommit = $script:sha; RequestedSourceRef = 'main' }
Assert-MasterPublicationSource @source
Assert-Throws { Assert-MasterPublicationSource @source -ReuseBuild } 'cannot use SkipBuild'
$source.ReleaseRepoName = 'owner/releases'
Assert-Throws { Assert-MasterPublicationSource @source } 'release_repo to equal source_repo'
$source.ReleaseRepoName = 'owner/source'
$script:dirty = ' M app.py'
Assert-Throws { Assert-MasterPublicationSource @source } 'clean source checkout'
$script:dirty = ''
$script:head = $script:otherSha
Assert-Throws { Assert-MasterPublicationSource @source } 'HEAD changed'
$script:head = $script:sha
$script:requested = $script:otherSha
Assert-Throws { Assert-MasterPublicationSource @source } 'SourceRef does not resolve'
foreach ($call in $script:ghCalls) {
  if ($call[0] -ne 'api' -and $call[1] -ne 'view') { throw 'Mutating GitHub call attempted' }
}
Write-Host 'PASS: isolated Master publication provenance guards (all GitHub calls mocked)'
