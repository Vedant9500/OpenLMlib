@echo off
REM Verify MCP Tools - Run this after installing the npm package
REM Usage: verify-tools.cmd

echo ========================================
echo OpenLMlib MCP Tool Verification
echo ========================================
echo.

REM Find the Python executable in the venv
set "VENV_PYTHON=%USERPROFILE%\.openlmlib\venv\Scripts\python.exe"

if not exist "%VENV_PYTHON%" (
    echo ERROR: Virtual environment Python not found at:
    echo   %VENV_PYTHON%
    echo.
    echo Is OpenLMlib installed? Try:
    echo   npm install -g openlmlib
    exit /b 1
)

echo Python: %VENV_PYTHON%
echo.

REM Run the tool count check
"%VENV_PYTHON%" -c "from openlmlib.mcp_server import mcp; tools = mcp._tool_manager._tools; core = [n for n in tools if n.startswith('openlmlib_')]; collab = [n for n in tools if n.startswith('collab_')]; print(f'Total tools: {len(tools)}'); print(f'  Core tools: {len(core)}'); print(f'  Collab tools: {len(collab)}'); print(); exit(0 if len(tools) == 41 else 1)"

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ========================================
    echo ✓ SUCCESS: All 41 MCP tools registered!
    echo ========================================
    echo.
    echo If your IDE shows fewer tools, try:
    echo   1. Restart your IDE completely
    echo   2. Run: openlmlib mcp-config
    echo   3. Run: openlmlib doctor
    echo.
) else (
    echo.
    echo ========================================
    echo ✗ ERROR: Not all tools registered
    echo ========================================
    echo.
    echo Expected: 41 tools
    echo.
    echo Troubleshooting:
    echo   1. Check installation: openlmlib doctor
    echo   2. Reinstall: npm install -g openlmlib
    echo   3. Check for errors in install logs
    echo.
)

exit /b %ERRORLEVEL%
