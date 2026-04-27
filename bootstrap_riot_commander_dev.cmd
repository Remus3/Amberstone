@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0bootstrap_riot_commander_dev.ps1" -Root "C:\Riot Commander"
