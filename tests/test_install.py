import io
import os
import sys
from hashlib import sha256
from types import SimpleNamespace

import pytest
from events import Events

from pyctr.crypto import MissingSeedError

from custominstall import __main__ as ci

ID0 = bytes(range(16))
ID1 = '11' * 16
TID_A = '0004000000012345'
TID_B = '0004000000054321'


# ---------------------------------------------------------------------------
# cifinish (T1)

def v1_entry(tid, has_seed, seed):
    # title id, common key index, has seed, magic, title key, seed
    return (tid.to_bytes(8, 'little') + b'\0' + bytes([has_seed]) + b'TITLE\0' + b'\xaa' * 0x10 + seed)


def v2_entry(tid, has_seed, seed):
    # magic, title id, has seed, padding, seed
    return b'TITLE\0' + tid.to_bytes(8, 'little') + bytes([has_seed]) + b'\0' + seed


def cifinish_header(version, count, magic=b'CIFINISH'):
    return magic + version.to_bytes(4, 'little') + count.to_bytes(4, 'little')


def test_cifinish_round_trip(tmp_path):
    path = tmp_path / 'cifinish.bin'
    data = {
        0x0004000000012345: {'seed': None},
        0x0004000000054321: {'seed': bytes(range(0x10))},
    }
    ci.save_cifinish(path, data)
    assert path.read_bytes()[:8] == b'CIFINISH'
    assert ci.load_cifinish(path) == data


def test_cifinish_missing_file_is_empty(tmp_path):
    assert ci.load_cifinish(tmp_path / 'nope.bin') == {}


def test_cifinish_v1(tmp_path):
    path = tmp_path / 'cifinish.bin'
    seed = b'\x42' * 0x10
    path.write_bytes(cifinish_header(1, 2) + v1_entry(0x1111, 0, b'\0' * 0x10) + v1_entry(0x2222, 1, seed))
    assert ci.load_cifinish(path) == {0x1111: {'seed': None}, 0x2222: {'seed': seed}}


def test_cifinish_v2(tmp_path):
    path = tmp_path / 'cifinish.bin'
    seed = b'\x24' * 0x10
    path.write_bytes(cifinish_header(2, 2) + v2_entry(0x1111, 0, b'\0' * 0x10) + v2_entry(0x2222, 1, seed))
    assert ci.load_cifinish(path) == {0x1111: {'seed': None}, 0x2222: {'seed': seed}}


def test_cifinish_bad_magic(tmp_path):
    path = tmp_path / 'cifinish.bin'
    path.write_bytes(cifinish_header(3, 0, magic=b'NOTRIGHT'))
    with pytest.raises(ci.InvalidCIFinishError):
        ci.load_cifinish(path)


def test_cifinish_truncated_entry(tmp_path):
    path = tmp_path / 'cifinish.bin'
    path.write_bytes(cifinish_header(2, 1) + b'TITLE\0')
    with pytest.raises(ci.InvalidCIFinishError):
        ci.load_cifinish(path)


# ---------------------------------------------------------------------------
# replace_title_dir (T2)

def make_dir(path, name, content):
    path.mkdir(parents=True)
    (path / name).write_bytes(content)


def test_replace_title_dir_success(tmp_path):
    new_root = tmp_path / 'new'
    title_root = tmp_path / 'title'
    backup_root = tmp_path / 'backup'
    make_dir(new_root, 'new.app', b'new')
    make_dir(title_root, 'old.app', b'old')

    ci.replace_title_dir(str(new_root), str(title_root), str(backup_root))

    assert (title_root / 'new.app').read_bytes() == b'new'
    assert not (title_root / 'old.app').exists()
    assert not new_root.exists()
    assert not backup_root.exists()


def test_replace_title_dir_without_existing_title(tmp_path):
    new_root = tmp_path / 'new'
    title_root = tmp_path / 'title'
    make_dir(new_root, 'new.app', b'new')

    ci.replace_title_dir(str(new_root), str(title_root), str(tmp_path / 'backup'))

    assert (title_root / 'new.app').read_bytes() == b'new'
    assert not (tmp_path / 'backup').exists()


def test_replace_title_dir_restores_original_when_second_rename_fails(tmp_path, monkeypatch):
    new_root = tmp_path / 'new'
    title_root = tmp_path / 'title'
    backup_root = tmp_path / 'backup'
    make_dir(new_root, 'new.app', b'new')
    make_dir(title_root, 'old.app', b'old')

    real_rename = os.rename
    calls = []

    def flaky_rename(src, dst):
        calls.append((src, dst))
        # the first rename (title -> backup) works, the one moving the new title in fails
        if str(src) == str(new_root):
            raise OSError('simulated failure')
        real_rename(src, dst)

    monkeypatch.setattr(ci, 'rename', flaky_rename)

    with pytest.raises(OSError, match='simulated failure'):
        ci.replace_title_dir(str(new_root), str(title_root), str(backup_root))

    assert len(calls) == 3
    assert (title_root / 'old.app').read_bytes() == b'old'
    assert (new_root / 'new.app').read_bytes() == b'new'
    assert not backup_root.exists()


