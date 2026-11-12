<#
.SYNOPSIS
    Cross-store stock of one product, nearest store first (act 6, step 3, PB-35).

.DESCRIPTION
    GET /products/barcode/{barcode}/stock?from_store={store} with the Staff token of
    that store. Runs on machine A with -BaseUrl pointing at machine S; copy
    .certs/ca.crt and .tokens/demo_tokens.json from S into the repository on A
    first. Prints the stores as a table after the status line. 404 means the route
    is not on main yet (PB-35) or the barcode is unknown; the message says which.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/demo/cross_store.ps1 -Barcode 8930000000011 -Store STORE-DN1 -Token staff_dn1 -BaseUrl https://192.168.1.10:8443/api/v1
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidatePattern('^[A-Za-z0-9-]{1,30}$')][string]$Barcode,
    [ValidatePattern('^[A-Za-z0-9_-]{1,10}$')][string]$Store = "STORE-DN1",
    [string]$Token = "staff_dn1",
    [string]$BaseUrl = "https://localhost:8443/api/v1",
    [string]$TokensPath,
    [string]$CaPath
)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_demo_http.ps1")
$common = New-DemoCommonArgs -TokensPath $TokensPath -CaPath $CaPath

$url = "$($BaseUrl.TrimEnd('/'))/products/barcode/$Barcode/stock?from_store=$Store"
$result = Invoke-DemoApi -Method GET -Url $url -TokenName $Token @common
if ($result.Status -eq 200) {
    $data = $result.Body | ConvertFrom-Json
    Write-Host "SKU $($data.sku), asked from $Store, nearest first:"
    @($data.stores) | Format-Table store_id, name, qty, distance_km -AutoSize | Out-String | Write-Host
}
Exit-Demo $result
