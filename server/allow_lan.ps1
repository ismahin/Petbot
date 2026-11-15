# Run once in an Administrator PowerShell. Only peers on the local subnet are allowed.
$ErrorActionPreference = 'Stop'
$aibiIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
$aibiPrincipal = [Security.Principal.WindowsPrincipal]::new($aibiIdentity)
if (-not $aibiPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Windows requires Administrator permission to add the two LAN firewall rules.'
}
foreach ($aibiRule in @(@('Deskter HTTPS LAN','TCP',8443),@('Deskter clock LAN','UDP',8123))) {
    if (-not (Get-NetFirewallRule -DisplayName $aibiRule[0] -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName $aibiRule[0] -Direction Inbound -Action Allow -Protocol $aibiRule[1] -LocalPort $aibiRule[2] -RemoteAddress LocalSubnet -Profile Any | Out-Null
    }
}
'Deskter LAN rules ready: TCP 8443 and UDP 8123, local subnet only.'
