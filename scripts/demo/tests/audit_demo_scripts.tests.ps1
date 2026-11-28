<#
.SYNOPSIS
    Regression tests for audit findings #10 and #11a (reset_demo_db.ps1 and
    export_terminal_tokens.ps1). Windows PowerShell 5.1, no Pester, no Docker.

.DESCRIPTION
    Each case copies the real script into a temporary folder laid out like the
    repository. reset_demo_db.ps1 runs against a stub `docker` function and a stub
    Invoke-DemoApi (no HTTP, no database); export_terminal_tokens.ps1 runs on fake
    tokens and certificate files. The PB-41-2 cases run the six API scripts against
    a temporary .env and record the URL they would call. Exit code 0 when every
    case passes.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/demo/tests/audit_demo_scripts.tests.ps1
#>
$ErrorActionPreference = "Stop"
$DemoDir = Split-Path $PSScriptRoot
$script:Failures = 0
$script:Passes = 0

function Invoke-Case {
    param([string]$Name, [scriptblock]$Body)
    $start = Get-Location
    try {
        & $Body
        $script:Passes++
        Write-Host "PASS $Name"
    }
    catch {
        $script:Failures++
        Write-Host "FAIL $Name : $($_.Exception.Message)" -ForegroundColor Red
    }
    finally {
        Set-Location $start
    }
}

function Assert-That {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) { throw $Message }
}

function New-TempDir {
    $path = Join-Path ([IO.Path]::GetTempPath()) ("rts-audit-" + [guid]::NewGuid().ToString("N").Substring(0, 8))
    New-Item -ItemType Directory $path | Out-Null
    return (Resolve-Path $path).Path
}

# --- reset_demo_db.ps1 fixture ---------------------------------------------

$FakeDemoHttp = @'
function Invoke-DemoApi {
    param([string]$Method, [string]$Url, [string]$TokenName, [string]$Body,
          [int]$TimeoutSeconds, [switch]$Quiet)
    $global:AuditHttpCalls.Add("$Method $Url")
    $kind = if ($Url -like "*/health") { "health" } else { "job" }
    $queue = @($global:AuditHttpReplies[$kind])
    $reply = $queue[0]
    if ($queue.Count -gt 1) { $global:AuditHttpReplies[$kind] = $queue[1..($queue.Count - 1)] }
    return [pscustomobject]@{ Status = $reply[0]; Body = $reply[1]; Error = "stub" }
}
'@

$SqlPassword = "Audit-Test-Pass-9!"

function Invoke-ResetFixture {
    param([string]$BindAddress, [hashtable]$Replies, [hashtable]$ScriptArgs = @{})
    $root = New-TempDir
    $demo = Join-Path $root "scripts\demo"
    New-Item -ItemType Directory $demo | Out-Null
    Copy-Item (Join-Path $DemoDir "reset_demo_db.ps1") $demo
    # The real helpers (the .env reader), then the stub Invoke-DemoApi replaces the real one.
    Copy-Item (Join-Path $DemoDir "_demo_http.ps1") $demo
    Add-Content -Encoding ASCII (Join-Path $demo "_demo_http.ps1") $FakeDemoHttp
    $envLines = @("MSSQL_SA_PASSWORD=$SqlPassword", "DB_NAME=RTS_DB_DEMO", "HQ_DB_NAME=RTS_HQ")
    if ($BindAddress) { $envLines += "MIDDLEWARE_BIND_ADDRESS=$BindAddress" }
    Set-Content -Encoding ASCII (Join-Path $root ".env") $envLines

    $global:AuditDockerCalls = New-Object System.Collections.Generic.List[string]
    $global:AuditSqlEnv = New-Object System.Collections.Generic.List[string]
    $global:AuditHttpCalls = New-Object System.Collections.Generic.List[string]
    $global:AuditHttpReplies = $Replies
    $result = [pscustomobject]@{ Error = $null }
    # The script does Set-Location into $root; leave it again, or the folder cannot be removed.
    Push-Location
    try {
        & (Join-Path $demo "reset_demo_db.ps1") @ScriptArgs *> $null
    }
    catch {
        $result.Error = $_.Exception.Message
    }
    finally {
        Pop-Location
        Remove-Item -Recurse -Force $root
    }
    return $result
}

function global:docker {
    $global:AuditDockerCalls.Add(($args -join " "))
    if ($args -contains "exec") { $global:AuditSqlEnv.Add([string]$env:SQLCMDPASSWORD) }
    $global:LASTEXITCODE = 0
}
function global:Start-Sleep { }