def test_replace_title_dir_says_where_the_original_is_when_rollback_fails(tmp_path, monkeypatch):
    new_root = tmp_path / 'new'
    title_root = tmp_path / 'title'
    backup_root = tmp_path / 'backup'
    make_dir(new_root, 'new.app', b'new')
    make_dir(title_root, 'old.app', b'old')

    real_rename = os.rename

    def failing_rename(src, dst):
        # only the first rename (title -> backup) works
        if str(src) != str(title_root):
            raise OSError('simulated failure')
        real_rename(src, dst)

    monkeypatch.setattr(ci, 'rename', failing_rename)

    with pytest.raises(OSError) as excinfo:
        ci.replace_title_dir(str(new_root), str(title_root), str(backup_root))

    assert str(backup_root) in str(excinfo.value)
    assert (backup_root / 'old.app').read_bytes() == b'old'


# ---------------------------------------------------------------------------
# fakes for start() and prepare_titles()

class FakeCipher:
    def encrypt(self, data):
        return data


class FakeCmac:
    def update(self, data):
        pass

    def digest(self):
        return b'\0' * 0x10


class FakeIO:
    def __init__(self, out):
        self.out = out

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def write(self, data):
        return self.out.write(data)

    def seek(self, pos):
        return self.out.seek(pos)


class FakeCrypto:
    def __init__(self, fail_iv_for=None):
        self.id0 = ID0
        self.b9_path = 'boot9.bin'
        self.fail_iv_for = fail_iv_for

    def sd_path_to_iv(self, path):
        if self.fail_iv_for and self.fail_iv_for in path:
            raise RuntimeError('simulated failure for ' + path)
        return b'\0' * 0x10

    def create_ctr_cipher(self, keyslot, iv):
        return FakeCipher()

    def create_ctr_io(self, keyslot, out, iv):
        return FakeIO(out)

    def create_cmac_object(self, keyslot):
        return FakeCmac()


class FakeTmd:
    def __init__(self, title_id, save_size=0):
        self.title_id = title_id
        self.save_size = save_size
        self.title_version = 0

    def __bytes__(self):
        return b'FAKETMD'


class FakeContent:
    def __init__(self, uses_seed=False, product_code='CTR-P-TEST'):
        self.flags = SimpleNamespace(uses_seed=uses_seed)
        self.program_id = '0004000000012345'
        self.version = 0
        self._product_code = product_code

    @property
    def product_code(self):
        if isinstance(self._product_code, Exception):
            raise self._product_code
        return self._product_code

    def open_raw_section(self, section):
        return io.BytesIO(b'\0' * 0x400)


class FakeReader:
    def __init__(self, title_id, data=b'content data', uses_seed=False, product_code='CTR-P-TEST'):
        self.tmd = FakeTmd(title_id)
        self.data = data
        record = SimpleNamespace(id='00000000', cindex=0, size=len(data), hash=sha256(data).digest())
        self.content_info = [record]
        self.contents = {0: FakeContent(uses_seed, product_code)}

    def open_raw_section(self, cindex):
        return io.BytesIO(self.data)


class FakeRun:
    returncode = 0
    stdout = ''
    args = []


# start() needs the full 64 KiB boot9.bin that save3ds_fuse reads, so the fake one has that size
BOOT9_DATA = b'boot9'.ljust(0x10000, b'\0')


def make_sd(tmp_path):
    sd = tmp_path / 'sd'
    id1_root = sd / 'Nintendo 3DS' / ID0.hex() / ID1
    (id1_root / 'dbs').mkdir(parents=True)
    (id1_root / 'dbs' / 'title.db').write_bytes(b'not a real database')
    return sd, id1_root


def make_installer(sd, readers, skip_contents, crypto=None):
    installer = object.__new__(ci.CustomInstall)
    installer.event = Events()
    installer.log_lines = []
    installer.crypto = crypto or FakeCrypto()
    installer.seeddb = None
    installer.readers = [(r, f'{r.tmd.title_id}.cia') for r in readers]
    installer.sd = str(sd)
    installer.skip_contents = skip_contents
    installer.overwrite_saves = False
    installer.cifinish_out = None
    # start() checks that these exist and gives save3ds_fuse copies of them
    keys = sd.parent / 'keys'
    keys.mkdir(exist_ok=True)
    (keys / 'boot9.bin').write_bytes(BOOT9_DATA)
    (keys / 'movable.sed').write_bytes(b'movable')
    installer.crypto.b9_path = str(keys / 'boot9.bin')
    installer.boot9 = installer.crypto.b9_path
    installer.movable = str(keys / 'movable.sed')
    return installer


@pytest.fixture
def fake_tools(tmp_path, monkeypatch):
    fuse = tmp_path / 'save3ds_fuse'
    fuse.write_bytes(b'')
    monkeypatch.setattr(ci, 'save3ds_fuse_path', str(fuse))
    monkeypatch.setattr(ci.subprocess, 'run', lambda *args, **kwargs: FakeRun())


# ---------------------------------------------------------------------------
# skip_contents (T3)

