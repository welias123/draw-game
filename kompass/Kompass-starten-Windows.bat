@echo off
rem Kompass: oeffnet die Website in Brave, startet die App und legt eine Desktop-Verknuepfung an.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0launcher\windows.ps1"
if errorlevel 1 pause
