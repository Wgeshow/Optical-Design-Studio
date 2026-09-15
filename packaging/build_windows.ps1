param(
    [Parameter(Mandatory=$true)][string]$SourceRoot,
    [string]$DataBundle,
    [ValidateSet('private','public')][string]$Profile = 'private',
    [string]$PublicSource,
    [string]$Python = 'python',
    [string]$InnoCompiler = (Join-Path $PSScriptRoot 'tools\InnoSetup7\ISCC.exe')
)
$ErrorActionPreference = 'Stop'
$sourcePath = (Resolve-Path -LiteralPath $SourceRoot).Path
$compilerPath = (Resolve-Path -LiteralPath $InnoCompiler).Path
$env:PYTHONNOUSERSITE = '1'
Push-Location -LiteralPath $PSScriptRoot
try {
    $prepareArgs = @('prepare_payload.py', '--source', $sourcePath, '--profile', $Profile)
    if ($DataBundle) { $prepareArgs += @('--bundle', (Resolve-Path -LiteralPath $DataBundle).Path) }
    if ($PublicSource) { $prepareArgs += @('--public-source', (Resolve-Path -LiteralPath $PublicSource).Path) }
    & $Python @prepareArgs
    if ($LASTEXITCODE -ne 0) { throw 'Payload preparation failed.' }
    & $Python clean_payload.py
    if ($LASTEXITCODE -ne 0) { throw 'Previous generated payload cleanup failed.' }
    & $Python -m PyInstaller --noconfirm --distpath dist --workpath work OpticalDesignStudio.spec
    if ($LASTEXITCODE -ne 0) { throw 'Application compilation failed.' }
    & $Python augment_native_runtime.py
    if ($LASTEXITCODE -ne 0) { throw 'Native dependency verification failed.' }
    & $Python finalize_payload.py
    if ($LASTEXITCODE -ne 0) { throw 'Payload finalization failed.' }
    $appPath = Join-Path $PSScriptRoot 'dist\Optical Design Studio\Optical Design Studio.exe'
    $testPath = Join-Path $PSScriptRoot 'build-verification\report.json'
    $env:S4_LIBRARY_ROOT = Join-Path $PSScriptRoot 'build-verification\User Data'
    $inputManifest = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'build_input\build_input.json') -Raw | ConvertFrom-Json
    $env:S4_SELF_TEST_MIN_SAVED_ENTRIES = [string]$inputManifest.seed_runs
    $env:S4_SELF_TEST_EXPECT_EMPTY_LIBRARY = if ($Profile -eq 'public') { '1' } else { '0' }
    $testProcess = Start-Process -FilePath $appPath -ArgumentList @('--self-test', ('"'+$testPath+'"')) -WindowStyle Hidden -PassThru -Wait
    if ($testProcess.ExitCode -ne 0) { throw "Bundled application verification failed. See $testPath" }
    & $compilerPath OpticalDesignStudio.iss
    if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed.' }
    Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'release') -Filter '*.exe' | Get-FileHash -Algorithm SHA256
} finally {
    Pop-Location
}