def test_skip_contents_keeps_existing_title(tmp_path, fake_tools):
    sd, id1_root = make_sd(tmp_path)
    content = id1_root / 'title' / '00040000' / '00012345' / 'content'
    content.mkdir(parents=True)
    (content / 'x.app').write_bytes(b'existing')

    installer = make_installer(sd, [FakeReader(TID_A)], skip_contents=True)
    result, _, _ = installer.start()

    assert (content / 'x.app').read_bytes() == b'existing'
    assert result['installed'] and not result['failed']
    assert [d.name for d in os.scandir(sd) if d.name.startswith('ci-install-')] == []
    assert int(TID_A, 16) in ci.load_cifinish(sd / 'cifinish.bin')


def test_install_replaces_existing_title(tmp_path, fake_tools):
    sd, id1_root = make_sd(tmp_path)
    content = id1_root / 'title' / '00040000' / '00012345' / 'content'
    content.mkdir(parents=True)
    (content / 'x.app').write_bytes(b'existing')

    installer = make_installer(sd, [FakeReader(TID_A)], skip_contents=False)
    result, _, _ = installer.start()

    assert result['installed'] and not result['failed']
    assert not (content / 'x.app').exists()
    assert (content / '00000000.app').is_file()
    assert [d.name for d in os.scandir(sd) if d.name.startswith('ci-install-')] == []


def test_leftover_folders_are_reported_and_kept(tmp_path, fake_tools):
    sd, _ = make_sd(tmp_path)
    (sd / 'ci-install-old-0004000000012345-deadbeef').mkdir()
    (sd / 'ci-install-temp-0004000000012345-deadbeef').mkdir()

    installer = make_installer(sd, [], skip_contents=False)
    installer.start()

    assert (sd / 'ci-install-old-0004000000012345-deadbeef').is_dir()
    assert (sd / 'ci-install-temp-0004000000012345-deadbeef').is_dir()
    assert any('ci-install-old-0004000000012345-deadbeef' in l for l in installer.log_lines)


# ---------------------------------------------------------------------------
# one title failing (T4)

def test_failed_title_does_not_stop_the_batch(tmp_path, fake_tools):
    sd, _ = make_sd(tmp_path)
    readers = [FakeReader(TID_A, product_code=RuntimeError('simulated failure')), FakeReader(TID_B)]

    installer = make_installer(sd, readers, skip_contents=True)
    result, _, _ = installer.start()

    assert len(result['failed']) == 1 and TID_A in result['failed'][0]
    assert len(result['installed']) == 1 and TID_B in result['installed'][0]
    assert any('simulated failure' in l for l in installer.log_lines)


def test_failed_title_temp_folder_is_removed(tmp_path, fake_tools):
    sd, id1_root = make_sd(tmp_path)
    readers = [FakeReader(TID_A), FakeReader(TID_B)]

    # the first title fails while writing, the second one is fine
    installer = make_installer(sd, readers, skip_contents=False, crypto=FakeCrypto(fail_iv_for=TID_A[8:]))
    result, _, _ = installer.start()

    assert len(result['failed']) == 1 and TID_A in result['failed'][0]
    assert len(result['installed']) == 1 and TID_B in result['installed'][0]
    assert [d.name for d in os.scandir(sd) if d.name.startswith('ci-install-')] == []
    assert not (id1_root / 'title' / '00040000' / '00012345').exists()
    assert (id1_root / 'title' / '00040000' / '00054321' / 'content' / '00000000.app').is_file()


def test_failed_database_import_is_not_imported_with_the_next_title(tmp_path, monkeypatch):
    sd, _ = make_sd(tmp_path)
    fuse = tmp_path / 'save3ds_fuse'
    fuse.write_bytes(b'')
    monkeypatch.setattr(ci, 'save3ds_fuse_path', str(fuse))

    import_listings = []

    def fake_run(args, **kwargs):
        run = FakeRun()
        run.args = args
        if '-i' in args:
            # the directory given to save3ds_fuse is the last argument before the mode
            import_listings.append(sorted(os.listdir(args[-2])))
            run.returncode = 1 if len(import_listings) == 1 else 0
        return run

    monkeypatch.setattr(ci.subprocess, 'run', fake_run)

    installer = make_installer(sd, [FakeReader(TID_A), FakeReader(TID_B)], skip_contents=True)
    result, _, _ = installer.start()

    assert len(result['failed']) == 1 and TID_A in result['failed'][0]
    assert len(result['installed']) == 1 and TID_B in result['installed'][0]
    assert import_listings == [[TID_A], [TID_B]]


OTHER_TID = '0004000000077777'


def run_with_existing_database(tmp_path, monkeypatch, first_import, prepare=None):
    """Installs TID_A then TID_B where the extracted database already holds TID_A and another title.
    first_import is called for the first -i and may raise or return the return code.
    prepare, if given, is called with the installer and the imports list before the install starts."""
    sd, _ = make_sd(tmp_path)
    fuse = tmp_path / 'save3ds_fuse'
    fuse.write_bytes(b'')
    monkeypatch.setattr(ci, 'save3ds_fuse_path', str(fuse))

    imports = []

    def fake_run(args, **kwargs):
        run = FakeRun()
        run.args = args
        directory = args[-2]
        if '-x' in args:
            with open(os.path.join(directory, TID_A), 'wb') as o:
                o.write(b'OLD-A')
            with open(os.path.join(directory, OTHER_TID), 'wb') as o:
                o.write(b'OTHER')
        if '-i' in args:
            imports.append({name: open(os.path.join(directory, name), 'rb').read()
                            for name in os.listdir(directory)})
            if len(imports) == 1:
                run.returncode = first_import()
        return run

    monkeypatch.setattr(ci.subprocess, 'run', fake_run)

    installer = make_installer(sd, [FakeReader(TID_A), FakeReader(TID_B)], skip_contents=True)
    if prepare:
        prepare(installer, imports)
    result, _, application_count = installer.start()
    return result, application_count, imports


