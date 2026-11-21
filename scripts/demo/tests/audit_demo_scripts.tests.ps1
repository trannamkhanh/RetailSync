<#
.SYNOPSIS
    Regression tests for audit findings #10 and #11a (reset_demo_db.ps1 and
    export_terminal_tokens.ps1). Windows PowerShell 5.1, no Pester, no Docker.

.DESCRIPTION
    Each case copies the real script into a temporary folder laid out like the
    repository. reset_demo_db.ps1 runs against a stub `docker` function and a stub
    _demo_http.ps1 (no HTTP, no database); export_terminal_tokens.ps1 runs on fake
    tokens and certificate files. Exit code 0 when every case passes.

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
    Set-Content -Encoding ASCII (Join-Path $demo "_demo_http.ps1") $FakeDemoHttp
    $envLines = @("MSSQL_SA_PASSWORD=$SqlPassword", "DB_NAME=RTS_DB_DEMO", "HQ_DB_NAME=RTS_HQ")
    if ($BindAddress) { $envLines += "MIDDLEWARE_BIND_ADDRESS=$BindAddress" }
    Set-Content -Encoding ASCII (Join-Path $root ".env") $envLines

    $global:AuditDockerCalls = New-Object System.Collections.Generic.List[string]
    $global:AuditSqlEnv = New-Object System.Collections.Generic.List[string]
    $global:AuditHttpCalls = New-Object System.Collections.Generic.List[string]
    $global:AuditHttpReplies = $Replies
    $result = [pscustomobject]@{ Error = $null }
    try {
        & (Join-Path $demo "reset_demo_db.ps1") @ScriptArgs *> $null
    }
    catch {
        $result.Error = $_.Exception.Message
    }
    finally {
        Remove-Item -Recurse -Force $root -ErrorAction SilentlyContinue
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

Write-Host ""
Write-Host "$script:Passes passed, $script:Failures failed"
if ($script:Failures -gt 0) { exit 1 }
exit 0
