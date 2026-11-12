<#
.SYNOPSIS
    Run one sync cycle now: POST /sync/run as admin (PB-42-7, act 5).

.DESCRIPTION
    Aggregates the unsent transactions and sends the pending batches to HQ. Prints
    the HTTP status, the code and the body. 404 means /sync/run is not on main yet:
    wait for the SYNC_INTERVAL cycle instead.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/demo/sync_run.ps1
#>
[CmdletBinding()]
param(
    [string]$BaseUrl = "https://localhost:8443/api/v1",
    [string]$Token = "admin",
    [string]$TokensPath,
    [string]$CaPath
)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_demo_http.ps1")
$common = New-DemoCommonArgs -TokensPath $TokensPath -CaPath $CaPath

$result = Invoke-DemoApi -Method POST -Url "$($BaseUrl.TrimEnd('/'))/sync/run" -TokenName $Token @common
if ($result.Status -eq 404) {
    Write-Host "Not deployed: /sync/run is not on this middleware yet. Wait for the SYNC_INTERVAL cycle."
}
Exit-Demo $result