def test_failed_import_keeps_the_existing_entry_of_that_title(tmp_path, monkeypatch):
    result, application_count, imports = run_with_existing_database(tmp_path, monkeypatch, lambda: 1)

    assert len(result['failed']) == 1 and TID_A in result['failed'][0]
    assert len(result['installed']) == 1 and TID_B in result['installed'][0]
    # the second import still has the original entry for the title that failed, and the unrelated one
    assert imports[1][TID_A] == b'OLD-A'
    assert imports[1][OTHER_TID] == b'OTHER'
    assert TID_B in imports[1]
    assert application_count == 3


def test_exception_during_import_keeps_the_existing_entry_of_that_title(tmp_path, monkeypatch):
    def raise_error():
        raise UnicodeDecodeError('utf-8', b'\xff', 0, 1, 'invalid start byte')

    result, application_count, imports = run_with_existing_database(tmp_path, monkeypatch, raise_error)

    assert len(result['failed']) == 1 and TID_A in result['failed'][0]
    assert len(result['installed']) == 1 and TID_B in result['installed'][0]
    assert imports[1][TID_A] == b'OLD-A'
    assert imports[1][OTHER_TID] == b'OTHER'
    assert application_count == 3


def test_unreadable_existing_entry_is_not_removed(tmp_path, monkeypatch):
    real_open = open
    locked = [True]

    def prepare(installer, imports):
        def fake_open(path, mode='r', *args, **kwargs):
            # the old entry in the extracted database can't be read once, e.g. locked by another program
            if str(path).endswith(TID_A) and mode == 'rb' and locked[0]:
                locked[0] = False
                raise PermissionError('locked')
            return real_open(path, mode, *args, **kwargs)
        monkeypatch.setattr('builtins.open', fake_open)

    result, application_count, imports = run_with_existing_database(tmp_path, monkeypatch, lambda: 0, prepare)

    assert len(result['failed']) == 1 and TID_A in result['failed'][0]
    # the failed read happens before the entry is written, so the original stays for the next import
    assert imports[0][TID_A] == b'OLD-A'
    assert imports[0][OTHER_TID] == b'OTHER'
    assert application_count == 3


def test_entry_is_kept_after_a_successful_import_even_if_a_handler_raises(tmp_path, monkeypatch):
    def prepare(installer, imports):
        def raise_once(path, status):
            if status == ci.InstallStatus.Done and len(imports) == 1:
                raise RuntimeError('handler')
        installer.event.update_status += raise_once

    result, application_count, imports = run_with_existing_database(tmp_path, monkeypatch, lambda: 0, prepare)

    # the first import succeeded, so the new entry must not be swapped back for the old one
    assert imports[1][TID_A] != b'OLD-A'
    assert application_count == 3
    # and the title is reported once, as installed
    assert len(result['installed']) == 2
    assert result['failed'] == []


# ---------------------------------------------------------------------------
# seeds (T5)

def test_prepare_titles_skips_missing_seed(monkeypatch):
    # opening a reader looks up the seed, so a missing one raises from get_reader
    readers = {
        'seed_present.cia': FakeReader(TID_B, uses_seed=True),
        'no_seed.cia': FakeReader('0004000000099999'),
    }

    def fake_get_reader(path):
        if path == 'seed_missing.cia':
            raise MissingSeedError('missing')
        return readers[path]

    monkeypatch.setattr(ci.CustomInstall, 'get_reader', staticmethod(fake_get_reader))

    installer = object.__new__(ci.CustomInstall)
    installer.event = Events()
    installer.log_lines = []
    installer.seeddb = None
    installer.prepare_titles(['seed_missing.cia', 'seed_present.cia', 'no_seed.cia'])

    assert [path for _, path in installer.readers] == ['seed_present.cia', 'no_seed.cia']
    assert 'Skipping seed_missing.cia - seed not found, update seeddb.bin' in installer.log_lines
    assert not any("Couldn't read" in l for l in installer.log_lines)


