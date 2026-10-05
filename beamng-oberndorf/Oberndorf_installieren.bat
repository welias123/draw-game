@echo off
title Oberndorf in Tirol - BeamNG Map Installer
echo.
echo   ===================================================
echo     Oberndorf in Tirol - BeamNG.drive Map Installer
echo   ===================================================
echo.
set "OBD_DIR=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=[IO.File]::ReadAllText('%~f0',[Text.Encoding]::UTF8); $i=$s.LastIndexOf('#'+'#PS-START'); Invoke-Expression $s.Substring($i)"
echo.
pause
exit /b

##PS-START
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$ZipName = 'oberndorf_in_tirol.zip'
$Url = 'https://raw.githubusercontent.com/welias123/draw-game/refs/heads/claude/lucid-galileo-vuuiuy/beamng-oberndorf/dist/oberndorf_in_tirol.zip'

function Test-MapZip($path) {
    if (-not (Test-Path -LiteralPath $path)) { return $false }
    if ((Get-Item -LiteralPath $path).Length -lt 10MB) { return $false }
    try {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $z = [IO.Compression.ZipFile]::OpenRead($path)
        $ok = @($z.Entries | Where-Object { $_.FullName -eq 'levels/oberndorf_in_tirol/info.json' }).Count -gt 0
        $z.Dispose()
        return $ok
    } catch { return $false }
}

function Find-BeamNGUserDir {
    $docs = [Environment]::GetFolderPath('MyDocuments')
    $bases = @()
    if ($env:LOCALAPPDATA) {
        $bases += (Join-Path $env:LOCALAPPDATA 'BeamNG\BeamNG.drive')
        $bases += (Join-Path $env:LOCALAPPDATA 'BeamNG.drive')
    }
    if ($docs) { $bases += (Join-Path $docs 'BeamNG.drive') }
    $found = @()
    foreach ($b in $bases) {
        if (-not (Test-Path -LiteralPath $b)) { continue }
        $cur = Join-Path $b 'current'
        if (Test-Path -LiteralPath $cur) {
            $found += [pscustomobject]@{ Path = $cur; Ver = [version]'9999.0' }
            continue
        }
        $vers = @(Get-ChildItem -LiteralPath $b -Directory | Where-Object { $_.Name -match '^\d+\.\d+(\.\d+)?$' })
        foreach ($v in $vers) { $found += [pscustomobject]@{ Path = $v.FullName; Ver = [version]$v.Name } }
        if ($vers.Count -eq 0 -and ((Test-Path -LiteralPath (Join-Path $b 'mods')) -or (Test-Path -LiteralPath (Join-Path $b 'settings')))) {
            $found += [pscustomobject]@{ Path = $b; Ver = [version]'0.0' }
        }
    }
    if ($found.Count -eq 0) { return $null }
    return ($found | Sort-Object Ver -Descending | Select-Object -First 1).Path
}

try {
    # 1) BeamNG-Ordner finden
    $user = Find-BeamNGUserDir
    if ($user) {
        $mods = Join-Path $user 'mods'
    } else {
        Write-Host '  BeamNG-Ordner nicht automatisch gefunden.'
        Write-Host '  Bitte den Mods-Ordner auswaehlen (im Spiel: Mods -> "Ordner oeffnen").'
        Add-Type -AssemblyName System.Windows.Forms
        $dlg = New-Object System.Windows.Forms.FolderBrowserDialog
        $dlg.Description = 'BeamNG.drive Mods-Ordner auswaehlen'
        if ($dlg.ShowDialog() -ne [System.Windows.Forms.DialogResult]::OK) { throw 'Kein Ordner ausgewaehlt.' }
        $mods = $dlg.SelectedPath
    }
    if (-not (Test-Path -LiteralPath $mods)) { New-Item -ItemType Directory -Path $mods | Out-Null }
    Write-Host "  Mods-Ordner: $mods"
    $target = Join-Path $mods $ZipName

    # 2) Map holen: schon heruntergeladen (neben dem Installer / in Downloads)? Sonst von GitHub laden.
    $local = @()
    if ($env:OBD_DIR) { $local += (Join-Path $env:OBD_DIR $ZipName) }
    if ($env:USERPROFILE) { $local += (Join-Path $env:USERPROFILE ("Downloads\" + $ZipName)) }
    $src = $null
    foreach ($p in $local) { if (Test-MapZip $p) { $src = $p; break } }
    if ($src) {
        Write-Host "  Verwende vorhandene Datei: $src"
        Copy-Item -LiteralPath $src -Destination $target -Force
    } else {
        $tmp = Join-Path $env:TEMP $ZipName
        Write-Host '  Lade die Map herunter (ca. 80 MB) - bitte warten ...'
        (New-Object System.Net.WebClient).DownloadFile($Url, $tmp)
        if (-not (Test-MapZip $tmp)) { throw 'Download fehlgeschlagen oder Datei beschaedigt. Bitte nochmal starten.' }
        Move-Item -LiteralPath $tmp -Destination $target -Force
    }
    if (-not (Test-MapZip $target)) { throw "Kopieren nach $target fehlgeschlagen." }

    Write-Host ''
    Write-Host '  FERTIG! Die Map ist installiert.'
    Write-Host '  Im Spiel: Freeroam -> "Oberndorf in Tirol" auswaehlen.'
    Write-Host '  (Der erste Start dauert ein paar Minuten, danach geht es schneller.)'
    if (Get-Process -Name 'BeamNG*' -ErrorAction SilentlyContinue) {
        Write-Host ''
        Write-Host '  BeamNG laeuft gerade - bitte das Spiel einmal neu starten.'
    } else {
        Write-Host ''
        $a = Read-Host '  BeamNG.drive jetzt starten? (j/n)'
        if ($a -match '^[jJyY]') {
            try { Start-Process 'steam://rungameid/284160' } catch { Write-Host '  Bitte BeamNG.drive selbst starten.' }
        }
    }
} catch {
    Write-Host ''
    Write-Host ('  FEHLER: ' + $_.Exception.Message) -ForegroundColor Red
    Write-Host '  Alternative: oberndorf_in_tirol.zip von GitHub laden und in den Mods-Ordner kopieren.'
}
