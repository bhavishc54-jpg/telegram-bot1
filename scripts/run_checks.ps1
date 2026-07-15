$ErrorActionPreference = "Stop"
$Python = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
$Ruff = Join-Path $PSScriptRoot "..\.venv\Scripts\ruff.exe"
$Bandit = Join-Path $PSScriptRoot "..\.venv\Scripts\bandit.exe"

& $Ruff format --check app tests scripts alembic
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Ruff check app tests scripts alembic
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python -m compileall -q app tests scripts alembic
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python -m pytest -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Bandit -q -r app scripts alembic
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $Python -m pip check
exit $LASTEXITCODE
