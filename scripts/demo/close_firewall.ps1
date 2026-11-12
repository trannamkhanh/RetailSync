$ErrorActionPreference = 'Stop'
foreach ($port in @(8443, 9443)) {
    Get-NetFirewallRule -DisplayName "RetailSync Demo TCP $port" -ErrorAction SilentlyContinue | Remove-NetFirewallRule
}
