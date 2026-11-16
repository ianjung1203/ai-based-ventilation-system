param([string]$Python = '', [int]$Port = 8765)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not $Python) {
    $bundled = 'C:\Program Files\WindowsApps\OpenAI.CodexPrimaryRuntime.v26-1112-611-0_26.1112.611.0_x64__3k8sg7r9htsxt\dependencies\python\python.exe'
    if (Test-Path -LiteralPath $bundled) { $Python = $bundled }
    elseif (Test-Path -LiteralPath '.venv\Scripts\python.exe') { $Python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe' }
    else { $Python = (Get-Command python -ErrorAction Stop).Source }
}
& $Python -X utf8 -m ventilation_ai serve --model 'artifacts/demo_model' --port $Port
