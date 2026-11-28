param(
    [Parameter(Mandatory)][ValidateSet('host', 'guest')][string]$Mode,
    [string]$Staged,
    [string]$Endpoint
)

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false

function Test-DirectTcp([Net.IPAddress]$Address) {
    $client = [Net.Sockets.TcpClient]::new($Address.AddressFamily)
    try {
        return $client.ConnectAsync($Address, 443).Wait(3000) -and $client.Connected
    } catch [AggregateException] {
        return $false
    } catch [Net.Sockets.SocketException] {
        return $false
    } finally {
        $client.Dispose()
    }
}

function Save-Report($Path, $Data) {
    $Data | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Get-GuestNetwork([Net.IPAddress]$Address) {
    $interfaces = @([Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces() | ForEach-Object {
        [ordered]@{ name = $_.Name; kind = $_.NetworkInterfaceType.ToString(); status = $_.OperationalStatus.ToString()
                    addresses = @($_.GetIPProperties().UnicastAddresses | ForEach-Object { $_.Address.ToString() }) }
    })
    $tcp = Test-DirectTcp $Address
    [ordered]@{ utc = [DateTime]::UtcNow.ToString('o'); interfaces = $interfaces; endpoint = $Address.ToString(); directTcp = $tcp }
}

function Assert-GuestDisconnected($Snapshot) {
    $external = @($Snapshot.interfaces | Where-Object { $_.kind -ne 'Loopback' -and $_.status -eq 'Up' })
    $externalAddresses = @($Snapshot.interfaces.addresses | Where-Object {
        $_ -and -not [Net.IPAddress]::IsLoopback([Net.IPAddress]::Parse($_))
    })
    if ($external.Count -or $externalAddresses.Count -or $Snapshot.directTcp) {
        throw 'The isolated Windows container has external connectivity.'
    }
}

if ($Mode -eq 'guest') {
    $root = 'C:\vw-validation'
    if ($Staged -ne 'C:\vw-staged' -or (Test-Path -LiteralPath $root)) { throw 'Unexpected container scratch state.' }
    $reports = Join-Path $root 'reports'
    New-Item -ItemType Directory -Path $reports -Force | Out-Null
    $drive = [IO.DriveInfo]::new('C')
    Save-Report (Join-Path $reports 'scratch-volume.json') @{ format = $drive.DriveFormat; freeBytes = $drive.AvailableFreeSpace }
    if ($drive.DriveFormat -ne 'NTFS' -or $drive.AvailableFreeSpace -lt 9GB) { throw 'The container does not have enough native NTFS scratch space.' }
    $address = [Net.IPAddress]::Parse($Endpoint)
    $samples = New-Object 'Collections.Generic.List[object]'
    $child = $null
    try {
        $first = Get-GuestNetwork $address
        Save-Report (Join-Path $reports 'network-before.json') $first
        Assert-GuestDisconnected $first
        $env:PYTHONUTF8 = '1'
        $env:PYTHONDONTWRITEBYTECODE = '1'
        $child = Start-Process -FilePath 'C:\vw-driver\python.exe' -WindowStyle Hidden -PassThru `
            -WorkingDirectory 'C:\vw-source' `
            -ArgumentList @('-B', '-m', 'scripts.verify_vision_train_disconnected', 'continuous', $root, '--scope', 'all', '--staged', $Staged) `
            -RedirectStandardOutput (Join-Path $reports 'product.stdout.txt') `
            -RedirectStandardError (Join-Path $reports 'product.stderr.txt')
        # Windows PowerShell 5.1 otherwise loses the exit code of the redirected process.
        $null = $child.Handle
        while (-not $child.WaitForExit(12000)) {
            $snapshot = Get-GuestNetwork $address
            $samples.Add($snapshot)
            Assert-GuestDisconnected $snapshot
        }
        $last = Get-GuestNetwork $address
        Save-Report (Join-Path $reports 'network-after.json') $last
        Assert-GuestDisconnected $last
        $exitCode = $child.ExitCode
        Save-Report (Join-Path $reports 'guest-driver-process.json') @{ pid = $child.Id; exitCode = $exitCode }
        if ($null -eq $exitCode) { throw 'The guest validator could not read the product driver process exit code.' }
        if ($exitCode -ne 0) {
            Get-Content -LiteralPath (Join-Path $reports 'product.stderr.txt') -Tail 24 | Write-Output
            throw "The disconnected product lifecycle exited with $exitCode."
        }
    } finally {
        if ($child) {
            try {
                if (-not $child.HasExited) { $child.Kill(); $child.WaitForExit(5000) | Out-Null }
            } finally {
                $child.Dispose()
            }
        }
        Save-Report (Join-Path $reports 'network-during.json') @{ samples = @($samples.ToArray()); parentPid = $PID }
    }
    exit 0
}

if ($env:RUNNER_ENVIRONMENT -ne 'github-hosted' -or $env:RUNNER_OS -ne 'Windows' -or
    $env:GITHUB_REPOSITORY -ne 'jsdfhasuh/python_build_scripts' -or
    $env:GITHUB_WORKFLOW -ne 'VisionWorkshop continuous offline Windows' -or
    $env:GITHUB_REF -ne 'refs/heads/test/visionworkshop-modular-loader') {
    throw 'Use the dedicated disposable Windows GitHub-hosted job.'
}
$Staged = (Resolve-Path -LiteralPath $Staged).ProviderPath
$expected = (Resolve-Path -LiteralPath (Join-Path $env:RUNNER_TEMP 'vw-offline-staged')).ProviderPath
if ($Staged -ne $expected -or ((Get-Item -LiteralPath $Staged).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
    throw 'Unexpected staged input directory.'
}
$reports = Join-Path $Staged 'reports'
$source = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).ProviderPath
$driver = (Resolve-Path -LiteralPath $env:pythonLocation).ProviderPath
$address = [Net.Dns]::GetHostAddresses('api.github.com') | Where-Object AddressFamily -eq InterNetwork | Select-Object -First 1
if (-not $address -or -not (Test-DirectTcp $address)) { throw 'Host direct TCP control failed.' }
if ((docker info --format '{{.OSType}}') -ne 'windows' -or $LASTEXITCODE -ne 0) { throw 'Expected a native Windows Docker engine.' }

$base = 'mcr.microsoft.com/windows/servercore:ltsc2022'
$image = docker image inspect --format '{{.Id}}' $base
if ($LASTEXITCODE -ne 0 -or $image -notmatch '^sha256:[0-9a-f]{64}$') { throw 'Cannot bind the cached Windows Server Core image ID.' }
$repoDigests = @(docker image inspect --format '{{json .RepoDigests}}' $base | ConvertFrom-Json)
$probe = @(docker run --rm --pull=never --network none --isolation=hyperv $image cmd.exe /c ver 2>&1 | ForEach-Object { [string]$_ })
$probeCode = $LASTEXITCODE
$isolation = if ($probeCode -eq 0) { 'hyperv' } else { 'process' }
Save-Report (Join-Path $reports 'host-container-probe.json') @{ image = $image; imageRepoDigests = $repoDigests; base = $base; hypervExit = $probeCode; hyperv = $probe
    actualIsolation = $isolation; connectedControl = $true; endpoint = $address.ToString() }

$id = docker create --pull=never --network none "--isolation=$isolation" `
    --mount "type=bind,source=$Staged,target=C:\vw-staged,readonly" `
    --mount "type=bind,source=$source,target=C:\vw-source,readonly" `
    --mount "type=bind,source=$driver,target=C:\vw-driver,readonly" `
    $image powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass `
    -File 'C:\vw-source\scripts\verify_vision_train_offline_container.ps1' -Mode guest -Staged 'C:\vw-staged' -Endpoint $address.ToString()
if ($LASTEXITCODE -ne 0 -or $id -notmatch '^[0-9a-f]{64}$') { throw 'Cannot create the identified diagnostic container.' }
try {
    $record = @(docker inspect $id | Out-String | ConvertFrom-Json)[0]
    $attached = @($record.NetworkSettings.Networks.PSObject.Properties.Name | Where-Object { $_ -and $_ -ne 'none' })
    if ($record.HostConfig.NetworkMode -ne 'none' -or $record.HostConfig.Isolation -ne $isolation -or $attached.Count -or
        $record.Mounts.Count -ne 3 -or @($record.Mounts | Where-Object RW).Count) {
        throw 'The created container does not match the isolated read-only inputs.'
    }
    Save-Report (Join-Path $reports 'host-container-identity.json') @{ id = $id; image = $record.Image; mode = $record.HostConfig.NetworkMode
        isolation = $record.HostConfig.Isolation; mounts = @($record.Mounts | Select-Object Destination, RW) }
    docker start --attach $id
    $result = $LASTEXITCODE
    $destination = Join-Path $reports 'guest'
    if (Test-Path -LiteralPath $destination) { throw 'The guest evidence directory must be new.' }
    docker cp "${id}:C:/vw-validation/reports" $destination
    $copyCode = $LASTEXITCODE
    if ($copyCode -ne 0) {
        docker cp "${id}:C:/vw-validation/reports/product.stderr.txt" (Join-Path $reports 'guest-product.stderr.txt')
    }
    $online = Test-DirectTcp $address
    Save-Report (Join-Path $reports 'host-after.json') @{ childExitCode = $result; reportsCopyExitCode = $copyCode; directTcp = $online }
    if ($result -ne 0 -or $copyCode -ne 0 -or -not $online) { throw 'Container lifecycle or evidence collection failed.' }
} finally {
    docker rm --force $id | Out-Null
}
