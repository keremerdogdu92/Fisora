param(
    [string]$BaseUrl = "http://localhost:8088",
    [string]$ClientId = "",
    [string]$UserId = "mali-musavir"
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

if ($ClientId) {
    $headers = @{ "X-Fisora-User-Id" = $UserId }
    $operation = Invoke-FisoraGet -Path "/api/phase0/store/operation-health/$ClientId" -Headers $headers
    Write-Host "operation-health:" ($operation | ConvertTo-Json -Compress -Depth 6)
}
