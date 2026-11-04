# MEG-181: exact-state checks allow resuming after k without replaying an UPDATE.
# This script can write to the selected DB when run by a person. Review before running.
param(
    [Parameter(Mandatory)][string]$SplitDir,
    [string]$AuditBackend = (Split-Path $PSScriptRoot -Parent),
    [Parameter(Mandatory)][ValidateRange(1,2147483647)][int]$PilotNoteId,
    [Parameter(Mandatory)][int[]]$RestNoteIds,
    [Parameter(Mandatory)][ValidateRange(1,2147483647)][int]$ExpectedMarkedBlocks,
    [Parameter(Mandatory)][uri]$NoteUrl,
    [switch]$NoPause,
    [switch]$SkipAudit
)
$ErrorActionPreference = 'Stop'
if ($RestNoteIds.Count -eq 0 -or @($RestNoteIds | Where-Object { $_ -lt 1 -or $_ -eq $PilotNoteId }).Count -gt 0 -or
    @($RestNoteIds | Select-Object -Unique).Count -ne $RestNoteIds.Count) { throw '대상 ID 목록이 올바르지 않습니다.' }
$RestNoteIds = @($RestNoteIds | Sort-Object)
$SplitDir = (Resolve-Path -LiteralPath $SplitDir).Path
foreach ($file in @('state-pilot.sql','state-rest.sql','1-pilot-apply.sql','1-pilot-restore.sql','2-rest-apply.sql')) {
    if (-not (Test-Path -LiteralPath (Join-Path $SplitDir $file) -PathType Leaf)) { throw "준비 파일이 없습니다: $file" }
}
if (-not $env:DATABASE_URL) { $env:DATABASE_URL = Read-Host 'PRD 연결 문자열(Session pooler)' -MaskInput }
$env:DATABASE_URL = $env:DATABASE_URL.Trim()

function Invoke-Sql([string]$File) {
    $cmd = 'psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -q -At -F "," -f /sql/' + $File
    $out = docker run --rm -e DATABASE_URL -v "${SplitDir}:/sql:ro" postgres:17 sh -c $cmd 2>&1
    if ($LASTEXITCODE -ne 0) { throw "SQL 실행 실패: $File. 적용 상태를 읽기 전용으로 확인하세요." }
    return (($out -join "`n").Trim())
}
function Confirm-Step([string]$Question) {
    if ($NoPause) { return $true }
    return ((Read-Host "$Question (y/N)") -eq 'y')
}
function Get-GroupState([string]$Group) {
    $expectedIds = if ($Group -eq 'pilot') { @($PilotNoteId) } else { $RestNoteIds }
    $rows = (Invoke-Sql "state-$Group.sql") -split '\r?\n'
    $ids = @(); $states = @()
    foreach ($row in $rows) {
        if ($row -notmatch '^(\d+),(original|applied)$') { throw "$Group 본문이 백업/적용본과 다르거나 누락됐습니다. 변경 없이 중단합니다." }
        $ids += [int]$Matches[1]; $states += $Matches[2]
    }
    if (($ids -join ',') -ne ($expectedIds -join ',')) { throw "$Group 대상 목록이 일치하지 않습니다." }
    $unique = @($states | Select-Object -Unique)
    if ($unique.Count -ne 1) { throw "$Group 일부만 적용되어 있습니다. 변경 없이 중단합니다." }
    return $unique[0]
}
function Expect-State([string]$Group, [string]$Expected) {
    if ((Get-GroupState $Group) -ne $Expected) { throw "$Group 확인 실패: $Expected 상태가 아닙니다." }
}

Write-Host '[1/4] 현재 본문을 원본·적용본과 대조'
$pilot = Get-GroupState 'pilot'
$rest = Get-GroupState 'rest'
if ($pilot -eq 'original' -and $rest -eq 'applied') { throw '나머지만 적용된 상태입니다. 자동 적용 없이 중단합니다.' }
if ($pilot -eq 'original') {
    if (-not (Confirm-Step '파일럿 노트에 mermaid 표시를 적용할까요?')) { return }
    Invoke-Sql '1-pilot-apply.sql' | Out-Null
} else { Write-Host '파일럿 노트는 적용본과 정확히 일치합니다. UPDATE 없이 화면 확인부터 재개합니다.' }
Expect-State 'pilot' 'applied'

Write-Host '[2/4] 화면 확인'
Write-Host "운영자로 $NoteUrl 에 접속해 강력 새로고침(Ctrl+Shift+R)하세요."
if ($NoPause) { $answer = 'y' }
else { $answer = Read-Host 'y=그림 확인 / n=파일럿 노트 복구 / k=적용 상태로 중단' }
if ($answer -eq 'n') {
    # Do not restore the pilot alone after the second group has already committed.
    Expect-State 'rest' 'original'
    Invoke-Sql '1-pilot-restore.sql' | Out-Null
    Expect-State 'pilot' 'original'
    Write-Host '파일럿 노트 복구 및 본문 일치 확인 완료.'
    return
}
if ($answer -ne 'y') {
    Write-Host '추가 DB 변경 없이 멈춥니다. 재실행하면 현재 본문을 확인하고 화면 확인부터 재개합니다.'
    return
}

Write-Host '[3/4] 나머지 노트'
Expect-State 'pilot' 'applied'
$rest = Get-GroupState 'rest'
if ($rest -eq 'original') {
    if (-not (Confirm-Step '나머지 노트에도 적용할까요?')) { return }
    Invoke-Sql '2-rest-apply.sql' | Out-Null
} else { Write-Host '나머지도 적용본과 정확히 일치합니다. UPDATE를 건너뜁니다.' }
Expect-State 'pilot' 'applied'
Expect-State 'rest' 'applied'
Write-Host '모든 대상 노트가 확정된 적용본과 정확히 일치합니다.'

Write-Host '[4/4] 재대조 (읽기 전용)'
$ready = $env:MERMAID_AUDIT_SUPABASE_URL -and $env:MERMAID_AUDIT_SUPABASE_SECRET_KEY -and $env:NOTION_IMPORT_TOKEN
if ($SkipAudit -or -not $ready) {
    Write-Host '본문 일치 확인 완료. Notion 재대조는 미실행입니다. 환경변수를 준비한 뒤 재실행할 수 있습니다.'
    return
}
$after = Join-Path (Split-Path $SplitDir -Parent) ('after-' + [guid]::NewGuid().ToString('N'))
Push-Location $AuditBackend
try {
    $json = uv run python -m scripts.audit_mermaid_fences --out-dir $after
    if ($LASTEXITCODE -ne 0) { throw '재대조 도구 실행 실패. DB 적용 상태는 유지됩니다.' }
} finally { Pop-Location }
$r = ($json -join "`n") | ConvertFrom-Json
if ($null -eq $r.notes_to_change -or $null -eq $r.blocks_already_marked -or
    $null -eq $r.notion_unreadable -or $null -eq $r.excluded) { throw '재대조 결과 형식이 올바르지 않습니다.' }
if ($r.notes_to_change -ne 0 -or $r.blocks_already_marked -ne $ExpectedMarkedBlocks -or
    $r.notion_unreadable -ne 0 -or @($r.excluded.PSObject.Properties).Count -ne 0) {
    throw '재대조 결과를 확인해야 합니다. DB 적용 상태는 유지됩니다.'
}
Write-Host "본문 일치 및 재대조 확인 완료. 보고서: $after (기존 표시 블록의 Notion 재조회는 생략될 수 있습니다.)"