$Healthy = @{ health = @(, @(200, '{"status":"ok"}')); job = @(, @(200, '{}')) }

Invoke-Case "test_audit10_api_host_comes_from_middleware_bind_address" {
    $run = Invoke-ResetFixture -BindAddress "192.168.50.10" -Replies $Healthy.Clone()
    Assert-That ($null -eq $run.Error) "script failed: $($run.Error)"
    $calls = @($global:AuditHttpCalls)
    Assert-That ($calls.Count -gt 0) "no HTTP call was made"
    foreach ($call in $calls) {
        Assert-That ($call -like "* https://192.168.50.10:8443/api/v1/*") "call not sent to the bind address: $call"
    }
}

Invoke-Case "test_audit10_api_host_falls_back_to_localhost" {
    foreach ($bind in @($null, "0.0.0.0")) {
        $run = Invoke-ResetFixture -BindAddress $bind -Replies $Healthy.Clone()
        Assert-That ($null -eq $run.Error) "script failed: $($run.Error)"
        foreach ($call in @($global:AuditHttpCalls)) {
            Assert-That ($call -like "* https://localhost:8443/api/v1/*") "bind '$bind' gave: $call"
        }
    }
}

Invoke-Case "test_audit10_waits_for_health_before_running_the_job" {
    $replies = @{ health = @(@(0, ""), @(0, ""), @(200, '{"status":"ok"}')); job = @(, @(200, '{}')) }
    $run = Invoke-ResetFixture -Replies $replies
    Assert-That ($null -eq $run.Error) "script failed: $($run.Error)"
    $calls = @($global:AuditHttpCalls)
    $health = @($calls | Where-Object { $_ -like "GET */health" })
    Assert-That ($health.Count -eq 3) "expected 3 health polls, got $($health.Count): $($calls -join '; ')"
    Assert-That ($calls[-1] -like "POST */admin/jobs/forecast/run") "forecast not called after health 200: $($calls -join '; ')"
}

Invoke-Case "test_audit10_health_timeout_gives_clear_error" {
    $replies = @{ health = @(, @(0, "")); job = @(, @(200, '{}')) }
    $run = Invoke-ResetFixture -Replies $replies -ScriptArgs @{ HealthTimeoutSeconds = 0 }
    Assert-That ($null -ne $run.Error) "script did not fail when the middleware never answered"
    Assert-That ($run.Error -like "*/api/v1/health*") "error does not name the health URL: $($run.Error)"
    Assert-That (@($global:AuditHttpCalls | Where-Object { $_ -like "POST *" }).Count -eq 0) "forecast called although unhealthy"
}

Invoke-Case "test_audit10_job_running_409_is_retried_not_thrown" {
    $busy = '{"outcome":"REJECTED","code":"JOB_RUNNING","message":"Job ''forecast'' is already running."}'
    $replies = @{ health = @(, @(200, '{"status":"ok"}')); job = @(@(409, $busy), @(409, $busy), @(200, '{}')) }
    $run = Invoke-ResetFixture -Replies $replies
    Assert-That ($null -eq $run.Error) "script failed: $($run.Error)"
    $posts = @($global:AuditHttpCalls | Where-Object { $_ -like "POST *" })
    Assert-That ($posts.Count -eq 3) "expected 3 forecast calls, got $($posts.Count)"
}

Invoke-Case "test_audit10_job_running_409_timeout_gives_clear_error" {
    $busy = '{"outcome":"REJECTED","code":"JOB_RUNNING","message":"Job ''forecast'' is already running."}'
    $replies = @{ health = @(, @(200, '{"status":"ok"}')); job = @(, @(409, $busy)) }
    $run = Invoke-ResetFixture -Replies $replies -ScriptArgs @{ JobTimeoutSeconds = 0 }
    Assert-That ($null -ne $run.Error) "script did not fail while the job kept answering 409"
    Assert-That ($run.Error -like "*still running after 0 seconds*JOB_RUNNING*") "unclear error: $($run.Error)"
}

Invoke-Case "test_audit10_other_409_code_is_not_retried" {
    # Only the code field counts: "JOB_RUNNING" in another field is not enough.
    $conflict = '{"outcome":"REJECTED","code":"CONFLICT","message":"Conflict.","previous":"JOB_RUNNING"}'
    $replies = @{ health = @(, @(200, '{"status":"ok"}')); job = @(@(409, $conflict), @(200, '{}')) }
    $run = Invoke-ResetFixture -Replies $replies
    Assert-That ($run.Error -like "*HTTP 409*") "a 409 CONFLICT was not reported: $($run.Error)"
    Assert-That (@($global:AuditHttpCalls | Where-Object { $_ -like "POST *" }).Count -eq 1) "a 409 CONFLICT was retried"
}

