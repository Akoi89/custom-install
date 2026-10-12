r"""cx_Freeze setup for the Windows standalone build. Run it through make-standalone.ps1, which also
zips the result. By hand, from the repo folder:
python standalone\setup-cxfreeze.py build_exe --build-exe=build\custom-install-standalone
"""
import sys
from importlib import metadata
from os.path import abspath, dirname, isfile, join

from cx_Freeze import setup, Executable

HERE = dirname(abspath(__file__))
ROOT = dirname(HERE)

# build from this working tree, not from whatever copy of custominstall is installed in the venv
sys.path.insert(0, ROOT)
from custominstall import __version__  # noqa: E402

PKG = join(ROOT, 'custominstall')

# the code looks for these next to the exe (and bin\ for save3ds_fuse), not inside library.zip
include_files = [
    (join(PKG, 'TaskbarLib.tlb'), 'TaskbarLib.tlb'),
    (join(PKG, 'bin', 'win32', 'save3ds_fuse.exe'), join('bin', 'save3ds_fuse.exe')),
    (join(PKG, 'bin', 'README'), join('bin', 'README')),
    (join(PKG, 'custom-install-finalize.3dsx'), 'custom-install-finalize.3dsx'),
    (join(PKG, 'title.db.gz'), 'title.db.gz'),
    (join(ROOT, 'extras', 'windows-quickstart.txt'), 'windows-quickstart.txt'),
    (join(ROOT, 'LICENSE.md'), 'LICENSE.md'),
]

# licences: the bundled Python (from the Python install that runs the build), save3ds and the Python packages
# (cx_Freeze adds the Visual C++ one to share\licenses\vc_redist and the Tcl/Tk one to share\tk8.6)
share_dir = join('share', 'licenses')
python_license = join(sys.base_prefix, 'LICENSE.txt')
if isfile(python_license):
    include_files.append((python_license, join(share_dir, 'python', 'LICENSE.txt')))
include_files.append(
    (join(HERE, 'licenses', 'save3ds-LICENSE-MIT.txt'), join(share_dir, 'save3ds', 'LICENSE-MIT.txt')))
# the bundled Python packages, from their installed metadata
for dist_name in ('pyctr', 'events', 'pycryptodomex', 'comtypes'):
    license_files = [f for f in metadata.distribution(dist_name).files or []
                     if f.name.lower().startswith(('license', 'copying'))]
    if not license_files:
        sys.exit(f'no licence file found for {dist_name}')
    for f in license_files:
        include_files.append((str(f.locate()), join(share_dir, dist_name, f.name)))

gui_script = join(HERE, 'ci-gui.py')
cli_script = join(HERE, 'custominstall-cli.py')

executables = [
    Executable(gui_script, target_name='ci-gui-console', base='console'),
    Executable(gui_script, target_name='ci-gui', base='gui'),
    Executable(cli_script, target_name='custominstall', base='console'),
]

setup(
    name='ci-gui',
    version=__version__,
    description='Installs a title directly to an SD card for the Nintendo 3DS',
    options={
        'build_exe': {
            'packages': ['pyctr', 'events', 'Cryptodome', 'tkinter', 'comtypes'],
            'excludes': ['Cryptodome.SelfTest'],
            'include_files': include_files,
            # bundle the Microsoft C runtime (vcruntime140.dll and friends), so it runs on a PC
            # without the Visual C++ redistributable
            'include_msvcr': True,
            # keep the build machine's folders out of the compiled code (tracebacks show bare file names)
            'replace_paths': [('*', '')],
        },
    },
    executables=executables,
)
