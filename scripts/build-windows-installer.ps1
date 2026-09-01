param(
  [Parameter(Mandatory = $true)]
  [string]$ConfigPath,
  [Parameter(Mandatory = $true)]
  [string]$DistDir,
  [Parameter(Mandatory = $true)]
  [string]$ReleaseTag,
  [Parameter(Mandatory = $true)]
  [string]$Version,
  [Parameter(Mandatory = $true)]
  [string]$OutputPath
)

$ErrorActionPreference = 'Stop'

function Get-InnoCompiler {
  param([Parameter(Mandatory = $true)][string]$ExpectedVersion)

  $candidates = [System.Collections.Generic.List[string]]::new()
  if ($env:ISCC_PATH) {
    $candidates.Add($env:ISCC_PATH) | Out-Null
  }
  $command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
  if ($command) {
    $candidates.Add($command.Source) | Out-Null
  }
  if (${env:ProgramFiles(x86)}) {
    $candidates.Add(
      (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe')
    ) | Out-Null
  }
  if ($env:ProgramFiles) {
    $candidates.Add(
      (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe')
    ) | Out-Null
  }

  foreach ($candidate in $candidates) {
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
      continue
    }
    $resolved = (Resolve-Path -LiteralPath $candidate).Path
    $actualVersion = (Get-Item -LiteralPath $resolved).VersionInfo.ProductVersion
    $versionMatches = $actualVersion.StartsWith(
      $ExpectedVersion,
      [System.StringComparison]::Ordinal
    )
    if (-not $versionMatches) {
      $revisionHistory = Join-Path (Split-Path -Parent $resolved) 'whatsnew.htm'
      if (Test-Path -LiteralPath $revisionHistory -PathType Leaf) {
        $versionPattern = '<span class="ver">' + [regex]::Escape($ExpectedVersion) + '\s'
        $versionMatches = [regex]::IsMatch(
          (Get-Content -LiteralPath $revisionHistory -Raw),
          $versionPattern
        )
      }
    }
    if (-not $versionMatches) {
      throw "Inno Setup $ExpectedVersion is required at $resolved"
    }
    return $resolved
  }

  throw "Inno Setup $ExpectedVersion compiler was not found. Set ISCC_PATH or install Inno Setup."
}

function ConvertTo-InnoLiteral {
  param([Parameter(Mandatory = $true)][string]$Value)

  return $Value.Replace('"', '""')
}

function Invoke-HiddenProcess {
  param(
    [Parameter(Mandatory = $true)][string]$FilePath,
    [string[]]$Arguments = @(),
    [switch]$AllowFailure
  )

  $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
  $startInfo.FileName = $FilePath
  $startInfo.UseShellExecute = $false
  $startInfo.CreateNoWindow = $true
  foreach ($argument in $Arguments) {
    $startInfo.ArgumentList.Add($argument)
  }
  $process = [System.Diagnostics.Process]::Start($startInfo)
  if ($null -eq $process) {
    throw "Failed to start process: $FilePath"
  }
  try {
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) {
      if ($AllowFailure) {
        return $process.ExitCode
      }
      throw "$FilePath failed with exit code $($process.ExitCode)"
    }
    if ($AllowFailure) {
      return 0
    }
  }
  finally {
    $process.Dispose()
  }
}

function Wait-PathAbsent {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [int]$TimeoutSeconds = 15
  )

  $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
  do {
    if (-not (Test-Path -LiteralPath $Path)) {
      return
    }
    Start-Sleep -Milliseconds 100
  } while ([DateTime]::UtcNow -lt $deadline)

  throw "Path still exists after waiting $TimeoutSeconds seconds: $Path"
}