Invoke-Case "test_audit10_every_compose_run_has_no_deps" {
    $run = Invoke-ResetFixture -Replies $Healthy.Clone()
    Assert-That ($null -eq $run.Error) "script failed: $($run.Error)"
    $runs = @($global:AuditDockerCalls | Where-Object { $_ -like "compose run *" })
    Assert-That ($runs.Count -ge 4) "expected at least 4 compose run calls, got $($runs.Count)"
    foreach ($call in $runs) {
        Assert-That ($call -match '(^| )--no-deps( |$)') "compose run without --no-deps: $call"
    }
}

Invoke-Case "test_audit10_sql_password_not_on_docker_argv" {
    $run = Invoke-ResetFixture -Replies $Healthy.Clone()
    Assert-That ($null -eq $run.Error) "script failed: $($run.Error)"
    foreach ($call in @($global:AuditDockerCalls)) {
        Assert-That (-not $call.Contains($SqlPassword)) "password on argv: $($call.Replace($SqlPassword, '***'))"
    }
    Assert-That ($global:AuditSqlEnv.Count -gt 0) "no sqlcmd call recorded"
    foreach ($value in $global:AuditSqlEnv) {
        Assert-That ($value -eq $SqlPassword) "SQLCMDPASSWORD not set in the environment of docker compose exec"
    }
    Assert-That ([string]::IsNullOrEmpty($env:SQLCMDPASSWORD)) "SQLCMDPASSWORD left in the environment after the run"
}

Invoke-Case "test_pb52_reset_applies_demo_seed_and_uses_demo_profile" {
    $root = New-TempDir
    $demo = Join-Path $root "scripts\demo"
    $seedDemo = Join-Path $root "database\seed\demo"
    New-Item -ItemType Directory $demo, $seedDemo | Out-Null
    Copy-Item (Join-Path $DemoDir "reset_demo_db.ps1") $demo
    Copy-Item (Join-Path $DemoDir "_demo_http.ps1") $demo
    Add-Content -Encoding ASCII (Join-Path $demo "_demo_http.ps1") $FakeDemoHttp
    Set-Content -Encoding ASCII (Join-Path $seedDemo "001_demo_catalog_30.sql") "SELECT 1;"
    Set-Content -Encoding ASCII (Join-Path $root ".env") @("MSSQL_SA_PASSWORD=$SqlPassword", "DB_NAME=RTS_DB_DEMO", "HQ_DB_NAME=RTS_HQ")

    $global:AuditDockerCalls = New-Object System.Collections.Generic.List[string]
    $global:AuditSqlEnv = New-Object System.Collections.Generic.List[string]
    $global:AuditHttpCalls = New-Object System.Collections.Generic.List[string]
    $global:AuditHttpReplies = $Healthy.Clone()
    Push-Location
    try {
        & (Join-Path $demo "reset_demo_db.ps1") *> $null
        $seedCalls = @($global:AuditDockerCalls | Where-Object { $_ -like "*001_demo_catalog_30.sql*" })
        Assert-That ($seedCalls.Count -eq 1) "expected 1 demo seed call, got $($seedCalls.Count)"
        Assert-That ($seedCalls[0] -match '(^| )--no-deps( |$)') "demo seed call missing --no-deps: $($seedCalls[0])"
        Assert-That ($seedCalls[0] -like "*-f 65001*") "demo seed call missing UTF-8 flag -f 65001: $($seedCalls[0])"
        Assert-That (-not $seedCalls[0].Contains($SqlPassword)) "password leaked on demo seed argv"
        $histCalls = @($global:AuditDockerCalls | Where-Object { $_ -like "*history_generator*" })
        Assert-That ($histCalls.Count -eq 1) "expected 1 history_generator call, got $($histCalls.Count)"
        Assert-That ($histCalls[0] -like "*--demo-profile*") "history_generator missing --demo-profile: $($histCalls[0])"
    }
    finally {
        Pop-Location
        Remove-Item -Recurse -Force $root
    }
}

Remove-Item Function:\docker, Function:\Start-Sleep -ErrorAction SilentlyContinue

# --- export_terminal_tokens.ps1 fixture ------------------------------------

