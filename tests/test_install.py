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
    installer.movable = 'movable.sed'
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
    result, _, _ = installer.start()

    assert result['installed'] and not result['failed']


def test_multiple_id1_uses_the_one_with_a_title_database(tmp_path, fake_tools):
    sd, id1_root = make_sd(tmp_path)
    # the first id1 has no database, the second one does
    (id1_root / 'dbs' / 'title.db').unlink()
    other = add_id1(sd, ID2, with_db=True)

    installer = make_installer(sd, [FakeReader(TID_A)], skip_contents=False)
    result, _, _ = installer.start()

    assert result['installed'] and not result['failed']
    assert (other / 'title' / '00040000' / '00012345' / 'content' / '00000000.app').is_file()
    assert not (id1_root / 'title').exists()
    warnings = [l for l in installer.log_lines if l.startswith('Warning: ')]
    assert len(warnings) == 1 and ID2 in warnings[0] and ID1 in warnings[0]


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
    result, application_count, imports = run_with_existing_database(
        tmp_path, monkeypatch, blocked, lambda installer, imports: installers.append(installer))

    assert len(result['failed']) == 1 and TID_A in result['failed'][0]
    assert len(result['installed']) == 1 and TID_B in result['installed'][0]
    assert any(l.startswith("Error: Couldn't run save3ds_fuse at") and 'Access is denied' in l
               for l in installers[0].log_lines)
    assert any('antivirus or security software' in l for l in installers[0].log_lines)
    # the entry of the failed title is back as it was for the next import
    assert imports[1][TID_A] == b'OLD-A'
    assert application_count == 3
