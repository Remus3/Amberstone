@echo off
rem Launch the Riot Commander Electron companion/overlay shell.
rem Points the bundled Electron binary at this package (same as npm start =
rem "electron ."), but with no lingering console window (start + exit).
rem The Desktop "RC Overlay" shortcut targets electron.exe directly; this .bat
rem is the terminal-friendly equivalent and the single place to add env (e.g.
rem set RC_ORIGIN=https://127.0.0.1:8888) before launch.
start "" /d "%~dp0" "%~dp0node_modules\electron\dist\electron.exe" .
exit
