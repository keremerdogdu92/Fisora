param(
    [string]$Remote = "origin",
    [string]$Branch = "main",
    [switch]$Json,
    [switch]$PlanOnly,
    [switch]$AllowDirty,
    [switch]$Quiet
)

$ErrorActionPreference = "Stop"

$quietEnabled = $true
if ($PSBoundParameters.ContainsKey("Quiet")) {
    $quietEnabled = [bool]$Quiet
}

function Invoke-Git {
    param([string[]]$GitArgs)
    $output = & git @GitArgs 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw (($output | Out-String).Trim())
    }
    return $output
}

function Get-Rev {
    param([string]$Ref)
    return ((Invoke-Git -GitArgs @("rev-parse", "--short", $Ref)) | Select-Object -First 1).Trim()
}

function Get-AheadBehind {
    param(
        [string]$Left,
        [string]$Right
    )
    $counts = ((Invoke-Git -GitArgs @("rev-list", "--left-right", "--count", "$Left...$Right")) | Select-Object -First 1).Trim()
    $parts = $counts -split "\s+"
    return [ordered]@{
        ahead = [int]$parts[0]
        behind = [int]$parts[1]
    }
}

$pushCommand = "git push"
if ($quietEnabled) {
    $pushCommand += " --quiet"
}
$pushCommand += " $Remote HEAD:$Branch"

if ($PlanOnly) {
    $payload = [ordered]@{
        mode = "plan"
        remote = $Remote
        branch = $Branch
        quiet = $quietEnabled
        allow_dirty = [bool]$AllowDirty
        push_command = $pushCommand
    }
    if ($Json) {
        $payload | ConvertTo-Json -Depth 4
    } else {
        $payload
    }
    exit 0
}

$dirty = Invoke-Git -GitArgs @("status", "--porcelain")
if ($dirty -and -not $AllowDirty) {
    throw "Local worktree has uncommitted changes. Commit/stash or rerun with -AllowDirty."
}

$currentBranch = ((Invoke-Git -GitArgs @("branch", "--show-current")) | Select-Object -First 1).Trim()
if ($currentBranch -ne $Branch) {
    throw "Current branch is '$currentBranch', expected '$Branch'. Refusing to publish HEAD to $Remote/$Branch."
}

Invoke-Git -GitArgs @("fetch", "--quiet", $Remote, $Branch) | Out-Null

$remoteRef = "$Remote/$Branch"
$localCommit = Get-Rev "HEAD"
$beforeRemoteCommit = Get-Rev $remoteRef
$counts = Get-AheadBehind "HEAD" $remoteRef

if ($counts.ahead -gt 0 -and $counts.behind -gt 0) {
    throw "Local branch has diverged from $remoteRef. Resolve the divergence before publishing."
}
if ($counts.behind -gt 0) {
    throw "Local branch is behind $remoteRef by $($counts.behind) commit(s). Pull/rebase before publishing."
}

$pushed = $false
$skipped = $false
if ($counts.ahead -eq 0) {
    $skipped = $true
} else {
    $pushArgs = @("push")
    if ($quietEnabled) {
        $pushArgs += "--quiet"
    }
    $pushArgs += @($Remote, "HEAD:$Branch")
    Invoke-Git -GitArgs $pushArgs | Out-Null
    $pushed = $true
    Invoke-Git -GitArgs @("fetch", "--quiet", $Remote, $Branch) | Out-Null
}

$afterRemoteCommit = Get-Rev $remoteRef
$summary = [ordered]@{
    mode = "publish"
    remote = $Remote
    branch = $Branch
    local_commit = $localCommit
    before_remote_commit = $beforeRemoteCommit
    after_remote_commit = $afterRemoteCommit
    ahead = $counts.ahead
    behind = $counts.behind
    pushed = $pushed
    skipped = $skipped
    quiet = $quietEnabled
}

if ($Json) {
    $summary | ConvertTo-Json -Depth 4
} else {
    $summary
}
