@echo off
set "RC_ROOT=%~dp0.."
mkdir "%RC_ROOT%\ops\runtime\deploy_requests" 2>nul
mkdir "%RC_ROOT%\ops\runtime\deploy_results" 2>nul
mkdir "%RC_ROOT%\ops\runtime\logs" 2>nul
mkdir "%RC_ROOT%\ops\runtime\supervisor_requests" 2>nul
mkdir "%RC_ROOT%\ops\examples" 2>nul
echo Directories created.
