<#
.SYNOPSIS
    Run a daily job now: POST /admin/jobs/{name}/run as admin (act 6).

.DESCRIPTION
    For example near-expiry (#43) or forecast (PB-22/23). The call answers when the
    job ends. 404 NOT_FOUND means no daily job has this name on this middleware
    yet; 409 JOB_RUNNING means a run is already in progress.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/demo/run_job.ps1 -Name near-expiry
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidatePattern('^[A-Za-z0-9_-]{1,50}$')][string]$Name,
    [string]$BaseUrl = "https://localhost:8443/api/v1",
    [string]$Token = "admin",
    [int]$TimeoutSeconds = 120,
    [string]$TokensPath,
    [string]$CaPath
)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_demo_http.ps1")
$common = New-DemoCommonArgs -TokensPath $TokensPath -CaPath $CaPath

$url = "$($BaseUrl.TrimEnd('/'))/admin/jobs/$Name/run"
$result = Invoke-DemoApi -Method POST -Url $url -TokenName $Token -TimeoutSeconds $TimeoutSeconds @common
if ($result.Status -eq 404) { Write-Host "Not deployed: no daily job named '$Name' on this middleware yet." }
Exit-Demo $result
