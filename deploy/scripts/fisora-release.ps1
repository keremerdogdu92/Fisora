# File: deploy/scripts/fisora-release.ps1
# Summary: Provides an incident-only direct SSH release path; routine production deploys must use GitHub Actions and the restricted SSM document.

param(
    [string]$Server = $env:FISORA_RELEASE_SERVER,
    [string]$SshKey = $env:FISORA_RELEASE_SSH_KEY,
    [string]$RemotePath = "/opt/fisora/app",
    [string]$Branch = "main",
    [string]$BaseUrl = "http://127.0.0.1",
    [switch]$SkipLocalVerify,
    [switch]$SkipSmoke,
    [switch]$AllowDirty,
    [switch]$NoSudo,
    [switch]$EmergencyOverride,
    [switch]$PlanOnly,
    [switch]$Json
)

$ErrorActionPreference = "Stop"

if (-not $Server) {
    $Server = "codex@185.184.208.188"
}
if (-not $SshKey) {
    $defaultKey = Join-Path $HOME ".ssh\fisero_server_ed25519"
    if (Test-Path -LiteralPath $defaultKey) {
        $SshKey = $defaultKey
    }
}

function Invoke-Step {
    param(
        [string]$Name,
        [scriptblock]$Script
    )
    $started = Get-Date
    try {
        & $Script
        return [ordered]@{
            name = $Name
            status = "ok"
            seconds = [math]::Round(((Get-Date) - $started).TotalSeconds, 2)
        }
    } catch {
        return [ordered]@{
            name = $Name
            status = "failed"
            seconds = [math]::Round(((Get-Date) - $started).TotalSeconds, 2)
            error = $_.Exception.Message
        }
    }
}

function Invoke-CommandLine {
    param([string]$Command)
    Write-Host ">> $Command"
    & powershell -NoProfile -ExecutionPolicy Bypass -Command $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Command failed with exit code $LASTEXITCODE"
    }
}

function Invoke-Git {
    param([string[]]$GitArgs)
    $output = & git @GitArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw (($output | Out-String).Trim())
    }
    return $output
}

function Assert-OriginParity {
    param([string]$Branch)

    Invoke-Git -GitArgs @("fetch", "--quiet", "origin", $Branch) | Out-Null
    $counts = ((Invoke-Git -GitArgs @("rev-list", "--left-right", "--count", "HEAD...origin/$Branch")) | Select-Object -First 1).Trim()
    $parts = $counts -split "\s+"
    $ahead = [int]$parts[0]
    $behind = [int]$parts[1]
    if ($ahead -gt 0) {
        throw "Local branch origin/$Branch'den ahead; once publish calistir."
    }
    if ($behind -gt 0) {
        throw "Local branch origin/$Branch'den behind; once local branch'i guncelle."
    }
}

