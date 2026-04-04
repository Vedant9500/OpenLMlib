$ErrorActionPreference = 'Stop'

function Get-PythonCommand {
    $candidate = Get-Command py -ErrorAction SilentlyContinue
    if ($candidate) {
        return 'py'
    }

    $candidate = Get-Command python -ErrorAction SilentlyContinue
    if ($candidate) {
        return 'python'
    }

    $candidate = Get-Command python3 -ErrorAction SilentlyContinue
    if ($candidate) {
        return 'python3'
    }

    throw "No Python launcher found. Install Python 3.10+ and ensure python is on PATH."
}

function Refresh-Path {
    $pathsToAdd = @(
        (Join-Path $HOME '.local\bin'),
        (Join-Path $env:APPDATA 'Python\Scripts')
    )

    $versioned = Get-ChildItem (Join-Path $env:APPDATA 'Python') -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like 'Python*' } |
        ForEach-Object { Join-Path $_.FullName 'Scripts' }
    $pathsToAdd += $versioned

    foreach ($p in $pathsToAdd) {
        if ($p -and (Test-Path $p) -and ($env:Path -notlike "*$p*")) {
            $env:Path += ";$p"
        }
    }
}

function Invoke-Pipx {
    param([string[]]$PipxArgs)

    $pipxCmd = Get-Command pipx -ErrorAction SilentlyContinue
    if ($pipxCmd) {
        & pipx @PipxArgs
        return
    }

    & $script:PythonCmd -m pipx @PipxArgs
}

function Ensure-Pipx {
    $pipxCmd = Get-Command pipx -ErrorAction SilentlyContinue
    if (-not $pipxCmd) {
        Write-Host "pipx not found. Installing pipx..."
        & $script:PythonCmd -m pip install --user pipx
        & $script:PythonCmd -m pipx ensurepath
        Refresh-Path
    }
}

$script:PythonCmd = Get-PythonCommand
Ensure-Pipx
Refresh-Path

if (-not (Test-Path .\pyproject.toml)) {
    Write-Error "Run this script from the OpenLMlib repository root."
    exit 1
}

Invoke-Pipx -PipxArgs @('install', '.', '--force')
if ($LASTEXITCODE -ne 0) {
    Write-Error "pipx install failed."
    exit $LASTEXITCODE
}

$openlmlibCmd = Get-Command openlmlib -ErrorAction SilentlyContinue
if ($openlmlibCmd) {
    & openlmlib setup
    if ($LASTEXITCODE -ne 0) {
        Write-Error "openlmlib setup failed."
        exit $LASTEXITCODE
    }

    & openlmlib doctor
    if ($LASTEXITCODE -ne 0) {
        Write-Error "openlmlib doctor failed."
        exit $LASTEXITCODE
    }
} else {
    Write-Warning "openlmlib command is not available in this shell yet. Running setup via pipx fallback."

    Invoke-Pipx -PipxArgs @('run', '--spec', '.', 'openlmlib', 'setup')
    if ($LASTEXITCODE -ne 0) {
        Write-Error "openlmlib setup failed via pipx fallback."
        exit $LASTEXITCODE
    }

    Invoke-Pipx -PipxArgs @('run', '--spec', '.', 'openlmlib', 'doctor')
    if ($LASTEXITCODE -ne 0) {
        Write-Error "openlmlib doctor failed via pipx fallback."
        exit $LASTEXITCODE
    }
}

Write-Host "OpenLMlib installed and validated. Try: openlmlib query --query 'retrieval'"
