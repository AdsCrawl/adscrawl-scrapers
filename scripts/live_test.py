"""Run an explicitly selected site's live tests, after validating the input."""
import json
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
names = {item['directory'] for item in json.loads((root/'docs/catalog.json').read_text())}
selected = os.environ.get('SELECTED_SCRAPER', '')
if selected not in names:
    raise SystemExit('SELECTED_SCRAPER must name one directory from docs/catalog.json')
if not os.environ.get('ADSCRAWL_API_KEY'):
    raise SystemExit('Set ADSCRAWL_API_KEY; live tests consume credits')
raise SystemExit(subprocess.call([sys.executable,'-m','pytest',str(root/selected/'test.py'),'-v','--reruns=0'],cwd=root))
