<#
.SYNOPSIS
    Send a small HQ stock snapshot: POST /hq/snapshot as hq_operator (act 5, step 4).

.DESCRIPTION
    The middleware always refuses it (422 SNAPSHOT_REJECTED), writes the audit row
    SNAPSHOT_REJECTED and leaves the local stock unchanged (PB-13, NFR05). The
    sample body claims 999 units of SKU-0001 and SKU-0004 at the store, so an
    unchanged stock is easy to see. 404 means the route is not on main yet.
    The expected 422 SNAPSHOT_REJECTED exits 0.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/demo/hq_snapshot.ps1
#>
[CmdletBinding()]
param(
    [string]$BaseUrl = "https://localhost:8443/api/v1",
    [string]$Token = "hq_operator",
    [ValidatePattern('^[A-Za-z0-9_-]{1,10}$')][string]$StoreId = "STORE-DN1",
    [string]$TokensPath,
    [string]$CaPath
)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_demo_http.ps1")
$common = New-DemoCommonArgs -TokensPath $TokensPath -CaPath $CaPath

$takenAt = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
$body = '{"store_id":"' + $StoreId + '","taken_at":"' + $takenAt + '","items":[{"sku":"SKU-0001","quantity":999},{"sku":"SKU-0004","quantity":999}]}'
$result = Invoke-DemoApi -Method POST -Url "$($BaseUrl.TrimEnd('/'))/hq/snapshot" -TokenName $Token -Body $body @common
if ($result.Status -eq 404) { Write-Host "Not deployed: /hq/snapshot is not on this middleware yet." }
if ($result.Status -eq 422 -and (Get-DemoErrorCode $result.Body) -eq "SNAPSHOT_REJECTED") {
    Write-Host "Expected: the snapshot was refused and nothing changed."
    exit 0
}
Exit-Demo $result
