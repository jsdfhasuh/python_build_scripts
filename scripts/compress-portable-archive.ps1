param(
  [Parameter(Mandatory = $true)][string]$DistDir,
  [Parameter(Mandatory = $true)][string]$AssetPath
)
$ErrorActionPreference = 'Stop'
if (Test-Path -LiteralPath $AssetPath) {
  throw 'Refusing to overwrite an archive'
}
Compress-Archive -LiteralPath $DistDir -DestinationPath $AssetPath -ErrorAction Stop
