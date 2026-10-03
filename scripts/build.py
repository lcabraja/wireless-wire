#!/usr/bin/env python3
"""Build an original-code-only zipapp and optional native launcher."""
import argparse
import platform
from pathlib import Path
import shutil
import subprocess
import tempfile
import zipapp

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'dist')
    parser.add_argument('--native', action='store_true')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        stage = Path(temporary)
        package = stage / 'wireless_wire'
        package.mkdir()
        for source in sorted((ROOT / 'src/wireless_wire').glob('*.py')):
            shutil.copyfile(source, package / source.name)
        (stage / '__main__.py').write_text(
            'import sys\n'
            'if sys.version_info < (3, 11):\n'
            '    raise SystemExit("Wireless Wire requires Python 3.11 or newer")\n'
            'from wireless_wire.cli import main\nmain()\n')
        zipapp.create_archive(stage, output / 'wireless-wire.pyz',
                              interpreter='/usr/bin/env python3', compressed=True)
    (output / 'wireless-wire.pyz').chmod(0o755)
    if args.native:
        command = ['cc', '-O2', '-Wall', '-Wextra', '-Werror',
                   '-ffile-prefix-map=' + str(ROOT) + '=.', '-o', str(output / 'wireless-wire')]
        if platform.system() == 'Darwin':
            command += ['-arch', 'arm64', '-arch', 'x86_64']
        command += ['native/launcher.c']
        subprocess.run(command, cwd=ROOT, check=True)
        subprocess.run(['strip', str(output / 'wireless-wire')], check=True)
    print('Built ' + str(output))


if __name__ == '__main__':
    main()
