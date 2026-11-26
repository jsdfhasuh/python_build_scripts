param([Parameter(Mandatory)][string]$Root)

$ErrorActionPreference = 'Stop'
if ($env:RUNNER_ENVIRONMENT -ne 'github-hosted' -or $env:RUNNER_OS -ne 'Windows' -or
    $env:GITHUB_REPOSITORY -ne 'jsdfhasuh/python_build_scripts' -or
    $env:GITHUB_WORKFLOW -ne 'VisionWorkshop disconnected Windows guest' -or
    $env:GITHUB_REF -ne 'refs/heads/test/visionworkshop-modular-loader') {
    throw 'Use the dedicated disposable Windows GitHub-hosted job.'
}
$Root = (Resolve-Path -LiteralPath $Root).ProviderPath
$expected = (Resolve-Path -LiteralPath (Join-Path $env:RUNNER_TEMP 'vw-disconnected')).ProviderPath
if ($Root -ne $expected -or ((Get-Item -LiteralPath $Root).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
    throw 'Unexpected diagnostic directory.'
}
$reports = Join-Path $Root 'reports'
$taskName = 'VisionWorkshop-disconnected-' + [guid]::NewGuid().ToString('N')
$armed = Join-Path $reports 'watchdog-armed.json'
$restore = Join-Path $reports 'watchdog-restore.request'
$started = Join-Path $reports 'watchdog-restoring.json'
$restored = Join-Path $reports 'watchdog-restored.json'

function Write-NetworkReport($Name, $Value) {
    $Value | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $reports $Name) -Encoding utf8
}

$loopback = @((Get-NetIPAddress -PolicyStore ActiveStore | Where-Object IPAddress -in @('127.0.0.1', '::1')).InterfaceIndex)
if ($loopback.Count -eq 0) { throw 'Cannot identify Windows loopback.' }

function Get-NetworkSnapshot {
    $adapters = @(Get-NetAdapter -IncludeHidden | Select-Object Name, InterfaceGuid, InterfaceIndex, Status)
    $interfaces = @(Get-NetIPInterface -PolicyStore ActiveStore | Where-Object {
        $_.ConnectionState -eq 'Connected' -and $_.InterfaceIndex -notin $loopback
    } | Select-Object InterfaceIndex, InterfaceAlias, AddressFamily, ConnectionState)
    [ordered]@{ utc = [DateTime]::UtcNow.ToString('o'); adapters = $adapters; connectedExternalInterfaces = $interfaces }
}

function Test-DirectTcp([System.Net.IPAddress]$Address) {
    $client = [System.Net.Sockets.TcpClient]::new($Address.AddressFamily)
    try {
        return $client.ConnectAsync($Address, 443).Wait(4000) -and $client.Connected
    } catch [System.AggregateException] {
        return $false
    } catch [System.Net.Sockets.SocketException] {
        return $false
    } finally {
        $client.Dispose()
    }
}

function Assert-Disconnected($Snapshot) {
    $disabled = @($Snapshot.adapters | Where-Object {
        $_.InterfaceGuid -and ([guid]$_.InterfaceGuid).ToString('D') -in $adapterIds -and $_.Status -eq 'Disabled'
    })
    if ($disabled.Count -ne $adapterIds.Count -or @($Snapshot.adapters | Where-Object Status -eq 'Up').Count -or
        $Snapshot.connectedExternalInterfaces.Count -or (Test-Path -LiteralPath $started)) {
        throw 'The dedicated Windows guest did not stay disconnected.'
    }
}

