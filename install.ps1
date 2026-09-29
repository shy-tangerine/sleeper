$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = if ($env:PYTHON) { $env:PYTHON } else { "py" }
& $Python "$Root/scripts/install.py" @args
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
