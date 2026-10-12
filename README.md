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
- **Clearer SD card errors.** It says when MSET9 is still set up instead of only failing to find a folder, stops before writing anything when other folders sit next to the console folder (save3ds_fuse could update the wrong one) and says which one to keep, and explains when save3ds_fuse can't be started (usually antivirus).
- **custom-install-finalize keeps going** when one title fails, and keeps the unfinished ones in cifinish.bin so you can run it again. These finalize changes are in the source only; the bundled `custom-install-finalize.3dsx` is still the original until I've tested the new one on a 3DS.

None of this has been run on a real 3DS yet. It passes an automated test suite and the finalize program builds cleanly, but that's all. If you try it, I'd like to hear how it went in this fork's issues.

The pip commands below install this fork, not the original.

The fixes were made with Claude (Anthropic) doing the code reading and the changes, and every change was checked by tests and a separate review.


## Summary

### Windows standalone

Download `custom-install-standalone.zip` from the releases page of this fork, unzip it, and run `ci-gui.exe`. Python is bundled, so there is nothing else to install. The original project's old 2.1 build on its releases page doesn't have these fixes.

Put `boot9.bin`, `seeddb.bin` and `movable.sed` in the same folder as `ci-gui.exe` and the GUI picks them up on its own. `ci-gui-console.exe` is the same program with a console window that shows errors, and `custominstall.exe` is the command-line version.

### With installed Python

> [!NOTE]
> Windows users: Enabling "Add Python 3.X to PATH" is **NOT** required! Python is installed with the `py` launcher by default.

1. [Dump boot9.bin and movable.sed](https://ihaveamac.github.io/dump.html) from a 3DS system.
2. Install the packages:
  * Windows: `py -3 -m pip install --user --upgrade https://github.com/Akoi89/custom-install/archive/refs/heads/fix/install-safety.zip`
  * macOS/Linux: `python3 -m pip install --user --upgrade https://github.com/Akoi89/custom-install/archive/refs/heads/fix/install-safety.zip`

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

This needs 64-bit Windows Python 3 (the python.org installer, with its default tcl/tk), the x86 Visual C++ redistributable (its `vcruntime140.dll` goes next to the 32-bit save3ds_fuse) and PowerShell. From the repo folder:

```
powershell -ExecutionPolicy Bypass -File standalone\make-standalone.ps1
```

It makes a virtual environment in `build\standalone-venv`, installs cx_Freeze and this package's dependencies into it, freezes the three exes from this folder into `build\custom-install-standalone`, and zips that folder to `dist\custom-install-standalone.zip`. Pass `-Venv <folder>` to use another environment. `standalone\setup-cxfreeze.py` is the cx_Freeze script it runs.

## Troubleshooting

- **"MSET9 is still set up on this SD card"**: Run the MSET9 script again and choose "5. Remove MSET9", then try again. The original custom-install reports this as "Could not find a suitable id1 directory".
- **"Could not find a suitable id1 directory"**: The folder that holds this console's data on the SD card is missing or was renamed. If you or a tool renamed it, rename it back first, because installing into a fresh folder would hide the games already on the card. If the folder was deleted rather than renamed, put the card in the 3DS and turn it on once, then retry.
- **"... is the folder this console uses, but ... also holds: ..."**: The folder named first is the one in use. Move the other folders it lists out of that folder (to your PC, for example), then try again. save3ds_fuse, which updates the title database, uses whichever folder it finds first, so it could write to the wrong one while they're there.
- **"There are multiple id1 directories"**: None or more than one of them has a title database, so I can't tell which one is in use. Put the card in the 3DS, check that your games show up, then back up the folders that aren't in use and remove them.
- **"boot9 is no longer at ...", "movable.sed is no longer at ..." or "movable.sed can't be found at ..."**: The file was on a card or drive that was removed or got a different drive letter after you chose it (or before you pressed Start). Choose it again in the boot9 or movable.sed box, then press Start. On the command line, pass the right path with `-b` or `-m`. Files you put next to `ci-gui.exe` are only picked up when custom-install starts, so restart it after adding them. The original custom-install shows "An error occurred when trying to run save3ds_fuse" in this case, with an error such as "The system cannot find the path specified" (or "cannot find the file specified") in the console.
- **"... doesn't look like a boot9 dump (wrong size)"**: The file in the boot9 box is not a boot9 dump. Choose the boot9.bin or boot9_prot.bin you dumped from your 3DS.
- **"Access is denied" or "Couldn't run save3ds_fuse"**: Antivirus or security software is probably blocking save3ds_fuse. On macOS and Linux, make sure the file is executable (`chmod +x`).
- **WinError 1117 or other I/O errors while writing**: This points to a fault with the SD card or the card reader. Test the card (H2testw on Windows, F3 on macOS and Linux) and try another reader.
- **"CIFINISH magic not found", or custom-install-finalize showing up as unknown homebrew**: The file system on the SD card is probably damaged, often from removing the card without ejecting it. Check the card, delete `cifinish.bin` from it, and run custom-install again.
- **"0xc000007b" when starting ci-gui**: That's the original project's old 2.1 standalone build. Use this fork's standalone zip or the Python install instead.
- **"Failed to finish ticket install: d8e08019" in custom-install-finalize**: I haven't confirmed the cause. One report links it to a game made only for the New 3DS being installed on an older model.

## License/Credits
[save3ds by wwylele](https://github.com/wwylele/save3ds) is used to interact with the Title Database (details in `bin/README`).

Thanks to @nek0bit for redesigning `custominstall.py` to work as a module, and for implementing an earlier GUI.

Thanks to @LyfeOnEdge from the [brewtools Discord](https://brewtools.dev) for designing the second version of the GUI. Special thanks to CrafterPika and archbox for testing.

Thanks to @BpyH64 for [researching how to generate the cmacs](https://github.com/d0k3/GodMode9/issues/340#issuecomment-487916606).
