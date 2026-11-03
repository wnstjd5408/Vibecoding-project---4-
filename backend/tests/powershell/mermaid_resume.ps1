param([string]$Runner = "$PSScriptRoot/../../scripts/apply_mermaid_fences.ps1")
$ErrorActionPreference = 'Stop'
# No Docker process or network call is possible: intercept the executable name.
function global:docker {
    $commandText = $args[-1]
    $file = [regex]::Match($commandText, '/sql/([^ ]+)$').Groups[1].Value
    $global:meg170Test_calls.Add($file)
    $global:LASTEXITCODE = 0
    switch ($file) {
        'state-pilot.sql' { return "39,$global:meg170Test_pilot" }
        'state-rest.sql' {
            return (@(1,2,4,5,6,14,18,20,21,22,24,25,27,31,34,37,38,40) | ForEach-Object { "$_,$global:meg170Test_rest" }) -join "`n"
        }
        '1-pilot-apply.sql' {
            if ($global:meg170Test_pilot -ne 'original') { $global:LASTEXITCODE=1; return 'changed since audit' }
            $global:meg170Test_pilot='applied'; return ''
        }
        '1-pilot-restore.sql' {
            if ($global:meg170Test_pilot -ne 'applied') { $global:LASTEXITCODE=1; return 'changed since audit' }
            $global:meg170Test_pilot='original'; return ''
        }
        '2-rest-apply.sql' { $global:meg170Test_rest='applied'; return '' }
        'verify-pilot.sql' { return '39,4,1' }
        'verify-all.sql' { return '19,2,4,68' }
        default { throw "Unexpected command blocked: $file" }
    }
}
function global:uv { throw 'Network/audit execution is forbidden in this test.' }
function global:Read-Host {
    param([string]$Prompt, [switch]$MaskInput)
    if ($global:meg170Test_answers.Count -eq 0) { throw "Unexpected question: $Prompt" }
    return $global:meg170Test_answers.Dequeue()
}
$cases = @(
    @{name='fresh apply';pilot='original';rest='original';answers=@('y','y','y');writes=@('1-pilot-apply.sql','2-rest-apply.sql');error=$false},
    @{name='resume after k';pilot='applied';rest='original';answers=@('y','y');writes=@('2-rest-apply.sql');error=$false},
    @{name='all applied rerun';pilot='applied';rest='applied';answers=@('y');writes=@();error=$false},
    @{name='keep pilot';pilot='applied';rest='original';answers=@('k');writes=@();error=$false},
    @{name='restore pilot';pilot='applied';rest='original';answers=@('n');writes=@('1-pilot-restore.sql');error=$false},
    @{name='pilot drift';pilot='drift';rest='original';answers=@();writes=@();error=$true},
    @{name='rest drift';pilot='original';rest='drift';answers=@();writes=@();error=$true},
    @{name='missing pilot';pilot='missing';rest='original';answers=@();writes=@();error=$true},
    @{name='rest only applied';pilot='original';rest='applied';answers=@();writes=@();error=$true},
    @{name='do not restore pilot alone';pilot='applied';rest='applied';answers=@('n');writes=@();error=$true}
)
$oldDb=$env:DATABASE_URL
$fixtureDir=Join-Path ([System.IO.Path]::GetTempPath()) ([guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $fixtureDir | Out-Null
foreach ($file in @('state-pilot.sql','state-rest.sql','1-pilot-apply.sql','1-pilot-restore.sql','2-rest-apply.sql')) { Set-Content -LiteralPath (Join-Path $fixtureDir $file) -Value '-- synthetic; never executed' }
try {
    $env:DATABASE_URL='mock://offline-only'
    foreach ($case in $cases) {
        $global:meg170Test_pilot=$case.pilot; $global:meg170Test_rest=$case.rest
        $global:meg170Test_calls=[System.Collections.Generic.List[string]]::new()
        $global:meg170Test_answers=[System.Collections.Generic.Queue[string]]::new()
        foreach ($answer in $case.answers) { $global:meg170Test_answers.Enqueue($answer) }
        $failed=$false
        try { & $Runner -SkipAudit -SplitDir $fixtureDir -PilotNoteId 39 -RestNoteIds @(1,2,4,5,6,14,18,20,21,22,24,25,27,31,34,37,38,40) -ExpectedMarkedBlocks 68 -NoteUrl 'https://example.invalid/notes/39' 6>$null } catch { $failed=$true; $caught = $_.Exception.Message }
        $writes=@($global:meg170Test_calls | Where-Object { $_ -match '(apply|restore)\.sql$' })
        if ($failed -ne $case.error -or ($writes -join ',') -ne ($case.writes -join ',')) {
            throw "FAIL $($case.name): error=$failed writes=$($writes -join ',') cause=$caught"
        }
        Write-Output "PASS $($case.name)"
    }
} finally {
    foreach ($file in Get-ChildItem -LiteralPath $fixtureDir -File) { Remove-Item -LiteralPath $file.FullName }
    Remove-Item -LiteralPath $fixtureDir
    $env:DATABASE_URL=$oldDb
    Remove-Item Function:\global:docker,Function:\global:uv,Function:\global:Read-Host
}