function New-RemoteScript {
    param(
        [string]$RemotePath,
        [string]$Branch,
        [string]$BaseUrl,
        [bool]$SkipSmoke
    )

    $smokeBlock = if ($SkipSmoke) {
        'smoke_status=skipped'
    } else {
        'if sh deploy/scripts/fisora-prod.sh smoke; then smoke_status=ok; else smoke_status=failed; fi'
    }

    return @"
set -eu
exec 2>&1
cd '$RemotePath'
before_commit=`$(git rev-parse --short HEAD 2>/dev/null || echo unknown)
git fetch origin
git checkout $Branch
git pull --ff-only origin $Branch
after_commit=`$(git rev-parse --short HEAD)
sh deploy/scripts/fisora-prod.sh check
sh deploy/scripts/fisora-prod.sh deploy
$smokeBlock
health_status=`$(curl -fsSL -k -o /tmp/fisora-release-health.json -w '%{http_code}' '$BaseUrl/health' || true)
readiness_status=`$(curl -fsSL -k -o /tmp/fisora-release-readiness.json -w '%{http_code}' '$BaseUrl/api/phase0/store/system/readiness' || true)
route_status=`$(curl -fsSL -k -o /tmp/fisora-release-root.html -w '%{http_code}' '$BaseUrl/' || true)
ready=false
pilot_sellable=false
if command -v python3 >/dev/null 2>&1 && [ -s /tmp/fisora-release-readiness.json ]; then
  ready=`$(python3 - <<'PY'
import json
from pathlib import Path
try:
    data = json.loads(Path('/tmp/fisora-release-readiness.json').read_text())
    print(str(bool(data.get('ready'))).lower())
except Exception:
    print("false")
PY
)
  pilot_sellable=`$(python3 - <<'PY'
import json
from pathlib import Path
try:
    data = json.loads(Path('/tmp/fisora-release-readiness.json').read_text())
    print(str(bool(data.get('pilot_sellable'))).lower())
except Exception:
    print("false")
PY
)
fi
printf 'FISORA_RELEASE_SUMMARY {"before_commit":"%s","after_commit":"%s","smoke":"%s","health_status":"%s","readiness_status":"%s","route_status":"%s","ready":%s,"pilot_sellable":%s}\n' "`$before_commit" "`$after_commit" "`$smoke_status" "`$health_status" "`$readiness_status" "`$route_status" "`$ready" "`$pilot_sellable"
"@
}

$remoteScript = New-RemoteScript -RemotePath $RemotePath -Branch $Branch -BaseUrl $BaseUrl -SkipSmoke ([bool]$SkipSmoke)

if ($PlanOnly) {
    $payload = [ordered]@{
        mode = "plan"
        server = $Server
        remote_path = $RemotePath
        branch = $Branch
        base_url = $BaseUrl
        local_verify_enabled = -not [bool]$SkipLocalVerify
        smoke_enabled = -not [bool]$SkipSmoke
        sudo_enabled = -not [bool]$NoSudo
        ssh_key_configured = [bool]$SshKey
        emergency_override_required = $true
        remote_script = $remoteScript
    }
    if ($Json) {
        $payload | ConvertTo-Json -Depth 5
    } else {
        $payload
    }
    exit 0
}

if (-not $EmergencyOverride) {
    throw "Direct SSH production releases are disabled for routine operations. Use the GitHub Actions 'Deploy Production' workflow. Use -EmergencyOverride only for an authorized incident response."
}

$summary = [ordered]@{
    mode = "release"
    server = $Server
    remote_path = $RemotePath
    branch = $Branch
    base_url = $BaseUrl
    started_at = (Get-Date).ToString("o")
    sudo_enabled = -not [bool]$NoSudo
    ssh_key_configured = [bool]$SshKey
    steps = @()
}

$summary.steps += Invoke-Step -Name "local-git-status" -Script {
    $dirty = git status --porcelain -uno
    if ($dirty -and -not $AllowDirty) {
        throw "Local worktree has uncommitted tracked changes. Commit/stash or rerun with -AllowDirty."
    }
}
if ($summary.steps[-1].status -ne "ok") { throw ($summary.steps[-1].error) }

$summary.steps += Invoke-Step -Name "origin-parity" -Script {
    Assert-OriginParity -Branch $Branch
}
if ($summary.steps[-1].status -ne "ok") { throw ($summary.steps[-1].error) }

if (-not $SkipLocalVerify) {
    $summary.steps += Invoke-Step -Name "local-diff-check" -Script { Invoke-CommandLine "git diff --check" }
    if ($summary.steps[-1].status -ne "ok") { throw ($summary.steps[-1].error) }

    $summary.steps += Invoke-Step -Name "backend-tests" -Script { Invoke-CommandLine "python -m unittest discover -s backend/tests" }
    if ($summary.steps[-1].status -ne "ok") { throw ($summary.steps[-1].error) }

    $summary.steps += Invoke-Step -Name "frontend-tests" -Script { Invoke-CommandLine "node --test frontend/app/*.test.cjs" }
    if ($summary.steps[-1].status -ne "ok") { throw ($summary.steps[-1].error) }

    $summary.steps += Invoke-Step -Name "frontend-build" -Script { Invoke-CommandLine "cd frontend; npm.cmd run build" }
    if ($summary.steps[-1].status -ne "ok") { throw ($summary.steps[-1].error) }
}

$tempScript = New-TemporaryFile
try {
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($tempScript.FullName, $remoteScript, $utf8NoBom)
    $summary.steps += Invoke-Step -Name "server-release" -Script {
        $remoteShell = if ($NoSudo) { "sed -e '1s/^\xef\xbb\xbf//' | tr -d '\r' | sh -s" } else { "sed -e '1s/^\xef\xbb\xbf//' | tr -d '\r' | sudo -n sh -s" }
        $sshArgs = @()
        if ($SshKey) {
            $sshArgs += @("-i", $SshKey)
        }
        $sshArgs += @($Server, $remoteShell)
        $releaseOutput = Get-Content -LiteralPath $tempScript | ssh @sshArgs
        $summaryLine = @($releaseOutput | Where-Object { $_ -like "FISORA_RELEASE_SUMMARY *" } | Select-Object -Last 1)
        if ($summaryLine.Count) {
            $summary.remote_summary = ($summaryLine[-1] -replace "^FISORA_RELEASE_SUMMARY ", "") | ConvertFrom-Json
        }
        if ($LASTEXITCODE -ne 0) {
            $tail = @($releaseOutput | Select-Object -Last 20) -join "`n"
            throw "ssh release failed with exit code $LASTEXITCODE`n$tail"
        }
    }
    if ($summary.steps[-1].status -ne "ok") { throw ($summary.steps[-1].error) }
} finally {
    Remove-Item -LiteralPath $tempScript -Force -ErrorAction SilentlyContinue
}

$summary.finished_at = (Get-Date).ToString("o")
if ($Json) {
    $summary | ConvertTo-Json -Depth 6
} else {
    $summary
}
