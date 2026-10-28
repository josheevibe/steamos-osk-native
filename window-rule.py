#!/usr/bin/env python3
"""Install/remove only the Steam OSK KWin window rule for the current user."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

KEY = 'steam-osk-native-focus'


def sections(text):
    matches = list(re.finditer(r'^\[([^\n\]]+)\]\s*\n', text, re.M))
    result = {'': text[:matches[0].start()] if matches else text}
    for index, match in enumerate(matches):
        name = match.group(1)
        if name in result:
            raise RuntimeError('Duplicate config section: ' + name)
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        result[name] = text[match.start():end]
    return result


def entry(block, key, default=''):
    match = re.search(r'^' + re.escape(key) + r'=(.*)$', block, re.M)
    return match.group(1) if match else default


def set_entry(block, key, value):
    pattern = r'^' + re.escape(key) + r'=.*$'
    if re.search(pattern, block, re.M):
        return re.sub(pattern, lambda _: key + '=' + value, block, flags=re.M)
    return block.rstrip('\n') + '\n' + key + '=' + value + '\n'


def rule(title):
    if not title or any(c in title for c in '\n\r\\'):
        raise RuntimeError('Use the exact keyboard title without line breaks or backslashes')
    return (f'[{KEY}]\nDescription=Steam virtual keyboard keeps text-field focus\n'
            'wmclass=steam\nwmclasscomplete=false\nwmclassmatch=1\n'
            f'title={title}\ntitlematch=1\nacceptfocus=false\nacceptfocusrule=2\n'
            'fsplevel=4\nfsplevelrule=2\nlayer=overlay\nlayerrule=2\n\n')


def merge(text, replacement, member, position=None):
    parts = sections(text)
    general = parts.get('General', '[General]\n')
    keys = [item for item in entry(general, 'rules').split(',') if item and item != KEY]
    if member:
        keys.insert(len(keys) if position is None else min(position, len(keys)), KEY)
    general = set_entry(general, 'rules', ','.join(keys))
    parts['General'] = set_entry(general, 'count', str(len(keys)))
    if replacement is None:
        parts.pop(KEY, None)
    else:
        parts[KEY] = replacement
    return ''.join(block if not block or block.endswith('\n') else block + '\n'
                   for block in parts.values())


def atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.osk-tmp')
    temp.write_text(text)
    temp.chmod(0o600)
    os.replace(temp, path)


def apply(action, title, config, backup):
    original = config.read_text() if config.exists() else ''
    parts = sections(original)
    current = parts.get(KEY)
    if action == 'status':
        print(current or 'No Steam OSK rule installed.')
        return False
    if action == 'install':
        desired = rule(title)
        old_keys = [key for key in entry(parts.get('General', ''), 'rules').split(',') if key]
        member = KEY in old_keys
        position = old_keys.index(KEY) if member else None
        if current and current.strip() == desired.strip() and member:
            print('Matching rule already exists. No changes made.')
            return False
        if backup.exists():
            raise RuntimeError('Existing backup: remove the managed rule before changing its title')
        saved = {'previous': current, 'member': member, 'position': position, 'installed': desired,
                 'config': str(config)}
        atomic(backup, json.dumps(saved, ensure_ascii=False, indent=2) + '\n')
        updated = merge(original, desired, True, position)
    else:
        if not backup.exists():
            print('No rule backup; no changes made.')
            return False
        saved = json.loads(backup.read_text())
        if saved['config'] != str(config) or current != saved['installed']:
            raise RuntimeError('Rule changed since installation. Review the backup before restoring')
        updated = merge(original, saved['previous'], saved['member'], saved['position'])
    if (config.read_text() if config.exists() else '') != original:
        raise RuntimeError('KWin config changed concurrently; retry after closing its settings window')
    atomic(config, updated)
    if action == 'remove':
        backup.unlink()
    print('Window rule ' + ('installed.' if action == 'install' else 'restored.'))
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('status', 'install', 'remove'))
    parser.add_argument('--title', default='Steam Input 가상 키보드')
    args = parser.parse_args()
    if os.geteuid() == 0:
        raise RuntimeError('Run as the desktop user, without sudo')
    config = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'kwinrulesrc'
    backup = Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'steamos-osk-native/window-rule.json'
    changed = apply(args.action, args.title, config, backup)
    if changed:
        bus = shutil.which('qdbus6')
        if bus and os.environ.get('DBUS_SESSION_BUS_ADDRESS'):
            result = subprocess.run([bus, 'org.kde.KWin', '/KWin', 'reconfigure'], check=False)
            if result.returncode == 0:
                return
        print('KWin will load the rule on your next desktop login.')


if __name__ == '__main__':
    main()
