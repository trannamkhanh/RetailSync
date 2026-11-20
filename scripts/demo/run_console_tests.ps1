# Run the demo console's xunit tests without `dotnet test`.
#
# Why this exists: on some hosts the VSTest testhost cannot open a handle to its
# parent process, so `dotnet test` aborts with
# "System.ComponentModel.Win32Exception (5): Access is denied" before running a
# single test. The xunit console runner executes the test assembly in its own
# process instead, so it does not need that handle.
#
# It needs three things the `dotnet test` flow does not set up for a manual run:
#   * a runtimeconfig that asks for Microsoft.WindowsDesktop.App (the tests use WinForms),
#   * the RID-specific Microsoft.Data.SqlClient.dll, because the copy at the output
#     root is a reference assembly and throws PlatformNotSupportedException,
#   * Microsoft.Data.SqlClient.SNI.dll, the native SNI layer.
#
# Usage, from the repository root:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/demo/run_console_tests.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/demo/run_console_tests.ps1 -Method "DemoConsole.Tests.DashboardTests.Parses_every_field_of_the_revenue_contract"
#
# The script exits 1 when a test fails, so it can gate a merge.

[CmdletBinding()]
param(
    [string]$Configuration = 'Debug',
    # An xunit console -method value: a full test name, or a prefix ending in '*' or
    # '!'. This is not the VSTest -Filter syntax ("FullyQualifiedName~...").
    [string]$Method = '',
    # Rebuild from scratch; use it when a source file's timestamp looks older than
    # the binaries and MSBuild would otherwise skip recompiling it.
    [switch]$Rebuild
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$solution = Join-Path $root 'clients/demo-console/DemoConsole.sln'
$testBin = Join-Path $root "clients/demo-console/DemoConsole.Tests/bin/$Configuration/net8.0-windows"
$runnerVersion = '2.9.2'
$runnerDir = Join-Path $env:TEMP "xunit.console.$runnerVersion"

# Always build: testing a stale DemoConsole.Tests.dll would report the previous
# source, which looks like a passing run of code nobody compiled.
#
# MSBuild decides by timestamp, so a file restored or checked out with an older mtime
# than the binary is silently left out. -Rebuild discards incremental state so the run
# can never test yesterday's source. It is the only build in that case: building twice
# would just compile the same sources again.
if ($Rebuild) {
    Write-Host "Rebuilding $solution without incremental state ..."
    dotnet build $solution --nologo --no-incremental | Out-Null
} else {
    Write-Host "Building $solution ..."
    dotnet build $solution --nologo | Out-Null
}
if ($LASTEXITCODE -ne 0) { throw 'dotnet build failed.' }

# Fetch the console runner once, into the temp folder rather than the repository.
# The check and the extraction must agree on the path, or every run re-downloads and
# an offline machine fails even though the runner is already cached.
$runnerSource = Join-Path $runnerDir 'pkg/tools/net6.0'
if (-not (Test-Path (Join-Path $runnerSource 'xunit.console.dll'))) {
    Write-Host "Downloading xunit.console $runnerVersion ..."
    New-Item -ItemType Directory -Force -Path $runnerDir | Out-Null
    $nupkg = Join-Path $runnerDir 'runner.nupkg'
    $url = "https://api.nuget.org/v3-flatcontainer/xunit.runner.console/$runnerVersion/xunit.runner.console.$runnerVersion.nupkg"
    Invoke-WebRequest -Uri $url -OutFile $nupkg -TimeoutSec 120
    # Expand-Archive only accepts .zip, and an .nupkg is one.
    Copy-Item $nupkg (Join-Path $runnerDir 'runner.zip') -Force
    Expand-Archive -Path (Join-Path $runnerDir 'runner.zip') -DestinationPath (Join-Path $runnerDir 'pkg') -Force
}

Copy-Item (Join-Path $runnerSource '*') $testBin -Force

# The runner targets net6.0; ask for the desktop framework the tests actually need.
$runtimeConfig = @'
{
  "runtimeOptions": {
    "tfm": "net8.0-windows",
    "rollForward": "Major",
    "framework": {
      "name": "Microsoft.WindowsDesktop.App",
      "version": "8.0.0"
    },
    "configProperties": {
      "System.Reflection.Metadata.MetadataUpdater.IsSupported": false
    }
  }
}
'@
Set-Content -Path (Join-Path $testBin 'xunit.console.runtimeconfig.json') -Value $runtimeConfig -Encoding UTF8

# Use the real SqlClient build and its native SNI, not the reference assembly.
$winLib = Join-Path $testBin 'runtimes/win/lib/net8.0'
if (Test-Path $winLib) {
    Copy-Item (Join-Path $winLib '*.dll') $testBin -Force
}
$winNative = Join-Path $testBin 'runtimes/win-x64/native'
if (Test-Path $winNative) {
    Copy-Item (Join-Path $winNative 'Microsoft.Data.SqlClient.SNI.dll') $testBin -Force
}

$arguments = @(
    (Join-Path $testBin 'xunit.console.dll'),
    (Join-Path $testBin 'DemoConsole.Tests.dll'),
    '-nologo',
    '-parallel', 'none'
)
if ($Method) { $arguments += @('-method', $Method) }

Push-Location $testBin
try {
    dotnet @arguments
    exit $LASTEXITCODE
}
finally {
    Pop-Location
    # Leave the build output as the build produced it.
    Get-ChildItem $testBin -Filter 'xunit.console*' | Remove-Item -Force -ErrorAction SilentlyContinue
}