$before = Get-NetworkSnapshot
$adapterIds = @($before.adapters | Where-Object Status -eq 'Up' | ForEach-Object { ([guid]$_.InterfaceGuid).ToString('D') })
if ($adapterIds.Count -eq 0 -or @($adapterIds | Select-Object -Unique).Count -ne $adapterIds.Count -or
    ($before.connectedExternalInterfaces.InterfaceIndex | Where-Object { $_ -notin $before.adapters.InterfaceIndex })) {
    throw 'Cannot bind every connected interface to the guest adapter inventory.'
}
$ipv4 = [System.Net.Dns]::GetHostAddresses('api.github.com') | Where-Object AddressFamily -eq InterNetwork | Select-Object -First 1
if (-not $ipv4 -or -not (Test-DirectTcp $ipv4)) { throw 'External TCP control failed before disconnection.' }
Write-NetworkReport 'network-before.json' @{ state = $before; directTcp = $true; address = $ipv4.ToString(); adapterIds = $adapterIds }

# The SYSTEM process receives the exact restoration set in its command. It does
# not depend on Actions connectivity or a runner-owned file after it starts.
$reportLiteral = "'" + $reports.Replace("'", "''") + "'"
$idLiteral = "@('" + ($adapterIds -join "','") + "')"
$watchdog = @'
$ErrorActionPreference = 'Stop'
if ([Security.Principal.WindowsIdentity]::GetCurrent().User.Value -ne 'S-1-5-18') { throw 'Expected the SYSTEM watchdog.' }
$clock = [Diagnostics.Stopwatch]::StartNew()
$armedTemp = Join-Path $reports 'watchdog-armed.tmp'
@{ pid = $PID; adapterIds = $ids; utc = [DateTime]::UtcNow.ToString('o') } | ConvertTo-Json | Set-Content -LiteralPath $armedTemp
Move-Item -LiteralPath $armedTemp -Destination (Join-Path $reports 'watchdog-armed.json')
while (-not (Test-Path -LiteralPath (Join-Path $reports 'watchdog-restore.request')) -and $clock.Elapsed.TotalSeconds -lt 270) {
    Start-Sleep -Milliseconds 500
}
try {
    Set-Content -LiteralPath (Join-Path $reports 'watchdog-restoring.json') -Value ([DateTime]::UtcNow.ToString('o')) -ErrorAction Continue
    $all = @(Get-NetAdapter -IncludeHidden | Where-Object { $_.InterfaceGuid -and ([guid]$_.InterfaceGuid).ToString('D') -in $ids })
    if ($all.Count -ne $ids.Count) { throw 'The restoration adapter set changed.' }
    $down = @($all | Where-Object Status -eq 'Disabled')
    if ($down.Count) { Enable-NetAdapter -InputObject $down -Confirm:$false }
    @{ pid = $PID; adapterIds = $ids; utc = [DateTime]::UtcNow.ToString('o'); enabled = $down.Count } |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $reports 'watchdog-restored.json') -ErrorAction Continue
} catch {
    $_ | Out-String | Set-Content -LiteralPath (Join-Path $reports 'watchdog-error.txt') -ErrorAction Continue
    throw
}
'@
$encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes("`$reports=$reportLiteral`n`$ids=$idLiteral`n$watchdog"))
$action = New-ScheduledTaskAction -Execute (Join-Path $PSHOME 'pwsh.exe') -Argument "-NoProfile -NonInteractive -EncodedCommand $encoded"
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 6) -MultipleInstances IgnoreNew
$registered = $false
$testChild = $null
$passed = $false
$samples = [Collections.Generic.List[object]]::new()
try {
    Register-ScheduledTask -TaskName $taskName -Action $action -Principal $principal -Settings $settings | Out-Null
    $registered = $true
    Start-ScheduledTask -TaskName $taskName
    $wait = [Diagnostics.Stopwatch]::StartNew()
    while (-not (Test-Path -LiteralPath $armed) -and $wait.Elapsed.TotalSeconds -lt 20) { Start-Sleep -Milliseconds 250 }
    $watchdogTask = Get-ScheduledTask -TaskName $taskName
    if (-not (Test-Path -LiteralPath $armed) -or $watchdogTask.State -ne 'Running') { throw 'The independent watchdog is not armed.' }
    $armedRecord = Get-Content -Raw -LiteralPath $armed | ConvertFrom-Json
    if (@(Compare-Object $adapterIds @($armedRecord.adapterIds)).Count) { throw 'Wrong watchdog adapter set.' }

    $present = @(Get-NetAdapter -IncludeHidden | Where-Object Status -eq 'Up')
    if (@(Compare-Object $adapterIds @($present | ForEach-Object { ([guid]$_.InterfaceGuid).ToString('D') })).Count) {
        throw 'The active adapter set changed after arming.'
    }
    $offlineClock = [Diagnostics.Stopwatch]::StartNew()
    Disable-NetAdapter -InputObject $present -Confirm:$false
    $disconnected = Get-NetworkSnapshot
    Assert-Disconnected $disconnected
    if (Test-DirectTcp $ipv4) { throw 'External TCP control still connects with the guest disconnected.' }
    Write-NetworkReport 'network-disconnected.json' @{ state = $disconnected; directTcp = $false; address = $ipv4.ToString() }
    $testChild = Start-Process -FilePath (Get-Command python.exe).Source -WindowStyle Hidden -PassThru `
        -WorkingDirectory (Split-Path -Parent $PSScriptRoot) `
        -ArgumentList @('-B', '-m', 'scripts.verify_vision_train_disconnected', 'lifecycle', "`"$Root`"") `
        -RedirectStandardOutput (Join-Path $reports 'lifecycle.stdout.txt') `
        -RedirectStandardError (Join-Path $reports 'lifecycle.stderr.txt')
    while (-not $testChild.WaitForExit(5000)) {
        $snapshot = Get-NetworkSnapshot
        $samples.Add($snapshot)
        Assert-Disconnected $snapshot
        if ($offlineClock.Elapsed.TotalSeconds -gt 215) { throw 'The offline lifecycle exceeded its bounded window.' }
    }
    $lastOffline = Get-NetworkSnapshot
    Assert-Disconnected $lastOffline
    if (Test-DirectTcp $ipv4) { throw 'External TCP became reachable before the lifecycle ended.' }
    Write-NetworkReport 'network-still-disconnected.json' @{ state = $lastOffline; directTcp = $false; child = $testChild.Id; exitCode = $testChild.ExitCode }
    if ($testChild.ExitCode -ne 0) { throw 'The disconnected EXE lifecycle failed.' }
    $passed = $true
} finally {
    try {
        if ($testChild -and -not $testChild.HasExited) { $testChild.Kill($true); $testChild.WaitForExit(10000) | Out-Null }
    } finally {
        if ($registered) {
            Set-Content -LiteralPath $restore -Value 'restore' -Encoding ascii
            $recoverClock = [Diagnostics.Stopwatch]::StartNew()
            do {
                Start-Sleep -Milliseconds 500
                $after = Get-NetworkSnapshot
                $up = @($after.adapters | Where-Object { $_.InterfaceGuid -and ([guid]$_.InterfaceGuid).ToString('D') -in $adapterIds -and $_.Status -eq 'Up' })
                $tcpRestored = $up.Count -eq $adapterIds.Count -and (Test-DirectTcp $ipv4)
                $ready = $tcpRestored -and (Test-Path -LiteralPath $restored) -and (Get-ScheduledTask -TaskName $taskName).State -eq 'Ready'
            } until ($ready -or $recoverClock.Elapsed.TotalSeconds -gt 45)
            Write-NetworkReport 'network-after.json' @{ state = $after; directTcp = $tcpRestored; watcherRestored = $ready; offlineWindowPassed = $passed }
            Write-NetworkReport 'network-during.json' @{ samples = @($samples.ToArray()) }
            if (-not $ready) { throw 'Did not verify that the original guest connectivity was restored.' }
            Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
            if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) { throw 'The watchdog task was not removed.' }
            Write-NetworkReport 'network-cleanup.json' @{ watchdogTask = $taskName; removed = $true }
        }
    }
}
