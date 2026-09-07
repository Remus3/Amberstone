@echo off
cd /d "C:\Riot Commander"
echo.
echo === Phase 3 Hot-Reload Test: Direct Deploy ===
echo.
echo Running transactional deploy for tft_coach_engine.py...
"%LOCALAPPDATA%\Programs\Python\Python314\python.exe" ops\rc_transactional_deploy.py ^
  --request "ops\runtime\deploy_requests\deploy-hot-reload-test-001.json" ^
  --result  "ops\runtime\deploy_results\deploy-hot-reload-test-001.json"

echo.
echo Exit code: %ERRORLEVEL%
echo.
echo Result written to: ops\runtime\deploy_results\deploy-hot-reload-test-001.json
echo.
echo Checking health.json for PID (should still be 1616 if hot-reload succeeded)...
type "ops\runtime\health.json"
echo.
pause
