#!/usr/bin/env python3
"""Version-locked SteamOS package installer. No session restart or user-setting edits."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

BUNDLE = Path(__file__).resolve().parent
STATE = Path('/var/lib/steamos-osk-native')


def run(*args):
    return subprocess.check_output(args, text=True, env={**os.environ, 'LC_ALL': 'C'}).strip()


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def read_json(path):
    return json.loads(path.read_text())


def write_json(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, indent=2) + '\n')
    os.replace(temp, path)


def compare_environment(expected, actual_os, architecture, packages):
    errors = []
    if architecture != expected['architecture']:
        errors.append('Architecture: ' + architecture)
    for key, value in expected['os_release'].items():
        if actual_os.get(key) != value:
            errors.append(f'{key}: expected {value}, found {actual_os.get(key)}')
    for name, version in expected['runtime_packages'].items():
        if packages.get(name) != version:
            errors.append(f'{name}: expected {version}, found {packages.get(name)}')
    require(not errors, 'Unsupported environment; rebuild for this OS.\n' + '\n'.join(errors))


def verify_archives(root, manifest):
    for name, package in manifest['packages'].items():
        for version, archive in package['versions'].items():
            path = root / archive['file']
            require(digest(path) == archive['sha256'], f'Archive checksum mismatch: {path}')
            require(run('pacman', '-Qp', str(path)) == f'{name} {version}',
                    f'Package metadata mismatch: {path}')


def verify_installed(manifest, versions):
    installed = dict(line.split(' ', 1) for line in run('pacman', '-Q').splitlines())
    for name, version in versions.items():
        require(installed.get(name) == version, f'Installed version mismatch: {name}')
        package = manifest['packages'][name]
        files = package['installed_files'] if version == package['fixed'] else package['base_files']
        for path, expected in files.items():
            require(digest(path) == expected, f'Installed file mismatch: {path}')


def preflight(root, check_files=True):
    require(platform.system() == 'Linux', 'This binary bundle requires Linux / SteamOS.')
    manifest = read_json(root / 'manifest.json')
    expected = read_json(root / 'tested-environment.json')
    os_info = {}
    for line in Path('/etc/os-release').read_text().splitlines():
        if '=' in line and not line.startswith('#'):
            key, value = line.split('=', 1)
            os_info[key] = value.strip('"\'')
    installed = dict(line.split(' ', 1) for line in run('pacman', '-Q').splitlines())
    compare_environment(expected, os_info, platform.machine(), installed)
    versions = {}
    for name, package in manifest['packages'].items():
        version = installed.get(name)
        require(version in package['versions'], f'Unsupported {name} version: {version}')
        versions[name] = version
    verify_archives(root, manifest)
    if check_files:
        verify_installed(manifest, versions)
    require(run('steamos-readonly', 'status') in ('enabled', 'disabled'), 'Unknown readonly state')
    run('getcap', '/usr/bin/kwin_wayland')
    return manifest, versions


@contextlib.contextmanager
def writable_system():
    previous = run('steamos-readonly', 'status')
    require(previous in ('enabled', 'disabled'), 'Unknown readonly state')
    try:
        if previous == 'enabled':
            run('steamos-readonly', 'disable')
        yield
    finally:
        if previous == 'enabled':
            run('steamos-readonly', 'enable')


def package_transaction(root, manifest, versions):
    archives = [str(root / manifest['packages'][name]['versions'][version]['file'])
                for name, version in versions.items()]
    subprocess.run(['pacman', '-U', '--noconfirm', *archives], check=True,
                   env={**os.environ, 'LC_ALL': 'C'})
    verify_installed(manifest, versions)


def install():
    manifest, previous = preflight(BUNDLE)
    target = {name: package['fixed'] for name, package in manifest['packages'].items()}
    if previous == target:
        print('Already installed; package versions and file hashes match. No changes made.')
        return
    require(not STATE.exists(), f'Backup already exists: {STATE}. Inspect or roll back first.')
    capability = run('getcap', '/usr/bin/kwin_wayland')
    with writable_system():
        STATE.mkdir(mode=0o700)
        for filename in ('manifest.json', 'tested-environment.json', 'manage.py'):
            shutil.copy2(BUNDLE / filename, STATE / filename)
        shutil.copytree(BUNDLE / 'packages', STATE / 'packages')
        verify_archives(STATE, manifest)
        journal = {'previous': previous, 'target': target, 'capability': capability,
                   'status': 'installing'}
        write_json(STATE / 'journal.json', journal)
        try:
            package_transaction(STATE, manifest, target)
            require(run('getcap', '/usr/bin/kwin_wayland') == capability, 'KWin capability changed')
        except (Exception, KeyboardInterrupt):
            journal['status'] = 'recovery_required'
            write_json(STATE / 'journal.json', journal)
            try:
                package_transaction(STATE, manifest, previous)
                require(run('getcap', '/usr/bin/kwin_wayland') == capability,
                        'KWin capability not restored')
                journal['status'] = 'rolled_back'
                write_json(STATE / 'journal.json', journal)
            except (Exception, KeyboardInterrupt) as recovery:
                print(f'Automatic rollback failed: {recovery}. Backup: {STATE}', file=sys.stderr)
            raise
        journal['status'] = 'installed'
        write_json(STATE / 'journal.json', journal)
    print('Installed. Save your work, then restart manually. No session was restarted.')


def rollback():
    require(STATE.is_dir() and not STATE.is_symlink(), 'No valid installation backup found')
    require(STATE.stat().st_uid == 0 and STATE.stat().st_mode & 0o022 == 0, 'Unsafe backup owner/mode')
    manifest, _ = preflight(STATE, check_files=False)
    journal = read_json(STATE / 'journal.json')
    if journal['status'] == 'rolled_back':
        verify_installed(manifest, journal['previous'])
        print('Already rolled back. Backup retained.')
        return
    with writable_system():
        package_transaction(STATE, manifest, journal['previous'])
        require(run('getcap', '/usr/bin/kwin_wayland') == journal['capability'],
                'KWin capability mismatch after rollback')
        journal['status'] = 'rolled_back'
        write_json(STATE / 'journal.json', journal)
    print('Previous packages restored. Save your work, then restart manually. Backup retained.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('check', 'install', 'rollback'), nargs='?', default='check')
    action = parser.parse_args().action
    if action == 'check':
        _, versions = preflight(BUNDLE)
        print(json.dumps({'compatible_binary_environment': True, 'installed': versions,
                          'note': 'Hardware/input behavior still needs validation on each device.'}, indent=2))
        return
    require(os.geteuid() == 0, 'Run install/rollback with sudo; check requires no sudo.')
    import fcntl
    with Path('/run/lock/steamos-osk-native.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        install() if action == 'install' else rollback()


if __name__ == '__main__':
    try:
        main()
    except (Exception, KeyboardInterrupt) as error:
        print('STOPPED: ' + str(error), file=sys.stderr)
        sys.exit(1)