function ConvertTo-Base64Url {
    param([string]$Text)
    return [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($Text)).TrimEnd('=').Replace('+', '-').Replace('/', '_')
}

function New-ExportFixture {
    $root = New-TempDir
    $repo = Join-Path $root "repo"
    $demo = Join-Path $repo "scripts\demo"
    New-Item -ItemType Directory $demo, (Join-Path $root "work"), (Join-Path $root "secrets\pos") | Out-Null
    Copy-Item (Join-Path $DemoDir "export_terminal_tokens.ps1") $demo
    & git -C $repo init -q
    $header = ConvertTo-Base64Url '{"alg":"HS256","typ":"JWT"}'
    $tokens = [ordered]@{
        "POS-DN1-01" = "$header." + (ConvertTo-Base64Url '{"role":"POS","pos_id":"POS-DN1-01","store_id":"STORE-DN1"}') + ".sig"
        "staff_dn1"  = "$header." + (ConvertTo-Base64Url '{"role":"Staff","store_id":"STORE-DN1"}') + ".sig"
    }
    Set-Content -Encoding ASCII (Join-Path $root "secrets\tokens.json") ($tokens | ConvertTo-Json)
    foreach ($file in @("ca.crt", "pos\POS-DN1-01.crt", "pos\POS-DN1-01.key")) {
        Set-Content -Encoding ASCII (Join-Path $root "secrets\$file") "fake"
    }
    return $root
}

function Invoke-Export {
    param([string]$Root, [string]$Out, [string]$Cwd)
    Set-Location $Cwd
    $warnings = @()
    & (Join-Path $Root "repo\scripts\demo\export_terminal_tokens.ps1") -Terminal POS-DN1-01 -Staff staff_dn1 `
        -Out $Out -TokensPath (Join-Path $Root "secrets\tokens.json") -CertsPath (Join-Path $Root "secrets") `
        -WarningVariable +warnings -WarningAction SilentlyContinue *> $null
    return , $warnings
}

function Assert-Exported {
    param([string]$Folder)
    foreach ($file in @(".tokens\demo_tokens.json", ".certs\ca.crt", ".certs\pos\POS-DN1-01.crt", ".certs\pos\POS-DN1-01.key")) {
        Assert-That (Test-Path (Join-Path $Folder $file)) "missing $Folder\$file"
    }
}

Invoke-Case "test_audit11a_absolute_out_path_is_used_as_is" {
    $root = New-ExportFixture
    try {
        $target = Join-Path $root "abs\A"
        Invoke-Export -Root $root -Out $target -Cwd (Join-Path $root "work") | Out-Null
        Assert-Exported $target
    }
    finally { Set-Location $env:TEMP; Remove-Item -Recurse -Force $root -ErrorAction SilentlyContinue }
}

Invoke-Case "test_audit11a_relative_out_path_joins_current_folder" {
    $root = New-ExportFixture
    try {
        Invoke-Export -Root $root -Out "out\A" -Cwd (Join-Path $root "work") | Out-Null
        Assert-Exported (Join-Path $root "work\out\A")
    }
    finally { Set-Location $env:TEMP; Remove-Item -Recurse -Force $root -ErrorAction SilentlyContinue }
}

Invoke-Case "test_audit11a_sibling_folder_is_not_inside_repo" {
    $root = New-ExportFixture
    try {
        $warnings = Invoke-Export -Root $root -Out "..\repo-export" -Cwd (Join-Path $root "repo")
        Assert-Exported (Join-Path $root "repo-export")
        Assert-That ($warnings.Count -eq 0) "sibling folder treated as inside the repo: $($warnings -join '; ')"
    }
    finally { Set-Location $env:TEMP; Remove-Item -Recurse -Force $root -ErrorAction SilentlyContinue }
}

Invoke-Case "test_audit11a_folder_inside_repo_still_warns_when_not_ignored" {
    $root = New-ExportFixture
    try {
        $warnings = Invoke-Export -Root $root -Out "out\A" -Cwd (Join-Path $root "repo")
        Assert-Exported (Join-Path $root "repo\out\A")
        Assert-That ($warnings.Count -eq 1) "expected one 'not ignored by git' warning, got $($warnings.Count)"
    }
    finally { Set-Location $env:TEMP; Remove-Item -Recurse -Force $root -ErrorAction SilentlyContinue }
}

# --- PB-41-2: default base URL from .env MIDDLEWARE_BIND_ADDRESS ------------

# Appended after the real helpers, so the real .env reader runs and no request is sent.
$FakeApiCalls = @'

