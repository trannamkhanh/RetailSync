<#
.SYNOPSIS
    Switch the HQ demo scenario: PUT /demo/mode on the HQ demo service (act 5).

.DESCRIPTION
    ONLINE answers ACK, OFFLINE and ERROR answer 503, SLOW waits 4 seconds (longer
    than the middleware's 3 second timeout), DROP_ACK stores the batch and answers
    500. The route needs no token. The mode lives in memory and is ONLINE again
    after hq-demo restarts.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/demo/hq_mode.ps1 -Mode OFFLINE
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet("ONLINE", "OFFLINE", "ERROR", "SLOW", "DROP_ACK")][string]$Mode,
    [string]$HqBaseUrl = "https://localhost:9000/api/v1",
    [string]$CaPath
)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_demo_http.ps1")
$common = New-DemoCommonArgs -CaPath $CaPath

$body = '{"mode":"' + $Mode.ToUpperInvariant() + '"}'
$result = Invoke-DemoApi -Method PUT -Url "$($HqBaseUrl.TrimEnd('/'))/demo/mode" -Body $body @common
Exit-Demo $result
