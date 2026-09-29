# Kompass fuer Windows einrichten:
#  1. Desktop-Verknuepfung "Kompass" anlegen (oeffnet Kompass als App-Fenster in Brave)
#  2. Kompass als Website in Brave oeffnen
#  3. Kompass als App-Fenster starten
$ErrorActionPreference = 'Stop'

$root  = Split-Path -Parent $PSScriptRoot
$index = Join-Path $root 'index.html'
$icon  = Join-Path $root 'icons\kompass.ico'
$url   = ([System.Uri]$index).AbsoluteUri

function Find-Brave {
  $candidates = @()
  foreach ($key in @(
      'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\brave.exe',
      'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\brave.exe')) {
    try {
      $p = (Get-ItemProperty -Path $key -ErrorAction Stop).'(default)'
      if ($p) { $candidates += $p }
    } catch {}
  }
  $candidates += @(
    (Join-Path $env:ProgramFiles 'BraveSoftware\Brave-Browser\Application\brave.exe'),
    (Join-Path $env:LOCALAPPDATA 'BraveSoftware\Brave-Browser\Application\brave.exe')
  )
  if (${env:ProgramFiles(x86)}) {
    $candidates += (Join-Path ${env:ProgramFiles(x86)} 'BraveSoftware\Brave-Browser\Application\brave.exe')
  }
  foreach ($c in $candidates) {
    if ($c -and (Test-Path -LiteralPath $c)) { return $c }
  }
  return $null
}

function New-KompassShortcut([string]$path, [string]$target, [string]$arguments) {
  $shell = New-Object -ComObject WScript.Shell
  $sc = $shell.CreateShortcut($path)
  $sc.TargetPath = $target
  $sc.Arguments = $arguments
  $sc.WorkingDirectory = $root
  $sc.IconLocation = "$icon,0"
  $sc.Description = 'Kompass Tagesplaner'
  $sc.Save()
}

Write-Host ''
Write-Host '  Kompass wird eingerichtet ...' -ForegroundColor Cyan

$brave = Find-Brave
$desktop = [Environment]::GetFolderPath('Desktop')
$programs = [Environment]::GetFolderPath('Programs')

if ($brave) {
  $appArgs = "--app=`"$url`""
  New-KompassShortcut (Join-Path $desktop 'Kompass.lnk') $brave $appArgs
  try { New-KompassShortcut (Join-Path $programs 'Kompass.lnk') $brave $appArgs } catch {}
  Write-Host '  [ok] Desktop-Verknuepfung "Kompass" angelegt' -ForegroundColor Green

  Start-Process -FilePath $brave -ArgumentList "`"$url`""
  Write-Host '  [ok] Website in Brave geoeffnet' -ForegroundColor Green
  Start-Sleep -Milliseconds 900
  Start-Process -FilePath $brave -ArgumentList $appArgs
  Write-Host '  [ok] Kompass-App gestartet' -ForegroundColor Green
} else {
  Write-Host '  Brave wurde nicht gefunden. Kompass oeffnet sich im Standardbrowser.' -ForegroundColor Yellow
  New-KompassShortcut (Join-Path $desktop 'Kompass.lnk') $index ''
  Write-Host '  [ok] Desktop-Verknuepfung "Kompass" angelegt' -ForegroundColor Green
  Start-Process -FilePath $index
}

Write-Host ''
Write-Host '  Fertig. Ab jetzt reicht ein Doppelklick auf "Kompass" auf dem Desktop.' -ForegroundColor Cyan
Start-Sleep -Seconds 3