function Invoke-DemoApi {
    param([string]$Method, [string]$Url, [string]$TokenName, [string]$Body, [int]$TimeoutSeconds, [switch]$Quiet)
    $global:Pb41Urls.Add($Url)
    return [pscustomobject]@{ Status = 418; Body = "{}"; Error = "stub" }
}
function New-DemoCommonArgs { param([string]$TokensPath, [string]$CaPath) return @{} }
function Exit-Demo { param($Result) }
'@

$Pb41Scripts = [ordered]@{
    "audit_tail.ps1"    = @{}
    "sync_run.ps1"      = @{}
    "hq_snapshot.ps1"   = @{}
    "run_job.ps1"       = @{ Name = "forecast" }
    "set_threshold.ps1" = @{ Category = "Dairy"; Days = 7 }
    "cross_store.ps1"   = @{ Barcode = "8930000000011" }
}

# Runs the six scripts in a temporary repository whose .env holds $EnvLines (no .env when $null).
# Returns script name -> the URLs it called.
function Invoke-BaseUrlFixture {
    param([string[]]$EnvLines, [hashtable]$Extra = @{})
    $root = New-TempDir
    $demo = Join-Path $root "scripts\demo"
    New-Item -ItemType Directory $demo | Out-Null
    Copy-Item (Join-Path $DemoDir "_demo_http.ps1") $demo
    Add-Content -Encoding ASCII (Join-Path $demo "_demo_http.ps1") $FakeApiCalls
    if ($null -ne $EnvLines) { Set-Content -Encoding ASCII (Join-Path $root ".env") $EnvLines }
    $urls = @{}
    try {
        foreach ($name in $Pb41Scripts.Keys) {
            Copy-Item (Join-Path $DemoDir $name) $demo
            $global:Pb41Urls = New-Object System.Collections.Generic.List[string]
            $scriptArgs = $Pb41Scripts[$name] + $Extra
            & (Join-Path $demo $name) @scriptArgs *> $null
            $urls[$name] = @($global:Pb41Urls)
        }
    }
    finally {
        Remove-Item -Recurse -Force $root
    }
    return $urls
}

function Assert-AllCalled {
    param([hashtable]$Urls, [string]$Prefix, [string]$Case)
    foreach ($name in $Pb41Scripts.Keys) {
        $calls = @($Urls[$name])
        Assert-That ($calls.Count -eq 1) "${Case}: $name made $($calls.Count) calls"
        Assert-That ($calls[0].StartsWith("$Prefix/")) "${Case}: $name called $($calls[0]), expected $Prefix/..."
    }
}

Invoke-Case "test_pb41_2_unset_bind_address_defaults_to_localhost" {
    $cases = [ordered]@{
        "no .env"  = $null
        "no key"   = @("DB_NAME=RTS_DB_DEMO")
        "empty"    = @("MIDDLEWARE_BIND_ADDRESS=")
        "0.0.0.0"  = @("MIDDLEWARE_BIND_ADDRESS=0.0.0.0")
    }
    foreach ($case in $cases.Keys) {
        Assert-AllCalled (Invoke-BaseUrlFixture -EnvLines $cases[$case]) "https://localhost:8443/api/v1" $case
    }
}

Invoke-Case "test_pb41_2_localhost_bind_address_is_used" {
    Assert-AllCalled (Invoke-BaseUrlFixture -EnvLines @("MIDDLEWARE_BIND_ADDRESS=localhost")) "https://localhost:8443/api/v1" "localhost"
    Assert-AllCalled (Invoke-BaseUrlFixture -EnvLines @("MIDDLEWARE_BIND_ADDRESS=127.0.0.1")) "https://127.0.0.1:8443/api/v1" "127.0.0.1"
}

Invoke-Case "test_pb41_2_lan_bind_address_is_used" {
    $lines = @("DB_NAME=RTS_DB_DEMO", 'MIDDLEWARE_BIND_ADDRESS = "192.168.50.10"', "POS_BIND_ADDRESS=192.168.50.10")
    Assert-AllCalled (Invoke-BaseUrlFixture -EnvLines $lines) "https://192.168.50.10:8443/api/v1" "LAN IP"
}

Invoke-Case "test_pb41_2_inline_comment_after_bind_address_is_dropped" {
    # Sprint_3_Demo.md section 3 puts this line in .env on machine S.
    $lines = @("MIDDLEWARE_BIND_ADDRESS=192.168.1.10 # middleware 8443")
    Assert-AllCalled (Invoke-BaseUrlFixture -EnvLines $lines) "https://192.168.1.10:8443/api/v1" "inline comment"
}

