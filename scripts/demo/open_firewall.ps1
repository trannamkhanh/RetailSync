$ErrorActionPreference = 'Stop'
foreach ($port in @(8443, 9443)) {
    $name = "RetailSync Demo TCP $port"
    if (-not (Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName $name -Direction Inbound -Action Allow -Protocol TCP -LocalPort $port -Profile Private | Out-Null
    }
}
