@echo off
:: tools\rollback_last.cmd
:: Reverts the most recent checkpoint commit.
:: Safe: uses --soft by default so changes stay staged (not lost).
:: Run from C:\Riot Commander

setlocal
cd /d "C:\Riot Commander"

echo [rollback] Last 3 commits:
git log --oneline -3
echo.

:: --soft keeps changes staged so they can be re-committed or inspected
:: Use --hard only if you want to discard all changes entirely
set /p CONFIRM="Roll back most recent commit? Changes stay staged. (y/N): "
if /i not "%CONFIRM%"=="y" (
    echo [rollback] Cancelled.
    exit /b 0
)

git reset --soft HEAD~1

if errorlevel 1 (
    echo [rollback] FAIL: git reset failed.
    exit /b 1
)

echo [rollback] Done. Changes are staged. Use 'git status' to review.
exit /b 0
