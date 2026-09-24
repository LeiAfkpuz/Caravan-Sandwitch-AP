# Repackage the apworld, install it, run N generations with stderr captured
# (the frozen ArchipelagoGenerate.exe waits on input() after an exception,
# which looks like a hang through a pipe), report sphere sizes, and commit
# only if every run passes.
#   powershell -File tools\gentest.ps1 [-Runs 3] [-CommitMsg "..."]
param([int]$Runs = 3, [string]$CommitMsg = "")
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
$scratch = Join-Path $env:TEMP "csw_gentest"
$players = Join-Path $scratch "players"
$out = Join-Path $scratch "out"
New-Item -ItemType Directory -Force $players, $out | Out-Null
if (-not (Test-Path "$players\test.yaml")) {
    "name: Player`ngame: Caravan SandWitch`nCaravan SandWitch: {}" | Out-File -Encoding ascii "$players\test.yaml"
}

Set-Location "$repo\apworld"
if (Test-Path caravan_sandwitch.apworld) { Remove-Item caravan_sandwitch.apworld -Force }
python -c "import shutil,os; shutil.make_archive('caravan_sandwitch','zip','.','caravan_sandwitch'); os.replace('caravan_sandwitch.zip','caravan_sandwitch.apworld')"
Copy-Item caravan_sandwitch.apworld "C:\ProgramData\Archipelago\custom_worlds\" -Force
Write-Output "apworld repackaged+installed"

$pass = 0
foreach ($i in 1..$Runs) {
    $so = "$scratch\g$i.out"; $se = "$scratch\g$i.err"
    $p = Start-Process -FilePath "C:\ProgramData\Archipelago\ArchipelagoGenerate.exe" `
        -ArgumentList "--player_files_path `"$players`" --outputpath `"$out`" --spoiler 2" `
        -RedirectStandardOutput $so -RedirectStandardError $se -PassThru -NoNewWindow
    $p.WaitForExit(60000) | Out-Null
    if (-not $p.HasExited) { $p.Kill(); Write-Output "run $i : HUNG (killed)" }
    $errText = if (Test-Path $se) { Get-Content $se -Raw } else { "" }
    $outText = if (Test-Path $so) { Get-Content $so -Raw } else { "" }
    $bad = $errText -match "Traceback" -or $errText -match "FillError" -or $errText -match "Unreachable"
    if ($outText -match "Done\. Enjoy" -and -not $bad) {
        Write-Output "run $i : PASS"; $pass++
    } else {
        Write-Output "run $i : FAIL"
        ($errText -split "`n") | Where-Object { $_ -match "Error" -or $_ -match "Traceback" -or $_ -match "caravan_sandwitch" } |
            Where-Object { $_ -notmatch "Witchspring" -and $_ -notmatch "already registered" -and $_ -notmatch "manifest" } |
            Select-Object -Last 8
    }
}

if ($pass -eq $Runs) {
    $z = Get-ChildItem "$out\*.zip" | Sort-Object LastWriteTime | Select-Object -Last 1
    $x = "$out\x"; if (Test-Path $x) { Remove-Item $x -Recurse -Force }
    Expand-Archive $z.FullName $x -Force
    $sp = Get-ChildItem "$x\*Spoiler.txt" | Select-Object -First 1
    $inPt = $false; $cur = $null; $counts = [ordered]@{}
    foreach ($l in (Get-Content $sp.FullName)) {
        if ($l -match '^Playthrough') { $inPt = $true; continue }
        if (-not $inPt) { continue }
        if ($l -match '^Unreachable' -or $l -match '^Paths') { break }
        if ($l -match '^(\d+): \{') { $cur = $Matches[1]; $counts[$cur] = 0; continue }
        if ($l -match '^\}') { $cur = $null; continue }
        if ($null -ne $cur -and $l -match '\S') { $counts[$cur]++ }
    }
    $summary = ($counts.GetEnumerator() | ForEach-Object { "s$($_.Key)=$($_.Value)" }) -join " "
    Write-Output "spheres (playthrough, progression-only): $summary"
    if ($CommitMsg -ne "") {
        Set-Location $repo
        git add -A | Out-Null
        git commit -q -m "$CommitMsg`n`nCo-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
        Write-Output "committed"
    }
} else {
    Write-Output "NOT committed ($pass/$Runs passed)"
}
