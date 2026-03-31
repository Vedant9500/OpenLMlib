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
    Write-Error "Run this script from the LMlib repository root."
    exit 1
}

Invoke-Pipx -PipxArgs @('install', '.', '--force')
if ($LASTEXITCODE -ne 0) {
    Write-Error "pipx install failed."
    exit $LASTEXITCODE
}

$lmlibCmd = Get-Command lmlib -ErrorAction SilentlyContinue
if ($lmlibCmd) {
    & lmlib setup
    if ($LASTEXITCODE -ne 0) {
        Write-Error "lmlib setup failed."
        exit $LASTEXITCODE
    }

    & lmlib doctor
    if ($LASTEXITCODE -ne 0) {
        Write-Error "lmlib doctor failed."
        exit $LASTEXITCODE
    }
} else {
    Write-Warning "lmlib command is not available in this shell yet. Open a new terminal and run:"
    Write-Host "  lmlib setup"
    Write-Host "  lmlib doctor"
    exit 1
}

Write-Host "LMlib installed and validated. Try: lmlib query --query 'retrieval'"