function Assert-SelfTest {
  param(
    [Parameter(Mandatory = $true)][string]$ExecutablePath,
    [Parameter(Mandatory = $true)][string]$ResultPath
  )

  if (Test-Path -LiteralPath $ResultPath) {
    Remove-Item -LiteralPath $ResultPath -Force
  }
  $exitCode = Invoke-HiddenProcess `
    -FilePath $ExecutablePath `
    -Arguments @('--self-test', '--result-json', $ResultPath) `
    -AllowFailure
  if (-not (Test-Path -LiteralPath $ResultPath -PathType Leaf)) {
    throw "Self-test exited with code $exitCode and did not create its result JSON: $ResultPath"
  }
  $result = Get-Content -LiteralPath $ResultPath -Raw | ConvertFrom-Json
  if ($result.status -ne 'ok') {
    throw "Package self-test failed with exit code ${exitCode}: $($result.errors -join '; ')"
  }
  if ($exitCode -ne 0) {
    throw "Package self-test reported status ok but exited with code $exitCode"
  }
}

function Assert-ForbiddenNamesAbsent {
  param(
    [Parameter(Mandatory = $true)][string]$Root,
    [string[]]$ForbiddenNames = @()
  )

  $matches = [System.Collections.Generic.List[string]]::new()
  foreach ($file in Get-ChildItem -LiteralPath $Root -File -Recurse) {
    $relativePath = $file.FullName.Substring($Root.Length).TrimStart('\', '/')
    foreach ($forbiddenName in $ForbiddenNames) {
      if ($relativePath.IndexOf(
          $forbiddenName,
          [System.StringComparison]::OrdinalIgnoreCase
        ) -ge 0) {
        $matches.Add($relativePath) | Out-Null
        break
      }
    }
  }
  if ($matches.Count -gt 0) {
    throw "Forbidden runtime files were packaged: $($matches -join ', ')"
  }
}

function New-InnoScript {
  param(
    [Parameter(Mandatory = $true)][object]$Installer,
    [Parameter(Mandatory = $true)][string]$SourceDirectory,
    [Parameter(Mandatory = $true)][string]$ApplicationVersion,
    [Parameter(Mandatory = $true)][string]$ScriptPath
  )

  $appId = (ConvertTo-InnoLiteral ([string]$Installer.app_id)).Replace('{', '{{')
  $appName = ConvertTo-InnoLiteral ([string]$Installer.app_name)
  $publisher = ConvertTo-InnoLiteral ([string]$Installer.publisher)
  $defaultDirName = ConvertTo-InnoLiteral ([string]$Installer.default_dir_name)
  $executable = ConvertTo-InnoLiteral ([string]$Installer.executable)
  $startMenuName = ConvertTo-InnoLiteral ([string]$Installer.start_menu_name)
  $desktopShortcutName = ConvertTo-InnoLiteral ([string]$Installer.desktop_shortcut_name)
  $escapedSourceDirectory = ConvertTo-InnoLiteral $SourceDirectory

  $script = @"
[Setup]
AppId=$appId
AppName=$appName
AppVersion=$ApplicationVersion
AppPublisher=$publisher
DefaultDirName=$defaultDirName
DefaultGroupName=$startMenuName
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64os
ArchitecturesInstallIn64BitMode=x64os
OutputBaseFilename=setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\$executable
VersionInfoVersion=$ApplicationVersion
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
Source: "$escapedSourceDirectory\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\$startMenuName"; Filename: "{app}\$executable"; WorkingDir: "{app}"
Name: "{autodesktop}\$desktopShortcutName"; Filename: "{app}\$executable"; WorkingDir: "{app}"; Tasks: desktopicon
"@
  $script | Set-Content -LiteralPath $ScriptPath -Encoding UTF8
}

function Invoke-InstallerSmokeTest {
  param(
    [Parameter(Mandatory = $true)][string]$SetupPath,
    [Parameter(Mandatory = $true)][string]$ExecutableName
  )

  $testId = [System.Guid]::NewGuid().ToString('N')
  $installDir = Join-Path ([System.IO.Path]::GetTempPath()) "emo-master-install-$testId"
  $resultPath = Join-Path ([System.IO.Path]::GetTempPath()) "emo-master-installed-$testId.json"
  $userDataRoot = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.emo_master'
  New-Item -ItemType Directory -Path $userDataRoot -Force | Out-Null
  $userDataMarker = Join-Path $userDataRoot "packaging-smoke-$testId.txt"
  'preserve' | Set-Content -LiteralPath $userDataMarker -Encoding UTF8

  try {
    Invoke-HiddenProcess `
      -FilePath $SetupPath `
      -Arguments @(
        '/VERYSILENT',
        '/SUPPRESSMSGBOXES',
        '/NORESTART',
        '/SP-',
        "/DIR=$installDir"
      )
    $installedExecutable = Join-Path $installDir $ExecutableName
    if (-not (Test-Path -LiteralPath $installedExecutable -PathType Leaf)) {
      throw "Installed executable was not found: $installedExecutable"
    }
    Assert-SelfTest -ExecutablePath $installedExecutable -ResultPath $resultPath

    $uninstaller = Join-Path $installDir 'unins000.exe'
    if (-not (Test-Path -LiteralPath $uninstaller -PathType Leaf)) {
      throw "Uninstaller was not found: $uninstaller"
    }
    Invoke-HiddenProcess `
      -FilePath $uninstaller `
      -Arguments @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART')
    # Inno Setup's uninstaller returns before its copied cleanup process removes
    # the final directory. Give that helper a bounded window to finish.
    Wait-PathAbsent -Path $installDir
    if (-not (Test-Path -LiteralPath $userDataMarker -PathType Leaf)) {
      throw 'Uninstall removed the user data marker under ~/.emo_master'
    }
  }
  finally {
    if (Test-Path -LiteralPath $userDataMarker -PathType Leaf) {
      Remove-Item -LiteralPath $userDataMarker -Force
    }
    if (Test-Path -LiteralPath $resultPath -PathType Leaf) {
      Remove-Item -LiteralPath $resultPath -Force
    }
  }
}

$resolvedConfigPath = (Resolve-Path -LiteralPath $ConfigPath).Path
$resolvedDistDir = (Resolve-Path -LiteralPath $DistDir).Path
$config = Get-Content -LiteralPath $resolvedConfigPath -Raw | ConvertFrom-Json
if (-not ($config.PSObject.Properties.Name -contains 'installer')) {
  throw 'Target config does not define installer settings'
}
$installer = $config.installer
if (-not $installer.enabled) {
  throw 'Installer is disabled for this target'
}
foreach ($field in @(
    'compiler_version',
    'app_id',
    'app_name',
    'publisher',
    'default_dir_name',
    'executable',
    'start_menu_name',
    'desktop_shortcut_name'
  )) {
  if (-not $installer.$field) {
    throw "Missing installer config field: $field"
  }
}

$portableExecutable = Join-Path $resolvedDistDir ([string]$installer.executable)
if (-not (Test-Path -LiteralPath $portableExecutable -PathType Leaf)) {
  throw "Portable executable was not found: $portableExecutable"
}
$forbiddenNames = @()
if ($installer.PSObject.Properties.Name -contains 'forbidden_names') {
  $forbiddenNames = @($installer.forbidden_names | ForEach-Object { [string]$_ })
}
Assert-ForbiddenNamesAbsent -Root $resolvedDistDir -ForbiddenNames $forbiddenNames

$portableResultPath = Join-Path ([System.IO.Path]::GetTempPath()) "emo-master-portable-$([System.Guid]::NewGuid().ToString('N')).json"
try {
  Assert-SelfTest -ExecutablePath $portableExecutable -ResultPath $portableResultPath
}
finally {
  if (Test-Path -LiteralPath $portableResultPath -PathType Leaf) {
    Remove-Item -LiteralPath $portableResultPath -Force
  }
}

$outputDirectory = Split-Path -Parent $OutputPath
New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
$outputBaseName = [System.IO.Path]::GetFileNameWithoutExtension($OutputPath)
$scriptPath = Join-Path ([System.IO.Path]::GetTempPath()) "emo-master-$([System.Guid]::NewGuid().ToString('N')).iss"
try {
  New-InnoScript `
    -Installer $installer `
    -SourceDirectory $resolvedDistDir `
    -ApplicationVersion $Version `
    -ScriptPath $scriptPath
  $compiler = Get-InnoCompiler -ExpectedVersion ([string]$installer.compiler_version)
  & $compiler "/O$outputDirectory" "/F$outputBaseName" $scriptPath
  if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup failed with exit code $LASTEXITCODE"
  }
}
finally {
  if (Test-Path -LiteralPath $scriptPath -PathType Leaf) {
    Remove-Item -LiteralPath $scriptPath -Force
  }
}

if (-not (Test-Path -LiteralPath $OutputPath -PathType Leaf)) {
  throw "Installer output was not created: $OutputPath"
}
if ($installer.smoke_test) {
  Invoke-InstallerSmokeTest `
    -SetupPath $OutputPath `
    -ExecutableName ([string]$installer.executable)
}

Write-Host "Installer created: $OutputPath"