Invoke-Case "test_pb41_2_later_empty_bind_address_falls_back_to_localhost" {
    $lines = @("MIDDLEWARE_BIND_ADDRESS=192.168.1.10", "MIDDLEWARE_BIND_ADDRESS=")
    Assert-AllCalled (Invoke-BaseUrlFixture -EnvLines $lines) "https://localhost:8443/api/v1" "later empty key"
}

# Get-EnvValue on its own: the real helper in a temporary repository with this .env.
function Get-EnvValueFixture {
    param([string[]]$EnvLines, [string]$Key)
    $root = New-TempDir
    try {
        $demo = Join-Path $root "scripts\demo"
        New-Item -ItemType Directory $demo | Out-Null
        Copy-Item (Join-Path $DemoDir "_demo_http.ps1") $demo
        Set-Content -Encoding ASCII (Join-Path $root ".env") $EnvLines
        return & { . (Join-Path $demo "_demo_http.ps1"); Get-EnvValue $Key }
    }
    finally {
        Remove-Item -Recurse -Force $root
    }
}

Invoke-Case "test_pb41_2_env_value_quotes_and_hash" {
    $cases = @(
        @{ Line = 'SECRET="Pass #1! # not a comment" # comment'; Want = 'Pass #1! # not a comment' },
        @{ Line = "SECRET='a#b' # comment"; Want = 'a#b' },
        @{ Line = 'SECRET=Pass#1!'; Want = 'Pass#1!' },
        @{ Line = 'SECRET=Pass#1! # rotated 25/11'; Want = 'Pass#1!' },
        @{ Line = 'SECRET = spaced value  '; Want = 'spaced value' }
    )
    foreach ($case in $cases) {
        $got = Get-EnvValueFixture -EnvLines @("OTHER=1", $case.Line) -Key "SECRET"
        Assert-That ($got -ceq $case.Want) "'$($case.Line)' gave '$got', expected '$($case.Want)'"
    }
}

Invoke-Case "test_pb41_2_explicit_base_url_wins" {
    $urls = Invoke-BaseUrlFixture -EnvLines @("MIDDLEWARE_BIND_ADDRESS=192.168.50.10") -Extra @{ BaseUrl = "https://10.0.0.7:8443/api/v1/" }
    Assert-AllCalled $urls "https://10.0.0.7:8443/api/v1" "explicit -BaseUrl"
}

# --- hq_snapshot.ps1 (minor) -----------------------------------------------

$FakeSnapshotHttp = @'
function New-DemoCommonArgs { param([string]$TokensPath, [string]$CaPath) return @{} }
function Get-DemoBaseUrl { return "https://localhost:8443/api/v1" }
function Get-DemoErrorCode { param([string]$Body) return "SNAPSHOT_REJECTED" }
function Exit-Demo { param($Result) }
function Invoke-DemoApi {
    param([string]$Method, [string]$Url, [string]$TokenName, [string]$Body)
    $global:AuditSnapshotBody = $Body
    return [pscustomobject]@{ Status = 422; Body = '{"code":"SNAPSHOT_REJECTED"}'; Error = "stub" }
}
'@

Invoke-Case "test_audit_minor_hq_snapshot_taken_at_is_iso_8601_in_any_culture" {
    $root = New-TempDir
    try {
        Copy-Item (Join-Path $DemoDir "hq_snapshot.ps1") $root
        Set-Content -Encoding ASCII (Join-Path $root "_demo_http.ps1") $FakeSnapshotHttp
        foreach ($culture in @("th-TH", "fi-FI")) {
            $global:AuditSnapshotBody = $null
            # One statement, so Windows PowerShell 5.1 keeps the culture while the script runs.
            & { [Threading.Thread]::CurrentThread.CurrentCulture = $culture; & (Join-Path $root "hq_snapshot.ps1") *> $null }
            $takenAt = ($global:AuditSnapshotBody | ConvertFrom-Json).taken_at
            $year = [DateTime]::UtcNow.Year
            Assert-That ($takenAt -match "^$year-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$") "culture $culture gave taken_at '$takenAt'"
        }
    }
    finally { Remove-Item -Recurse -Force $root -ErrorAction SilentlyContinue }
}

Write-Host ""
Write-Host "$script:Passes passed, $script:Failures failed"
if ($script:Failures -gt 0) { exit 1 }
exit 0
