param(
    [string]$BaseUrl = "http://localhost:8088",
    [string]$ClientId = "",
    [string]$UserId = "mali-musavir",
    [switch]$RequireRealDataPilot
)

$ErrorActionPreference = "Stop"

function Invoke-FisoraGet {
    param(
        [string]$Path,
        [hashtable]$Headers = @{}
    )
    $uri = "$BaseUrl$Path"
    Invoke-RestMethod -Uri $uri -Method Get -Headers $Headers
}

$health = Invoke-FisoraGet -Path "/health"
$summary = Invoke-FisoraGet -Path "/api/phase0/summary"
$readiness = Invoke-FisoraGet -Path "/api/phase0/store/system/readiness"

Write-Host "health:" ($health | ConvertTo-Json -Compress)
Write-Host "phase0:" ($summary | ConvertTo-Json -Compress)
Write-Host "readiness:" ($readiness | ConvertTo-Json -Compress)

if ($readiness.real_data_pilot) {
    Write-Host "real-data-pilot:" ($readiness.real_data_pilot | ConvertTo-Json -Compress -Depth 6)
}

if ($RequireRealDataPilot -and -not [bool]$readiness.real_data_pilot.allowed) {
    $blocking = @($readiness.real_data_pilot.blocking) -join ","
    throw "Real data pilot gate is not open. blocking=$blocking"
}

if ($ClientId) {
    $headers = @{ "X-Fisora-User-Id" = $UserId }
    $operation = Invoke-FisoraGet -Path "/api/phase0/store/operation-health/$ClientId" -Headers $headers
    Write-Host "operation-health:" ($operation | ConvertTo-Json -Compress -Depth 6)
}