def test_chosen_boot9_is_used_when_the_first_loaded_one_is_gone(tmp_path, monkeypatch):
    # pyctr keeps the path of the first boot9 it loaded, so crypto.b9_path can point at a removed card
    # even after the user chose another boot9
    sd, _ = make_sd(tmp_path)
    fuse = tmp_path / 'save3ds_fuse'
    fuse.write_bytes(b'')
    monkeypatch.setattr(ci, 'save3ds_fuse_path', str(fuse))

    installer = make_installer(sd, [FakeReader(TID_A)], skip_contents=True)
    installer.crypto.b9_path = str(tmp_path / 'removed-card' / 'boot9.bin')
    chosen = tmp_path / 'chosen' / 'boot9.bin'
    chosen.parent.mkdir()
    chosen_data = b'chosen boot9'.ljust(0x10000, b'\0')
    chosen.write_bytes(chosen_data)
    installer.boot9 = str(chosen)
    runs = []

    def fake_run(args, **kwargs):
        boot9 = args[args.index('-b') + 1]
        with open(boot9, 'rb') as b:
            runs.append((boot9, b.read()))
        run = FakeRun()
        run.args = args
        return run

    monkeypatch.setattr(ci.subprocess, 'run', fake_run)
    result, _, _ = installer.start()

    assert len(result['installed']) == 1 and not result['failed']
    assert runs and all(data == chosen_data and path != str(chosen) for path, data in runs)


def test_init_keeps_the_boot9_that_was_passed(tmp_path, monkeypatch):
    movable = tmp_path / 'movable.sed'
    movable.write_bytes(b'movable')

    class StubCrypto:
        b9_path = 'first-loaded/boot9.bin'

        def __init__(self, boot9=None):
            pass

        def setup_sd_key_from_file(self, path):
            pass

    monkeypatch.setattr(ci, 'CryptoEngine', StubCrypto)
    chosen = ci.CustomInstall(movable=str(movable), sd='sd', boot9='chosen/boot9.bin')
    assert chosen.boot9 == 'chosen/boot9.bin'
    fallback = ci.CustomInstall(movable=str(movable), sd='sd')
    assert fallback.boot9 == 'first-loaded/boot9.bin'


# ---------------------------------------------------------------------------
# main() (T6)

class FakeInstaller:
    id0_found = True
    start_result = ({'installed': [], 'failed': []}, False, 0)
    start_error = None
    calls = []

    def __init__(self, **kwargs):
        self.event = Events()
        self.crypto = SimpleNamespace(id0=ID0)
        self.logged = []

    def log(self, message, mtype=0, errorname=None, end='\n'):
        self.logged.append(message)
        self.calls.append((message, mtype))
        self.event.on_log_msg(message, end=end)

    def check_for_id0(self):
        return self.id0_found

    def prepare_titles(self, paths):
        pass

    def check_size(self):
        return 0, 1

    def start(self):
        if self.start_error:
            raise self.start_error
        return self.start_result


def run_main(monkeypatch, **attrs):
    installer_class = type('Installer', (FakeInstaller,), attrs)
    monkeypatch.setattr(ci, 'CustomInstall', installer_class)
    monkeypatch.setattr(sys, 'argv', ['custominstall', '-m', 'movable.sed', '--sd', 'sd', 'a.cia'])
    ci.main()


def test_main_missing_id0_exits_1(monkeypatch):
    with pytest.raises(SystemExit) as excinfo:
        run_main(monkeypatch, id0_found=False)
    assert excinfo.value.code == 1


def test_main_exit_code_when_start_fails(monkeypatch):
    with pytest.raises(SystemExit) as excinfo:
        run_main(monkeypatch, start_result=(None, False, 0))
    assert excinfo.value.code == 1


def test_main_exit_code_when_a_title_failed(monkeypatch):
    with pytest.raises(SystemExit) as excinfo:
        run_main(monkeypatch, start_result=({'installed': ['a'], 'failed': ['b']}, False, 0))
    assert excinfo.value.code == 1


def test_main_exit_code_when_all_installed(monkeypatch):
    # no SystemExit means a normal return, exit status 0
    run_main(monkeypatch, start_result=({'installed': ['a'], 'failed': []}, False, 0))


# ---------------------------------------------------------------------------
# copy_with_progress (F9)

def test_copy_with_progress_stops_on_truncated_input():
    installer = object.__new__(ci.CustomInstall)
    installer.event = Events()
    installer.crypto = FakeCrypto()

    src = io.BytesIO(b'abc')
    dst = io.BytesIO()
    digest = installer.copy_with_progress(src, dst, 10, '/title/x', fire_event=False)

    assert dst.getvalue() == b'abc'
    assert digest == sha256(b'abc').digest()
    assert digest != sha256(b'abc' + b'\0' * 7).digest()


# ---------------------------------------------------------------------------
# MSET9 and several id1 folders

ID2 = '22' * 16
MSET9_HINT = 'choose "5. Remove MSET9"'


def add_id1(sd, name, with_db):
    folder = sd / 'Nintendo 3DS' / ID0.hex() / name
    (folder / 'dbs').mkdir(parents=True)
    if with_db:
        (folder / 'dbs' / 'title.db').write_bytes(b'not a real database')
    return folder


def test_mset9_renamed_real_id1_is_detected(tmp_path, fake_tools):
    sd, id1_root = make_sd(tmp_path)
    renamed = id1_root.with_name(ID1 + '_user-id1')
    id1_root.rename(renamed)

    installer = make_installer(sd, [], skip_contents=True)
    with pytest.raises(ci.SDPathError) as excinfo:
        installer.start()

    assert MSET9_HINT in str(excinfo.value)
    assert ID1 + '_user-id1' in str(excinfo.value)


