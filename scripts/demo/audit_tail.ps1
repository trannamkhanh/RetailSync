<#
.SYNOPSIS
    The latest audit rows: GET /audit-logs as auditor (acts 2 to 5).

.DESCRIPTION
    Prints the status line, then the rows newest first (time, action, entity key,
    details). -Action keeps one action only, for example DUPLICATE_EVENT,
    EVENT_REJECTED or SNAPSHOT_REJECTED.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/demo/audit_tail.ps1 -Limit 10 -Action STOCK_CHANGE
#>
[CmdletBinding()]
param(
    [ValidateRange(1, 500)][int]$Limit = 15,
    [ValidatePattern('^[A-Za-z0-9_-]{0,50}$')][string]$Action = "",
    [string]$BaseUrl = "https://localhost:8443/api/v1",
    [string]$Token = "auditor",
    [string]$TokensPath,
    [string]$CaPath
)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_demo_http.ps1")
$common = New-DemoCommonArgs -TokensPath $TokensPath -CaPath $CaPath

$url = "$($BaseUrl.TrimEnd('/'))/audit-logs?limit=$Limit"
if ($Action) { $url += "&action=$Action" }
$result = Invoke-DemoApi -Method GET -Url $url -TokenName $Token @common
if ($result.Status -eq 200) {
    $items = @(($result.Body | ConvertFrom-Json).items)
    Write-Host "$($items.Count) rows, newest first:"
    $items | ForEach-Object {
        [pscustomobject]@{
            Time    = $_.created_at
            Action  = $_.action
            Key     = $_.entity_key
            Details = Format-DemoBody $_.details 70
        }
    } | Format-Table -AutoSize | Out-String -Width 220 | Write-Host
}
Exit-Demo $result
