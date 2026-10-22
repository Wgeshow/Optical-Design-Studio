param([switch]$Launch, [Parameter(ValueFromRemainingArguments=$true)][string[]]$ApplicationArguments = @())
$ErrorActionPreference = 'Stop'
$sourceDirectory = $PSScriptRoot
$runtimeRoot = Join-Path $env:LOCALAPPDATA 'OpticalDesignStudio\SolverEnvironments'
$runtimeReceipt = Join-Path $runtimeRoot 'desktop.json'

function Assert-OwnedPath([string]$TargetPath) {
    $full = [IO.Path]::GetFullPath($TargetPath)
    $allowed = [IO.Path]::GetFullPath($runtimeRoot)
    if ($full -ne $allowed -and -not $full.StartsWith($allowed + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Setup target is outside its managed directory.' }
    $item = $full
    while ($item) {
        if ((Test-Path -LiteralPath $item) -and ((Get-Item -LiteralPath $item).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Managed setup paths cannot contain links or junctions.' }
        $item = [IO.Path]::GetDirectoryName($item)
    }
}

try {
    if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { throw 'Automatic source setup requires Windows x64.' }
    Assert-OwnedPath $runtimeRoot
    $pythonPath = $null
    if (Test-Path -LiteralPath $runtimeReceipt) {
        $receipt = Get-Content -LiteralPath $runtimeReceipt -Raw | ConvertFrom-Json
        if ($receipt.schema -eq 1 -and $receipt.python) {
            Assert-OwnedPath $receipt.python
            if (Test-Path -LiteralPath $receipt.python) {
                & $receipt.python (Join-Path $sourceDirectory 'desktop_environment_probe.py')
                if ($LASTEXITCODE -eq 0) { $pythonPath = $receipt.python }
            }
        }
    }
    if (-not $pythonPath) {
        Write-Host 'Creating the Optical Design Studio environment. Python and required packages download into a separate application folder.'
        [void](New-Item -ItemType Directory -Path $runtimeRoot -Force)
        $uvArchive = Join-Path $runtimeRoot 'uv-0.11.19-win_amd64.whl'
        $uvBinary = Join-Path $runtimeRoot 'uv-0.11.19.exe'
        Assert-OwnedPath $uvArchive
        Assert-OwnedPath $uvBinary
        $expectedHash = '480fc34a8d0967af6a90b3f99a6e5687cd5c6e29528de96bec04d6e305a59363'
        if (-not (Test-Path -LiteralPath $uvArchive) -or (Get-FileHash -LiteralPath $uvArchive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedHash) {
            Invoke-WebRequest -UseBasicParsing -Uri 'https://files.pythonhosted.org/packages/d4/43/f374fad7ad94e4a8c47cf09f00d803c76c6cc7f225668c41f4e2fb5de000/uv-0.11.19-py3-none-win_amd64.whl' -OutFile $uvArchive
        }
        if ((Get-FileHash -LiteralPath $uvArchive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedHash) { throw 'Environment-manager download failed SHA256 verification.' }
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $archive = [IO.Compression.ZipFile]::OpenRead($uvArchive)
        try {
            $entries = @($archive.Entries | Where-Object { $_.FullName.EndsWith('/scripts/uv.exe') })
            if ($entries.Count -ne 1) { throw 'Unexpected environment-manager archive.' }
            [IO.Compression.ZipFileExtensions]::ExtractToFile($entries[0], $uvBinary, $true)
        } finally { $archive.Dispose() }
        $env:UV_PYTHON_INSTALL_DIR = Join-Path $runtimeRoot 'python'
        $env:UV_CACHE_DIR = Join-Path $runtimeRoot 'cache'
        $env:TEMP = Join-Path $runtimeRoot 'tmp'
        $env:TMP = $env:TEMP
        foreach ($directory in @($env:UV_PYTHON_INSTALL_DIR, $env:UV_CACHE_DIR, $env:TEMP)) {
            Assert-OwnedPath $directory
            [void](New-Item -ItemType Directory -Path $directory -Force)
        }
        $env:UV_PYTHON_NO_REGISTRY = '1'
        $env:UV_LINK_MODE = 'copy'
        $env:PYTHONNOUSERSITE = '1'
        $env:PYTHONPATH = ''
        $env:PYTHONHOME = ''
        $prefix = Join-Path $runtimeRoot ('environments\desktop-' + [Guid]::NewGuid().ToString('N'))
        Assert-OwnedPath $prefix
        & $uvBinary --no-config venv --python 3.12 --managed-python $prefix
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the isolated Python environment. Check the setup output and internet connection, then retry.' }
        $pythonPath = Join-Path $prefix 'Scripts\python.exe'
        & $uvBinary --no-config pip install --python $pythonPath --index-url 'https://pypi.org/simple' -r (Join-Path $sourceDirectory 'requirements.txt') 'mkl==2023.1.0' 'intel-openmp==2023.1.0' 'tbb==2021.9.0' 'scikit-learn==1.7.2' 'joblib==1.5.3' 'threadpoolctl==3.6.0'
        if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Existing installations were preserved; retry to create a new environment.' }
        & $pythonPath (Join-Path $sourceDirectory 'desktop_environment_probe.py')
        if ($LASTEXITCODE -ne 0) { throw 'Environment verification failed. Review the diagnostic above. This environment was not selected.' }
        $receiptText = @{schema=1; python=$pythonPath; source=$sourceDirectory} | ConvertTo-Json
        [IO.File]::WriteAllText($runtimeReceipt, $receiptText, [Text.UTF8Encoding]::new($false))
    }
    Write-Host ('Environment ready: ' + $pythonPath)
    if ($Launch) {
        & $pythonPath (Join-Path $sourceDirectory 'qt_app.py') @ApplicationArguments
        exit $LASTEXITCODE
    }
} catch {
    Write-Error $_
    exit 1
}
