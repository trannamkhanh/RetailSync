<#
.SYNOPSIS
    Export what one demo machine needs: one terminal token, one Staff token, the CA,
    and that terminal's certificate and key (PB-42-7).

.DESCRIPTION
    Writes into -Out the same layout as the repository, so the folder's content can
    be copied onto the root of a clone on machine A or B:

        <Out>/.tokens/demo_tokens.json      only the -Terminal and -Staff tokens
        <Out>/.certs/ca.crt
        <Out>/.certs/pos/<Terminal>.crt
        <Out>/.certs/pos/<Terminal>.key

    It refuses the admin, auditor and hq_operator tokens and any name that is not
    a Staff or Manager account, refuses a Staff token of another store than the
    terminal's, and never prints a token. Run it on machine S after
    scripts/demo/reset_demo_db.ps1, which issues the tokens. Delete the folder once
    it is copied: it holds a private key.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/demo/export_terminal_tokens.ps1 -Terminal POS-DN1-01 -Staff staff_dn1 -Out .\out\A
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidatePattern('^POS-[A-Za-z0-9-]{1,30}$')][string]$Terminal,
    [Parameter(Mandatory)][string]$Staff,
    [Parameter(Mandatory)][string]$Out,
    [string]$TokensPath,
    [string]$CertsPath
)
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
if (-not $TokensPath) { $TokensPath = Join-Path $RepoRoot ".tokens\demo_tokens.json" }
if (-not $CertsPath) { $CertsPath = Join-Path $RepoRoot ".certs" }

$Forbidden = @("admin", "auditor", "hq_operator")
if ($Forbidden -contains $Staff.ToLowerInvariant()) {
    throw "Refusing to export '$Staff': only a terminal token and a Staff token of its store may leave machine S."
}
if ($Staff -notmatch '^(staff|manager)_[A-Za-z0-9]{1,20}$') {
    throw "'$Staff' is not a Staff or Manager account name, for example staff_dn1."
}

if (-not (Test-Path $TokensPath)) {
    throw "Missing $TokensPath. Run scripts/demo/reset_demo_db.ps1 first."
}
$tokens = Get-Content -Raw -Encoding UTF8 $TokensPath | ConvertFrom-Json

function Get-Claims {
    param([string]$Name)
    $value = $tokens.$Name
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "$TokensPath has no token named '$Name'."
    }
    $parts = $value.Split('.')
    if ($parts.Count -ne 3) { throw "Token '$Name' is not a JWT." }
    $payload = $parts[1].Replace('-', '+').Replace('_', '/')
    switch ($payload.Length % 4) { 2 { $payload += "==" } 3 { $payload += "=" } }
    $json = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($payload))
    return [pscustomobject]@{ Value = $value; Claims = ($json | ConvertFrom-Json) }
}

$terminalToken = Get-Claims $Terminal
$staffToken = Get-Claims $Staff
if ($terminalToken.Claims.role -ne "POS" -or $terminalToken.Claims.pos_id -ne $Terminal) {
    throw "Token '$Terminal' is not the POS token of terminal $Terminal."
}
if ($staffToken.Claims.role -notin @("Staff", "Manager")) {
    throw "Token '$Staff' has role '$($staffToken.Claims.role)', not Staff or Manager."
}
if ($staffToken.Claims.store_id -ne $terminalToken.Claims.store_id) {
    throw "'$Staff' belongs to $($staffToken.Claims.store_id), terminal $Terminal to $($terminalToken.Claims.store_id). Use the Staff account of the terminal's store."
}

$sources = @{
    "ca.crt"            = Join-Path $CertsPath "ca.crt"
    "pos\$Terminal.crt" = Join-Path $CertsPath "pos\$Terminal.crt"
    "pos\$Terminal.key" = Join-Path $CertsPath "pos\$Terminal.key"
}
foreach ($source in $sources.Values) {
    if (-not (Test-Path $source)) { throw "Missing $source. Run scripts/generate_dev_certs.sh on machine S." }
}

$outRoot = [IO.Path]::GetFullPath((Join-Path (Get-Location) $Out))
$outTokens = Join-Path $outRoot ".tokens"
$outCerts = Join-Path $outRoot ".certs"
New-Item -ItemType Directory -Force (Join-Path $outCerts "pos"), $outTokens | Out-Null

foreach ($name in $sources.Keys) {
    Copy-Item -Force $sources[$name] (Join-Path $outCerts $name)
}

$export = [ordered]@{}
$export[$Staff] = $staffToken.Value
$export[$Terminal] = $terminalToken.Value
$tokenFile = Join-Path $outTokens "demo_tokens.json"
# UTF-8 without a byte order mark, like scripts/issue_demo_tokens.py writes it.
[IO.File]::WriteAllText($tokenFile, ($export | ConvertTo-Json) + "`n", (New-Object Text.UTF8Encoding $false))

Write-Host "Exported for $Terminal ($($terminalToken.Claims.store_id)) into $outRoot :"
Write-Host "  .tokens/demo_tokens.json   tokens: $Terminal, $Staff"
Write-Host "  .certs/ca.crt"
Write-Host "  .certs/pos/$Terminal.crt"
Write-Host "  .certs/pos/$Terminal.key"
Write-Host "Copy the content of this folder onto the root of the clone on the demo machine, then delete it here."

# The folder may sit inside the repository: check git ignores everything in it.
Push-Location $RepoRoot
try {
    $relative = @(Get-ChildItem -Recurse -File -Force $outRoot | ForEach-Object { $_.FullName })
    $tracked = @()
    foreach ($file in $relative) {
        if ($file.StartsWith($RepoRoot, [StringComparison]::OrdinalIgnoreCase)) {
            & git check-ignore -q -- $file 2>$null
            if ($LASTEXITCODE -ne 0) { $tracked += $file }
        }
    }
    if ($tracked.Count -gt 0) {
        Write-Warning ("Not ignored by git, do not commit: " + ($tracked -join ", "))
    }
}
finally {
    Pop-Location
}