def test_mset9_hacked_id1_is_detected(tmp_path, fake_tools):
    sd, _ = make_sd(tmp_path)
    hacked = 'ab' + 'sdmc' + 'x' * 26
    assert len(hacked) == 32
    add_id1(sd, hacked, with_db=False)

    installer = make_installer(sd, [], skip_contents=True)
    with pytest.raises(ci.SDPathError) as excinfo:
        installer.start()

    assert MSET9_HINT in str(excinfo.value)
    assert hacked in str(excinfo.value)


def test_normal_id1_is_not_taken_for_mset9(tmp_path, fake_tools):
    sd, _ = make_sd(tmp_path)
    # a 32 character name without "sdmc" and other folders next to the id1 are not MSET9
    add_id1(sd, 'z' * 32, with_db=False)
    add_id1(sd, 'backup-of-something', with_db=False)

    installer = make_installer(sd, [FakeReader(TID_A)], skip_contents=True)
    with pytest.raises(ci.SDPathError) as excinfo:
        installer.start()

    # they still stop the install, since save3ds_fuse could use one of them instead of the id1
    message = str(excinfo.value)
    assert 'MSET9' not in message
    assert message.startswith(ID1) and 'z' * 32 in message and 'backup-of-something' in message


def test_multiple_id1_names_the_one_with_a_title_database_to_keep(tmp_path, fake_tools):
    sd, id1_root = make_sd(tmp_path)
    # the first id1 has no database, the second one does
    (id1_root / 'dbs' / 'title.db').unlink()
    other = add_id1(sd, ID2, with_db=True)

    installer = make_installer(sd, [FakeReader(TID_A)], skip_contents=False)
    with pytest.raises(ci.SDPathError) as excinfo:
        installer.start()

    # save3ds_fuse can't be told which folder to use, so nothing is installed until the other one is moved
    message = str(excinfo.value)
    assert message.startswith(ID2) and ID1 in message
    assert not (other / 'title').exists() and not (id1_root / 'title').exists()


def test_any_other_folder_next_to_the_id1_stops_the_install(tmp_path, fake_tools):
    sd, id1_root = make_sd(tmp_path)
    (id1_root.parent / '.hidden').mkdir()

    installer = make_installer(sd, [FakeReader(TID_A)], skip_contents=False)
    with pytest.raises(ci.SDPathError, match=r'\.hidden'):
        installer.start()

    assert not (id1_root / 'title').exists()
    assert (id1_root / 'dbs' / 'title.db').read_bytes() == b'not a real database'


def test_multiple_id1_with_two_databases_is_an_error_listing_both(tmp_path, fake_tools):
    sd, _ = make_sd(tmp_path)
    add_id1(sd, ID2, with_db=True)

    installer = make_installer(sd, [], skip_contents=True)
    with pytest.raises(ci.SDPathError) as excinfo:
        installer.start()

    assert 'multiple id1 directories' in str(excinfo.value)
    assert ID1 in str(excinfo.value) and ID2 in str(excinfo.value)


def test_multiple_id1_without_any_database_is_an_error_listing_both(tmp_path, fake_tools):
    sd, id1_root = make_sd(tmp_path)
    (id1_root / 'dbs' / 'title.db').unlink()
    add_id1(sd, ID2, with_db=False)

    installer = make_installer(sd, [], skip_contents=True)
    with pytest.raises(ci.SDPathError) as excinfo:
        installer.start()

    assert 'multiple id1 directories' in str(excinfo.value)
    assert ID1 in str(excinfo.value) and ID2 in str(excinfo.value)


def test_no_id1_is_still_an_error(tmp_path, fake_tools):
    sd, id1_root = make_sd(tmp_path)
    ci.rmtree(id1_root)

    installer = make_installer(sd, [], skip_contents=True)
    with pytest.raises(ci.SDPathError, match='Could not find a suitable id1 directory'):
        installer.start()


def test_main_reports_sd_path_error_and_exits_1(monkeypatch, capsys):
    message = 'MSET9 is still set up on this SD card (found x). ' + MSET9_HINT
    calls = []
    with pytest.raises(SystemExit) as excinfo:
        run_main(monkeypatch, start_error=ci.SDPathError(message), calls=calls)

    assert excinfo.value.code == 1
    assert calls == [(message, 2)]
    captured = capsys.readouterr()
    assert message in captured.out
    assert 'Traceback' not in captured.out + captured.err


# ---------------------------------------------------------------------------
# save3ds_fuse cannot be started

def test_extract_cannot_start_save3ds_fuse(tmp_path, monkeypatch):
    sd, _ = make_sd(tmp_path)
    fuse = tmp_path / 'save3ds_fuse'
    fuse.write_bytes(b'')
    monkeypatch.setattr(ci, 'save3ds_fuse_path', str(fuse))

    def blocked(*args, **kwargs):
        raise PermissionError(5, 'Access is denied')

    monkeypatch.setattr(ci.subprocess, 'run', blocked)

    installer = make_installer(sd, [FakeReader(TID_A)], skip_contents=True)
    assert installer.start() == (None, False, 0)

    assert any(l.startswith("Error: Couldn't run save3ds_fuse at " + str(fuse)) and 'Access is denied' in l
               for l in installer.log_lines)
    assert any(l.startswith('Error: ') and 'antivirus or security software' in l for l in installer.log_lines)


