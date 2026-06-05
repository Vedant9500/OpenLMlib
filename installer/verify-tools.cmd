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

REM Run the tool count check. Importing the module alone only shows core tools;
REM the MCP server registers memory and collaboration tools during startup.
pushd "%USERPROFILE%\.openlmlib" >nul
"%VENV_PYTHON%" -c "import openlmlib; from openlmlib import mcp_server as m; m._register_memory_tools(); m._register_collab_tools(); tools = set(m.mcp._tool_manager._tools); required = {'create_co_scientist_run','submit_hypothesis','start_hypothesis_verification','submit_verification','create_co_scientist_final_report'}; missing = sorted(required - tools); print(f'OpenLMlib import: {openlmlib.__file__}'); print(f'Total tools: {len(tools)}'); print(f'Missing required Co-Scientist tools: {missing}'); print(); exit(0 if len(tools) >= 76 and not missing else 1)"
set "VERIFY_ERRORLEVEL=%ERRORLEVEL%"
popd >nul

if %VERIFY_ERRORLEVEL% EQU 0 (
    echo.
    echo ========================================
    echo SUCCESS: All expected MCP tools registered!
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
    echo ERROR: Not all tools registered
    echo ========================================
    echo.
    echo Expected: at least 76 tools with Co-Scientist lifecycle tools
    echo.
    echo Troubleshooting:
    echo   1. Check installation: openlmlib doctor
    echo   2. Reinstall: npm install -g openlmlib
    echo   3. Check for errors in install logs
    echo.
)

exit /b %VERIFY_ERRORLEVEL%
