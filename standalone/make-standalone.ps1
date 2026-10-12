# Builds the Windows standalone: build\custom-install-standalone, zipped to dist\custom-install-standalone.zip
# Run from anywhere:  powershell -ExecutionPolicy Bypass -File standalone\make-standalone.ps1
# -Venv  folder of the build venv (made with the newest "py -3" if it doesn't exist yet)
param(
    [string]$Venv = ''
)
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
if (-not $Venv) { $Venv = Join-Path $root 'build\standalone-venv' }
$py = Join-Path $Venv 'Scripts\python.exe'
$outDir = Join-Path $root 'build\custom-install-standalone'
$zip = Join-Path $root 'dist\custom-install-standalone.zip'

function Run($exe, $argList) {
    & $exe @argList
    if ($LASTEXITCODE -ne 0) { throw "failed ($LASTEXITCODE): $exe $argList" }
}

# save3ds_fuse.exe is a 32-bit program, so it needs the 32-bit C runtime next to it (the one cx_Freeze bundles
# for the exes is 64-bit). It comes from this PC's x86 Visual C++ redistributable.
$vcruntimeX86 = Join-Path $env:SystemRoot 'SysWOW64\vcruntime140.dll'
if (-not (Test-Path $vcruntimeX86)) { throw "$vcruntimeX86 is missing, install the x86 Visual C++ redistributable" }

if (-not (Test-Path $py)) {
    Run 'py' @('-3', '-m', 'venv', $Venv)
}
Run $py @('-c', 'import struct, sys; sys.exit(struct.calcsize(''P'') != 8 and ''64-bit Python is needed'')')

# cx_Freeze plus the package's dependencies, but not the package itself: setup-cxfreeze.py freezes this
# working tree, and an installed copy would bring its pip metadata (with this folder's path) into the build
Run $py @('-m', 'pip', 'install', '--upgrade', 'cx_Freeze==8.7.1', 'pyctr>=0.7.6,<0.9', 'events>=0.4',
          'comtypes>=1.4.12', 'setuptools>=61.0.0')
# an older build script installed the package into this venv, so take it out if it's there
Run $py @('-I', '-c', 'import importlib.metadata as m, subprocess, sys; names = {d.metadata[''Name''].lower() for d in m.distributions()}; ''custominstall'' in names and subprocess.check_call([sys.executable, ''-m'', ''pip'', ''uninstall'', ''-y'', ''-q'', ''custominstall''])')
Run $py @('-m', 'pip', 'show', 'cx_Freeze')

if (Test-Path $outDir) { Remove-Item -Recurse -Force $outDir }
if (Test-Path $zip) { Remove-Item -Force $zip }
New-Item -ItemType Directory -Force (Join-Path $root 'dist') | Out-Null

# setuptools works in the current folder, so run it from the repo folder
Push-Location $root
try {
    Run $py @((Join-Path $PSScriptRoot 'setup-cxfreeze.py'), 'build_exe', "--build-exe=$outDir", '--silent')
} finally {
    Pop-Location
}

# cx_Freeze also copies the package's data files into lib\custominstall. The program uses the copies next to
# the exe, so remove the duplicates (about 4.5 MB) to keep one copy of each.
$pkgDir = Join-Path $outDir 'lib\custominstall'
foreach ($name in 'TaskbarLib.tlb', 'title.db.gz', 'custom-install-finalize.3dsx', 'bin') {
    Remove-Item -Recurse -Force (Join-Path $pkgDir $name)
}
# copied here because cx_Freeze leaves out files from Windows system folders
Copy-Item $vcruntimeX86 (Join-Path $outDir 'bin\vcruntime140.dll')

# the zip holds one top-level folder, custom-install-standalone
Push-Location (Join-Path $root 'build')
try {
    Run $py @('-m', 'zipfile', '-c', $zip, 'custom-install-standalone')
} finally {
    Pop-Location
}
Write-Output "Built $zip"
Get-FileHash $zip -Algorithm SHA256 | Format-List Hash, Path