def test_import_cannot_start_save3ds_fuse_fails_only_that_title(tmp_path, monkeypatch):
    def blocked():
        raise PermissionError(5, 'Access is denied')

    installers = []

    def prepare(installer, imports):
        # write contents, so the hint about running again with --skip-contents applies
        installer.skip_contents = False
        installers.append(installer)

    result, application_count, imports = run_with_existing_database(tmp_path, monkeypatch, blocked, prepare)

    assert len(result['failed']) == 1 and TID_A in result['failed'][0]
    assert len(result['installed']) == 1 and TID_B in result['installed'][0]
    assert any(l.startswith("Error: Couldn't run save3ds_fuse at") and 'Access is denied' in l
               for l in installers[0].log_lines)
    assert any('antivirus or security software' in l for l in installers[0].log_lines)
    assert any('--skip-contents' in l for l in installers[0].log_lines)
    # the entry of the failed title is back as it was for the next import
    assert imports[1][TID_A] == b'OLD-A'
    assert application_count == 3


# ---------------------------------------------------------------------------
# GUI search folders

def test_gui_search_dirs_start_with_the_current_folder(monkeypatch):
    pytest.importorskip('tkinter')
    from custominstall import gui

    monkeypatch.setattr(gui, 'frozen', False)
    monkeypatch.setattr(gui, 'getcwd', lambda: 'current')
    assert gui.search_dirs() == ['current', gui.file_parent]


def test_gui_search_dirs_put_the_executable_folder_first_when_frozen(monkeypatch):
    pytest.importorskip('tkinter')
    from custominstall import gui

    monkeypatch.setattr(gui, 'frozen', True)
    monkeypatch.setattr(gui.sys, 'executable', os.path.join('app', 'ci-gui.exe'))
    monkeypatch.setattr(gui, 'getcwd', lambda: 'current')
    assert gui.search_dirs() == ['app', 'current', gui.file_parent]


# ---------------------------------------------------------------------------
# boot9 and movable.sed for save3ds_fuse

def test_missing_boot9_stops_before_touching_the_sd(tmp_path, fake_tools):
    sd, id1_root = make_sd(tmp_path)
    installer = make_installer(sd, [FakeReader(TID_A)], skip_contents=False)
    # the drive boot9 was chosen from is gone by the time the install starts
    os.remove(installer.crypto.b9_path)

    with pytest.raises(ci.KeyFileError, match='boot9 is no longer at'):
        installer.start()

    assert (id1_root / 'dbs' / 'title.db').read_bytes() == b'not a real database'
    assert not (id1_root / 'title').exists()


def test_missing_movable_stops_before_touching_the_sd(tmp_path, fake_tools):
    sd, id1_root = make_sd(tmp_path)
    installer = make_installer(sd, [FakeReader(TID_A)], skip_contents=False)
    os.remove(installer.movable)

    with pytest.raises(ci.KeyFileError, match='movable.sed is no longer at'):
        installer.start()

    assert (id1_root / 'dbs' / 'title.db').read_bytes() == b'not a real database'
    assert not (id1_root / 'title').exists()


def test_wrong_size_boot9_stops_before_touching_the_sd(tmp_path, fake_tools):
    sd, id1_root = make_sd(tmp_path)
    installer = make_installer(sd, [FakeReader(TID_A)], skip_contents=False)
    # boot9_prot.bin (0x8000 bytes) loads in pyctr but save3ds_fuse cannot use it
    with open(installer.boot9, 'wb') as f:
        f.write(b'boot9'.ljust(0x8000, b'\0'))

    with pytest.raises(ci.KeyFileError, match="isn't a full boot9 dump") as excinfo:
        installer.start()
    assert 'boot9_prot.bin' in str(excinfo.value)

    assert (id1_root / 'dbs' / 'title.db').read_bytes() == b'not a real database'
    assert not (id1_root / 'title').exists()


def test_full_size_boot9_is_accepted(tmp_path, fake_tools):
    sd, _ = make_sd(tmp_path)
    installer = make_installer(sd, [FakeReader(TID_A)], skip_contents=True)
    assert os.path.getsize(installer.boot9) == 0x10000
    result, _, _ = installer.start()
    assert len(result['installed']) == 1


def test_missing_movable_at_start_up_is_a_key_file_error(tmp_path):
    with pytest.raises(ci.KeyFileError, match="movable.sed can't be found at") as excinfo:
        ci.CustomInstall(movable=str(tmp_path / 'gone' / 'movable.sed'), sd=str(tmp_path / 'sd'))
    assert 'on the command line, pass the right path with -m' in str(excinfo.value)


def test_main_reports_missing_movable_and_exits_1(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['custominstall', '-m', str(tmp_path / 'gone.sed'), '--sd', str(tmp_path), 'a.cia'])
    with pytest.raises(SystemExit) as excinfo:
        ci.main()

    assert excinfo.value.code == 1
    captured = capsys.readouterr()
    assert "movable.sed can't be found at" in captured.out
    assert 'Traceback' not in captured.out + captured.err


