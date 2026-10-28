"""Exercise the source installer's real path guard without running the installer."""
import base64
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which('powershell.exe')
PRELUDE = r'''
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -ne 5) { throw 'Expected Windows PowerShell 5.1.' }
$tokens = $null
$parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile($env:ODS_SETUP_SCRIPT, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
$guards = @($ast.FindAll({ param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Assert-OwnedPath'
}, $false))
if ($guards.Count -ne 1) { throw 'Expected one Assert-OwnedPath definition.' }
# Evaluate only the production function. The installer's top-level code cannot run.
. ([scriptblock]::Create($guards[0].Extent.Text))
$fixture = [IO.Path]::GetFullPath($env:ODS_SETUP_TEST_ROOT)
$runtimeRoot = Join-Path $fixture 'managed'
[void](New-Item -ItemType Directory -Path $runtimeRoot)
function Assert-Rejected([string]$Path, [string]$Reason) {
    $failure = $null
    try { Assert-OwnedPath $Path } catch { $failure = $_.Exception.Message }
    if (-not $failure -or -not $failure.Contains($Reason)) {
        throw ('Expected rejection containing ' + $Reason + '; got: ' + $failure)
    }
}
'''


@unittest.skipUnless(os.name == 'nt' and POWERSHELL, 'Requires Windows PowerShell 5.1.')
class WindowsSourceSetupPathTests(unittest.TestCase):
    def run_guard(self, body):
        # Every writable fixture belongs to this checkout; never touch AppData or
        # invoke uv, downloads, dependency installation, or application startup.
        with tempfile.TemporaryDirectory(prefix='ods-setup-path-', dir=SOURCE) as folder:
            fixture = Path(folder).resolve()
            self.assertEqual(fixture.parent, SOURCE.resolve())
            environment = dict(os.environ, ODS_SETUP_SCRIPT=str(SOURCE/'setup_windows.ps1'),
                               ODS_SETUP_TEST_ROOT=str(fixture))
            encoded = base64.b64encode((PRELUDE + body).encode('utf-16-le')).decode('ascii')
            result = subprocess.run([POWERSHELL, '-NoProfile', '-NonInteractive',
                                     '-EncodedCommand', encoded], env=environment,
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + '\n' + result.stderr)

    def test_hidden_ancestor_allows_existing_and_new_owned_paths(self):
        self.run_guard(r'''
$hiddenParent = Get-Item -LiteralPath $fixture -Force
$oldAttributes = $hiddenParent.Attributes
try {
    $hiddenParent.Attributes = $oldAttributes -bor [IO.FileAttributes]::Hidden
    if (-not ((Get-Item -LiteralPath $fixture -Force).Attributes -band [IO.FileAttributes]::Hidden)) {
        throw 'The regression fixture must have a real Hidden attribute.'
    }
    $existing = Join-Path $runtimeRoot 'python.exe'
    [IO.File]::WriteAllText($existing, '')
    Assert-OwnedPath $runtimeRoot
    Assert-OwnedPath $existing
    Assert-OwnedPath (Join-Path $runtimeRoot 'new\Scripts\python.exe')
} finally {
    (Get-Item -LiteralPath $fixture -Force).Attributes = $oldAttributes
}
''')

    def test_outside_root_and_same_prefix_sibling_are_rejected(self):
        self.run_guard(r'''
Assert-Rejected (Join-Path $runtimeRoot '..\outside\python.exe') 'outside its managed directory'
Assert-Rejected ($runtimeRoot + '-sibling\python.exe') 'outside its managed directory'
''')

    def test_junction_ancestor_is_rejected_even_when_hidden(self):
        self.run_guard(r'''
$target = Join-Path $fixture 'unrelated'
[void](New-Item -ItemType Directory -Path $target)
$sentinel = Join-Path $target 'keep.txt'
[IO.File]::WriteAllText($sentinel, 'unrelated data')
$junction = Join-Path $runtimeRoot 'linked'
try {
    [void](New-Item -ItemType Junction -Path $junction -Target $target)
    $attributes = (Get-Item -LiteralPath $junction -Force).Attributes
    if (-not ($attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Expected a real junction.' }
    Assert-Rejected (Join-Path $junction 'Scripts\python.exe') 'links or junctions'
    (Get-Item -LiteralPath $junction -Force).Attributes = $attributes -bor [IO.FileAttributes]::Hidden
    if (-not ((Get-Item -LiteralPath $junction -Force).Attributes -band [IO.FileAttributes]::Hidden)) {
        throw 'The junction fixture must have a real Hidden attribute.'
    }
    Assert-Rejected (Join-Path $junction 'Scripts\python.exe') 'links or junctions'
} finally {
    # Delete the exact junction itself, never recurse into its target. Its path
    # is fixed beneath the already verified temporary fixture.
    $link = Get-Item -LiteralPath $junction -Force -ErrorAction SilentlyContinue
    if ($link -and ($link.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        [IO.Directory]::Delete($junction, $false)
    }
}
if ([IO.File]::ReadAllText($sentinel) -ne 'unrelated data') { throw 'Junction target was changed.' }
''')


if __name__ == '__main__':
    unittest.main()