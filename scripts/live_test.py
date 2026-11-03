"""Run an explicitly selected site's live tests, after validating the input.

Usage mistakes (unknown directory, missing API key) exit 2. A site suite that
fails keeps pytest's own exit code, so a failed assertion is not reported as
a harness configuration error and the reverse.
"""
import json
import os
from pathlib import Path
import subprocess
import sys


def main():
    root = Path(__file__).resolve().parents[1]
    names = {item['directory'] for item in json.loads((root / 'docs/catalog.json').read_text())}
    selected = os.environ.get('SELECTED_SCRAPER', '')
    if selected not in names:
        print('SELECTED_SCRAPER must name one directory from docs/catalog.json', file=sys.stderr)
        return 2
    if not os.environ.get('ADSCRAWL_API_KEY'):
        print('Set ADSCRAWL_API_KEY; live tests consume credits', file=sys.stderr)
        return 2
    return subprocess.call(
        [sys.executable, '-m', 'pytest', str(root / selected / 'test.py'), '-v', '--reruns=0'],
        cwd=root,
    )


if __name__ == '__main__':
    raise SystemExit(main())
