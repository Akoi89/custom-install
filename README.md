# custom-install
Installs a title directly to an SD card for the Nintendo 3DS. Originally created late June 2019.

> [!IMPORTANT]
> **This is an unofficial fork** of [ihaveamac/custom-install](https://github.com/ihaveamac/custom-install). It fixes bugs that could delete or lose installed titles, plus a few smaller ones. These changes aren't part of the original project and its author doesn't support them, so please report problems with this fork here, not upstream.

What's different in this fork:

- **"Skip contents" no longer wipes the game.** Ticking it (or `--skip-contents`) used to delete an installed title's files and save and put an empty folder in their place.
- **A missing seed no longer crashes the command line version.** A newer game whose seed isn't in your seeddb.bin is skipped with a message to update it, and the rest carry on.
- **Reinstalling is safer.** The old copy is moved aside and only deleted once the new one is in place, so a crash or a pulled SD card midway doesn't leave you with nothing.
- **One bad title doesn't stop the batch.** The rest still install and finalize still gets copied to the SD card. A title whose database entry couldn't be added is no longer slipped in by the next title while being reported as failed.
- **The GUI doesn't get stuck with every button greyed out** after a wrong movable.sed or SD card. The command line gives a proper error and exit code instead of a Python crash.
- **custom-install-finalize keeps going** when one title fails, and keeps the unfinished ones in cifinish.bin so you can run it again. These finalize changes are in the source only; the bundled `custom-install-finalize.3dsx` is still the original until I've tested the new one on a 3DS.

None of this has been run on a real 3DS yet. It passes an automated test suite and the finalize program builds cleanly, but that's all. If you try it, I'd like to hear how it went in this fork's issues.

To install this fork instead of the original, use this link in the pip commands below: `https://github.com/Akoi89/custom-install/archive/refs/heads/fix/install-safety.zip`

The fixes were made with Claude (Anthropic) doing the code reading and the changes, and every change was checked by tests and a separate review.


## Summary

### Windows standalone

1. [Dump boot9.bin and movable.sed](https://wiki.hacks.guide/wiki/3DS:Dump_system_files) from a 3DS system.
2. Download the [latest releases](https://github.com/ihaveamac/custom-install/releases).
3. Extract and run ci-gui. Read `windows-quickstart.txt`.

### With installed Python

> [!NOTE]
> Windows users: Enabling "Add Python 3.X to PATH" is **NOT** required! Python is installed with the `py` launcher by default.

1. [Dump boot9.bin and movable.sed](https://ihaveamac.github.io/dump.html) from a 3DS system.
2. Install the packages:
  * Windows: `py -3 -m pip install --user --upgrade https://github.com/ihaveamac/custom-install/archive/refs/heads/python-package.zip`
  * macOS/Linux: `python3 -m pip install --user --upgrade https://github.com/ihaveamac/custom-install/archive/refs/heads/python-package.zip`

To run the GUI:
* Windows: `py -3 -m custominstall.gui`
* macOS/Linux: `python3 -m custominstall.gui`

To run the command line version:
* Windows: `py -3 -m custominstall`
* macOS/Linux: `python3 -m custominstall`

## Setup
Linux users must build [wwylele/save3ds](https://github.com/wwylele/save3ds) and place `save3ds_fuse` in one of these places:
* A directory in `PATH`
* In `custominstall/bin/linux`
* Set the environment variable `CUSTOM_INSTALL_SAVE3DS_PATH` to the `save3ds_fuse` binary

movable.sed is required and can be provided with `-m` or `--movable`.

boot9 is needed:
* `-b` or `--boot9` argument (if set)
* `BOOT9_PATH` environment variable (if set)
* `%APPDATA%\3ds\boot9.bin` (Windows-specific)
* `~/Library/Application Support/3ds/boot9.bin` (macOS-specific)
* `~/.3ds/boot9.bin`
* `~/3ds/boot9.bin`

A [SeedDB](https://github.com/ihaveamac/3DS-rom-tools/wiki/SeedDB-list) is needed for newer games (2015+) that use seeds.  
SeedDB is checked in order of:
* `-s` or `--seeddb` argument (if set)
* `SEEDDB_PATH` environment variable (if set)
* `%APPDATA%\3ds\seeddb.bin` (Windows-specific)
* `~/Library/Application Support/3ds/seeddb.bin` (macOS-specific)
* `~/.3ds/seeddb.bin`
* `~/3ds/seeddb.bin`

## custom-install-finalize
custom-install-finalize installs a ticket, plus a seed if required. This is required for the title to appear and function.

This can be built as most 3DS homebrew projects [with devkitARM](https://www.3dbrew.org/wiki/Setting_up_Development_Environment).

## Usage
Use `-h` to view arguments.

Examples:
```
py -3 -m custominstall -b boot9.bin -m movable.sed --sd E:\ file.cia file2.cia
python3 -m custominstall -b boot9.bin -m movable.sed --sd /Volumes/GM9SD file.cia file2.cia
python3 -m custominstall -b boot9.bin -m movable.sed --sd /media/GM9SD file.cia file2.cia
```

## GUI
A GUI is provided to make the process easier.

### GUI Setup
Linux users may need to install a Tk package:
* Ubuntu/Debian: `sudo apt install python3-tk`
* Arch: `sudo pacman -S tk`
* Fedora: `sudo dnf install python3-tkinter`

## Development

### Building Windows standalone

> [!WARNING]
> This section is OUTDATED and currently does not work with the Python package setup.

## License/Credits
[save3ds by wwylele](https://github.com/wwylele/save3ds) is used to interact with the Title Database (details in `bin/README`).

Thanks to @nek0bit for redesigning `custominstall.py` to work as a module, and for implementing an earlier GUI.

Thanks to @LyfeOnEdge from the [brewtools Discord](https://brewtools.dev) for designing the second version of the GUI. Special thanks to CrafterPika and archbox for testing.

Thanks to @BpyH64 for [researching how to generate the cmacs](https://github.com/d0k3/GodMode9/issues/340#issuecomment-487916606).
