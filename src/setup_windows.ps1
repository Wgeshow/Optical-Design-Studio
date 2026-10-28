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
        # AppData is normally hidden. Include hidden ancestors while still
        # rejecting links and junctions anywhere in the managed path.
        if ((Test-Path -LiteralPath $item) -and ((Get-Item -LiteralPath $item -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Managed setup paths cannot contain links or junctions.' }
        $item = [IO.Path]::GetDirectoryName($item)
    }
}


function Find-OwnedPython {
    $pythonRoot = Join-Path $runtimeRoot 'python'
    Assert-OwnedPath $pythonRoot
    if (-not (Test-Path -LiteralPath $pythonRoot)) { return $null }
    # Use a physical patch-version directory. uv's minor-version junction can
    # fail on Windows even after its Python download has completed successfully.
    $candidates = Get-ChildItem -LiteralPath $pythonRoot -Directory -Force |
        Where-Object { $_.Name -match '^cpython-3\.12\.\d+-windows-x86_64-none$' } |
        Sort-Object { [version]($_.Name -replace '^cpython-([\d.]+)-.*$', '$1') } -Descending
    foreach ($candidate in $candidates) {
        $executable = Join-Path $candidate.FullName 'python.exe'
        Assert-OwnedPath $executable
        if (Test-Path -LiteralPath $executable -PathType Leaf) {
            & $executable -I -c 'import sys, venv, ssl, encodings; assert sys.version_info[:2] == (3, 12) and sys.maxsize > 2**32'
            if ($LASTEXITCODE -eq 0) { return $executable }
        }
    }
    return $null
}

try {
    # These settings apply equally to a saved runtime and a first installation.
    # The launcher runs this script in a child PowerShell process.
    foreach ($variable in @(Get-ChildItem Env:)) {
        if ($variable.Name -match '^(UV_|PIP_)' -or $variable.Name -in @('PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV', 'CONDA_PREFIX')) {
            Remove-Item -LiteralPath ('Env:' + $variable.Name)
        }
    }
    $env:PYTHONNOUSERSITE = '1'
    if (-not [Environment]::Is64BitOperatingSystem -or $env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { throw 'Automatic source setup requires Windows x64.' }
    Assert-OwnedPath $runtimeRoot
    Assert-OwnedPath $runtimeReceipt
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
        $basePython = Find-OwnedPython
        if (-not $basePython) {
            & $uvBinary --no-config python install --no-bin --no-registry 3.12
            $installExitCode = $LASTEXITCODE
            $basePython = Find-OwnedPython
            if (-not $basePython) { throw 'Could not install a working 64-bit Python 3.12. Check the setup output and internet connection, then retry.' }
            if ($installExitCode -ne 0) {
                Write-Warning 'The Python installer reported an error, but the physical Python installation passed verification. Continuing with that verified interpreter.'
            }
        }
        & $basePython -I -m venv --without-pip $prefix
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the isolated Python environment. Check the setup output and retry.' }
        $pythonPath = Join-Path $prefix 'Scripts\python.exe'
        & $uvBinary --no-config pip install --python $pythonPath --index-url 'https://pypi.org/simple' -r (Join-Path $sourceDirectory 'requirements.txt') 'mkl==2023.1.0' 'intel-openmp==2023.1.0' 'tbb==2021.9.0' 'scikit-learn==1.7.2' 'joblib==1.5.3' 'threadpoolctl==3.6.0'
        if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Existing installations were preserved; retry to create a new environment.' }
        & $pythonPath (Join-Path $sourceDirectory 'desktop_environment_probe.py')
        if ($LASTEXITCODE -ne 0) { throw 'Environment verification failed. Review the diagnostic above. This environment was not selected.' }
        $receiptText = @{schema=1; python=$pythonPath; source=$sourceDirectory} | ConvertTo-Json
        $temporaryReceipt = Join-Path $runtimeRoot ('desktop-' + [Guid]::NewGuid().ToString('N') + '.json.tmp')
        Assert-OwnedPath $temporaryReceipt
        [IO.File]::WriteAllText($temporaryReceipt, $receiptText, [Text.UTF8Encoding]::new($false))
        if (Test-Path -LiteralPath $runtimeReceipt) {
            [IO.File]::Replace($temporaryReceipt, $runtimeReceipt, $null)
        } else {
            [IO.File]::Move($temporaryReceipt, $runtimeReceipt)
        }
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