def run_main_with_boot9(tmp_path, monkeypatch, capsys, boot9):
    movable = tmp_path / 'movable.sed'
    movable.write_bytes(b'\0' * 0x140)
    monkeypatch.setattr(sys, 'argv', ['custominstall', '-m', str(movable), '-b', str(boot9),
                                      '--sd', str(tmp_path), 'a.cia'])
    with pytest.raises(SystemExit) as excinfo:
        ci.main()
    captured = capsys.readouterr()
    return excinfo.value.code, captured.out, captured.err


def test_main_reports_missing_boot9_and_exits_1(tmp_path, monkeypatch, capsys):
    code, out, err = run_main_with_boot9(tmp_path, monkeypatch, capsys, tmp_path / 'gone' / 'boot9.bin')

    assert code == 1
    assert 'Error: ' in out
    assert 'Check the path given with -b' in out
    assert 'Traceback' not in out + err


def test_main_reports_a_boot9_that_is_not_a_boot9_and_exits_1(tmp_path, monkeypatch, capsys):
    bad = tmp_path / 'boot9.bin'
    bad.write_bytes(b'\0' * 0x10000)
    code, out, err = run_main_with_boot9(tmp_path, monkeypatch, capsys, bad)

    assert code == 1
    assert 'Error: ' in out
    assert 'Check the path given with -b' in out
    assert 'Traceback' not in out + err


class StubTextbox:
    def __init__(self, value):
        self.value = value

    def get(self, start, end):
        return self.value


def run_gui_start_install(monkeypatch, boot9, error):
    # start_install only needs these parts of the window, so it runs without a display
    # (importing custominstall.gui runs its start-up code once per test session: it adds the cwd and package
    # folder to pyctr's boot9 search list, may load a seeddb from the config folders, and tries to create the
    # Windows taskbar object. That is why 'taskbar' is patched below, and why no test here relies on b9_paths.)
    pytest.importorskip('tkinter')
    from custominstall import gui

    created = []
    shown = []

    def fake_custom_install(**kwargs):
        created.append(kwargs)
        raise error

    monkeypatch.setattr(gui, 'CustomInstall', fake_custom_install)
    monkeypatch.setattr(gui, 'taskbar', None)
    window = SimpleNamespace(
        file_picker_textboxes={'sd': StubTextbox('sd'), 'seeddb': StubTextbox('seeddb.bin'),
                               'movable.sed': StubTextbox('movable.sed'), 'boot9': StubTextbox(boot9)},
        readers={'a.cia': object()},
        skip_contents_var=SimpleNamespace(get=lambda: 0),
        overwrite_saves_var=SimpleNamespace(get=lambda: 0),
        update_status=lambda *args: None,
        disable_buttons=lambda: None,
        enable_buttons=lambda: None,
        show_error=shown.append)
    gui.CustomInstallGUI.start_install(window)
    return created, shown


def test_gui_passes_no_boot9_when_the_box_is_empty(monkeypatch):
    created, _ = run_gui_start_install(monkeypatch, '', RuntimeError('stop'))
    assert created[0]['boot9'] is None
    created, _ = run_gui_start_install(monkeypatch, 'chosen/boot9.bin', RuntimeError('stop'))
    assert created[0]['boot9'] == 'chosen/boot9.bin'


def test_gui_shows_a_key_file_error_as_it_is_worded(monkeypatch):
    message = ("movable.sed can't be found at x. If it was on a card or drive that was removed or got a different "
               "drive letter, choose it again (on the command line, pass the right path with -m).")
    _, shown = run_gui_start_install(monkeypatch, '', ci.KeyFileError(message))
    assert shown == [message]
    _, shown = run_gui_start_install(monkeypatch, '', FileNotFoundError('nope'))
    assert shown == ['Could not start the install: FileNotFoundError: nope']


def test_save3ds_fuse_keeps_working_when_the_boot9_drive_goes_away(tmp_path, monkeypatch):
    sd, _ = make_sd(tmp_path)
    fuse = tmp_path / 'save3ds_fuse'
    fuse.write_bytes(b'')
    monkeypatch.setattr(ci, 'save3ds_fuse_path', str(fuse))

    installer = make_installer(sd, [FakeReader(TID_A), FakeReader(TID_B)], skip_contents=True)
    original_boot9 = installer.crypto.b9_path
    original_movable = installer.movable
    runs = []

    def fake_run(args, **kwargs):
        boot9 = args[args.index('-b') + 1]
        movable = args[args.index('-m') + 1]
        with open(boot9, 'rb') as b, open(movable, 'rb') as m:
            runs.append((boot9, movable, b.read(), m.read()))
        if os.path.exists(original_boot9):
            # the card or reader holding boot9 and movable.sed is removed after the first run
            os.remove(original_boot9)
            os.remove(original_movable)
        run = FakeRun()
        run.args = args
        return run

    monkeypatch.setattr(ci.subprocess, 'run', fake_run)
    result, _, _ = installer.start()

    assert len(result['installed']) == 2 and not result['failed']
    # one extract and one import per title, all with readable copies, never the original paths
    assert len(runs) == 3
    assert all(b == BOOT9_DATA and m == b'movable' for _, _, b, m in runs)
    assert all(bp != original_boot9 and mp != original_movable for bp, mp, _, _ in runs)
