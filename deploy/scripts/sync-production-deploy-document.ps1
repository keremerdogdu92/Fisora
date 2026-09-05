# File: deploy/scripts/sync-production-deploy-document.ps1
# Summary: Creates or updates the restricted Fisora production SSM deploy document from the repository source of truth.

[CmdletBinding()]
param(
    [string]$Region = "eu-central-1",
    [string]$DocumentName = "FisoraProductionDeploy",
    [switch]$PlanOnly
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$DocumentPath = Join-Path $RepoRoot "deploy\aws\fisora-production-deploy-document.json"

if (-not (Test-Path -LiteralPath $DocumentPath -PathType Leaf)) {
    throw "SSM document source is missing: $DocumentPath"
}

$DocumentUri = "file://" + ($DocumentPath -replace "\\", "/")
if ($PlanOnly) {
    [pscustomobject]@{
        region = $Region
        document_name = $DocumentName
        source = $DocumentPath
        action = "create-or-update-and-promote-default"
    } | ConvertTo-Json -Compress
    exit 0
}
$identity = & aws sts get-caller-identity --region $Region --output json 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "AWS authentication is required before syncing the production deploy document.`n$($identity -join "`n")"
}

$describe = & aws ssm describe-document --region $Region --name $DocumentName --output json 2>&1
$describeExit = $LASTEXITCODE
$describeText = $describe -join "`n"

if ($describeExit -eq 0) {
    $update = & aws ssm update-document `
        --region $Region `
        --name $DocumentName `
        --content $DocumentUri `
        --document-format JSON `
        --document-version '$LATEST' `
        --output json 2>&1
    $updateExit = $LASTEXITCODE
    $updateText = $update -join "`n"

    if ($updateExit -ne 0 -and $updateText -match "DuplicateDocumentContent") {
        Write-Output "SSM deploy document is already current."
        exit 0
    }
    if ($updateExit -ne 0) {
        throw "Failed to update SSM deploy document.`n$updateText"
    }
    $payload = $updateText | ConvertFrom-Json
    $version = [string]$payload.DocumentDescription.DocumentVersion
    & aws ssm update-document-default-version `
        --region $Region `
        --name $DocumentName `
        --document-version $version `
        --output json | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Updated SSM document version $version but failed to promote it as default."
    }
    Write-Output "Updated $DocumentName to document version $version and promoted it as default."
    exit 0
}

if ($describeText -notmatch "InvalidDocument") {
    throw "Unable to inspect existing SSM deploy document.`n$describeText"
}

$created = & aws ssm create-document `
    --region $Region `
    --name $DocumentName `
    --document-type Command `
    --document-format JSON `
    --content $DocumentUri `
    --output json 2>&1
if ($LASTEXITCODE -ne 0) {
    throw "Failed to create SSM deploy document.`n$($created -join "`n")"
}
Write-Output "Created $DocumentName from $DocumentPath."
