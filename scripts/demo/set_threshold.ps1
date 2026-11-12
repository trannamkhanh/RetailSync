<#
.SYNOPSIS
    Set the near-expiry threshold of a category: PUT /admin/near-expiry-thresholds/{category} (act 6, step 2).

.DESCRIPTION
    Admin only. Run scripts/demo/run_job.ps1 -Name near-expiry afterwards to see the
    new alerts. Raising a threshold adds alerts; lowering it does not close alerts
    that are already OPEN (PB-21 keeps an open alert until its batch is sold out).
    404 means the route is not on main yet (#43).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/demo/set_threshold.ps1 -Category Dairy -Days 7
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateLength(1, 50)][string]$Category,
    [Parameter(Mandatory)][ValidateRange(0, 3650)][int]$Days,
    [string]$BaseUrl = "https://localhost:8443/api/v1",
    [string]$Token = "admin",
    [string]$TokensPath,
    [string]$CaPath
)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_demo_http.ps1")
$common = New-DemoCommonArgs -TokensPath $TokensPath -CaPath $CaPath

$url = "$($BaseUrl.TrimEnd('/'))/admin/near-expiry-thresholds/$([Uri]::EscapeDataString($Category))"
$result = Invoke-DemoApi -Method PUT -Url $url -TokenName $Token -Body ('{"threshold_days":' + $Days + '}') @common
if ($result.Status -eq 404) { Write-Host "Not deployed: the threshold API is not on this middleware yet." }
Exit-Demo $result
