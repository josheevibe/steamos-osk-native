#!/usr/bin/env python3
"""Repack a Valve package with selected rebuilt files (Python 3.14+ for zstd).

Run inside the matching build environment, after stripping/removing build RPATH.
Example: python3 archive-rebuild.py original.pkg.tar.zst fixed.pkg.tar.zst \
  --version 24.1.14-1.1.1 --recipe sources/xwayland/PKGBUILD.patched \
  --replace usr/bin/Xwayland=/path/to/stripped/Xwayland
Does not install packages. Output must not already exist.
"""
import argparse
import copy
import gzip
import hashlib
import io
from pathlib import Path
import re
import subprocess
import tarfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('original', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--version', required=True)
    parser.add_argument('--recipe', required=True, type=Path)
    parser.add_argument('--replace', action='append', required=True, metavar='ARCHIVE_PATH=BUILT_FILE')
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        raise RuntimeError('Output already exists')
    changes = {}
    for value in args.replace:
        name, filename = value.split('=', 1)
        if name not in ('usr/bin/Xwayland', 'usr/lib/libkwin.so.6.7.3',
                        'usr/lib/qt6/plugins/kwin/plugins/eis.so'):
            raise RuntimeError('Unreviewed runtime replacement: ' + name)
        changes[name] = Path(filename).read_bytes()
    now = int(time.time())
    with tarfile.open(args.original) as original:
        members = original.getmembers()
        metadata = original.extractfile('.PKGINFO').read().decode()
        name = re.search(r'^pkgname = (.+)$', metadata, re.M)[1]
        delta = sum(len(data) - original.getmember(path).size for path, data in changes.items())
        updates = {'pkgver': args.version, 'builddate': str(now),
                   'size': str(int(re.search(r'^size = (\d+)$', metadata, re.M)[1]) + delta),
                   'packager': 'Local native OSK source repair'}
        for key, value in updates.items():
            metadata = re.sub(r'^' + key + r' = .*$', lambda _: key + ' = ' + value, metadata, flags=re.M)
        changes['.PKGINFO'] = metadata.encode()
        info = ['format = 2', 'pkgname = ' + name, 'pkgbase = ' + name,
                'pkgver = ' + args.version, 'pkgarch = x86_64',
                'pkgbuild_sha256sum = ' + hashlib.sha256(args.recipe.read_bytes()).hexdigest(),
                'packager = Local native OSK source repair', 'builddate = ' + str(now),
                'builddir = ' + str(Path.cwd()), 'startdir = ' + str(args.recipe.resolve().parent),
                'buildtool = native-osk-archive-rebuild', 'buildtoolver = 1', 'options = strip']
        packages = subprocess.check_output(['pacman', '-Q'], text=True).splitlines()
        info += ['installed = ' + line.replace(' ', '-', 1) for line in sorted(packages)]
        changes['.BUILDINFO'] = ('\n'.join(info) + '\n').encode()
        mtree = gzip.decompress(original.extractfile('.MTREE').read()).decode()
        for path, data in changes.items():
            pattern = r'^\./' + re.escape(path) + r' .*?$'
            lines = re.findall(pattern, mtree, re.M)
            if len(lines) != 1:
                raise RuntimeError('Missing/duplicate mtree entry: ' + path)
            line = lines[0]
            values = {'time': str(now) + '.0', 'size': str(len(data)),
                      'sha256digest': hashlib.sha256(data).hexdigest()}
            for key, value in values.items():
                line = re.sub(r'\b' + key + r'=\S+', key + '=' + value, line)
            mtree = re.sub(pattern, lambda _: line, mtree, flags=re.M)
        changes['.MTREE'] = gzip.compress(mtree.encode(), mtime=now)
        with args.output.open('xb') as stream, tarfile.open(fileobj=stream, mode='w:zst', format=tarfile.PAX_FORMAT) as output:
            for member in members:
                updated = copy.copy(member)
                if member.name in changes:
                    data = changes[member.name]
                    updated.size, updated.mtime = len(data), now
                    output.addfile(updated, io.BytesIO(data))
                else:
                    output.addfile(updated, original.extractfile(member) if member.isfile() else None)
    with tarfile.open(args.original) as before, tarfile.open(args.output) as after:
        if before.getnames() != after.getnames():
            raise RuntimeError('Archive member list changed')
        for left, right in zip(before.getmembers(), after.getmembers()):
            pax = dict(right.pax_headers)
            if 'hdrcharset' not in left.pax_headers and pax.get('hdrcharset') == 'BINARY':
                pax.pop('hdrcharset')
            if left.pax_headers != pax or any(getattr(left, k) != getattr(right, k)
                    for k in ('mode', 'uid', 'gid', 'type', 'linkname')):
                raise RuntimeError('Archive attributes changed: ' + left.name)
            if left.isfile() and left.name not in changes:
                if before.extractfile(left).read() != after.extractfile(right).read():
                    raise RuntimeError('Unplanned payload change: ' + left.name)
    print('Created; unchanged payload and attributes verified:', args.output)


if __name__ == '__main__':
    main()
