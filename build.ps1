param(
    [switch]$SkipInstaller
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$pythonExe = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { 'python' }
$schemaData = (Join-Path $PSScriptRoot 'response.schema.json') + ':.'
$iconData = (Join-Path $PSScriptRoot 'momo.ico') + ':.'

& $pythonExe -m PyInstaller --noconfirm --clean --onedir --windowed `
    --name MomoFriends --icon (Join-Path $PSScriptRoot 'momo.ico') `
    --add-data $schemaData --add-data $iconData `
    --distpath (Join-Path $PSScriptRoot 'dist') `
    --workpath (Join-Path $PSScriptRoot 'build\pyinstaller') `
    --specpath (Join-Path $PSScriptRoot 'build') `
    assistant.py
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller 빌드에 실패했습니다.' }

if (-not $SkipInstaller) {
    $compiler = Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'
    if (-not (Test-Path -LiteralPath $compiler)) {
        $compiler = 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
    }
    if (-not (Test-Path -LiteralPath $compiler)) {
        throw 'Inno Setup 6의 ISCC.exe를 찾지 못했습니다.'
    }
    & $compiler (Join-Path $PSScriptRoot 'installer.iss')
    if ($LASTEXITCODE -ne 0) { throw '설치 파일 생성에 실패했습니다.' }
}
