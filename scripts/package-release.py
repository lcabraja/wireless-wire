#!/usr/bin/env python3
"""Package reviewed project files only; never include an interpreter or USB tools."""
import argparse
import hashlib
import io
from pathlib import Path
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = '1.0.0'
FILES = ('README.md', 'LICENSE', 'AUDIT.md', 'DEPENDENCIES.md',
         'scripts/install-server.sh', 'scripts/install-client.py',
         'scripts/uninstall-server.sh')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--build-dir', type=Path, required=True)
    parser.add_argument('--platform', choices=('macos-universal', 'linux-arm64'), required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/releases')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    name = f'wireless-wire-v{VERSION}-{args.platform}'
    with tarfile.open(args.output / (name + '.tar.gz'), 'w:gz') as archive:
        sources = [(item, ROOT / item) for item in FILES]
        sources += [(item, args.build_dir / item) for item in ('wireless-wire', 'wireless-wire.pyz')]
        for relative, source in sources:
            data = source.read_bytes()
            info = tarfile.TarInfo(name + '/' + relative)
            info.size = len(data)
            info.mode = 0o755 if relative == 'wireless-wire' or relative.endswith(('.sh', '.py')) else 0o644
            info.mtime = 0
            archive.addfile(info, io.BytesIO(data))
    with zipfile.ZipFile(args.output / f'wireless-wire-skill-v{VERSION}.zip', 'w',
                         compression=zipfile.ZIP_DEFLATED) as archive:
        info = zipfile.ZipInfo('wireless-wire/SKILL.md', date_time=(2026, 1, 1, 0, 0, 0))
        info.external_attr = 0o100644 << 16
        archive.writestr(info, (ROOT / 'skills/wireless-wire/SKILL.md').read_bytes())
    paths = sorted(p for p in args.output.iterdir() if p.suffix in ('.gz', '.zip', '.pyz'))
    (args.output / 'SHA256SUMS').write_text(''.join(
        hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name + '\n' for p in paths))
    print('Packaged ' + name)


if __name__ == '__main__':
    main()
