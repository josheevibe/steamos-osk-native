#!/usr/bin/env python3
"""Unpack and patch sources in a NEW output directory. Does not build or install."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent / 'sources'
    manifest = json.loads((root / 'manifest.json').read_text())
    args.output.mkdir(parents=True, exist_ok=False)
    output = args.output.resolve()
    for name, source in manifest.items():
        directory = root / name
        for filename, expected in source['sha256'].items():
            if hashlib.sha256((directory / filename).read_bytes()).hexdigest() != expected:
                raise RuntimeError('Source checksum mismatch: ' + filename)
        with tarfile.open(directory / source['archive']) as archive:
            for member in archive.getmembers():
                path = PurePosixPath(member.name)
                if path.is_absolute() or '..' in path.parts or not (member.isfile() or member.isdir()):
                    raise RuntimeError('Unsupported source archive member: ' + member.name)
            archive.extractall(output)
        tree = output / source['directory']
        for patch in source['patches']:
            # Valve's shipped 0006 patch needs context fuzz on its own 6.7.3 archive.
            # Every touched file is checked against the actual build source below.
            subprocess.run(['patch', '--batch', '--fuzz=2', '-p1', '-i', str(directory / patch)],
                           cwd=tree, check=True)
        for filename, expected in source['patched_files'].items():
            if hashlib.sha256((tree / filename).read_bytes()).hexdigest() != expected:
                raise RuntimeError('Patched source does not match installed build: ' + filename)
        print('Verified patched sources:', tree)


if __name__ == '__main__':
    main()
