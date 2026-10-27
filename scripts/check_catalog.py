"""Credential-free source, import and request configuration audit for every site."""
from __future__ import annotations
import ast
import importlib.util
import json
from pathlib import Path
import sys
from dataclasses import fields
from adscrawl_scrapers import Request

ROOT = Path(__file__).resolve().parents[1]


def load_module(path):
    name = 'scraper_' + path.parent.name.replace('-', '_') + '_' + path.stem
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def check():
    catalog = json.loads((ROOT / 'docs/catalog.json').read_text())
    allowed = {f.name for f in fields(Request)}
    count = 0
    for entry in catalog:
        directory = ROOT / entry['directory']
        for path in directory.rglob('*.py'):
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    assert not (node.module or '').startswith('scrapfly'), path
                if isinstance(node, ast.Import):
                    assert all(not a.name.startswith('scrapfly') for a in node.names), path
                if isinstance(node, ast.Attribute):
                    assert node.attr not in {'scrape_result','async_scrape','concurrent_scrape','api_response','max_concurrency'}, (path,node.lineno,node.attr)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'Request':
                    assert all(k.arg is None or k.arg in allowed for k in node.keywords), (path,node.lineno)
        module = load_module(directory / entry['module'])
        for name in ('BASE_CONFIG','CLASSIFY_CONFIG'):
            if hasattr(module, name):
                Request('https://example.com', **getattr(module, name))
        for name in entry['functions']:
            assert callable(getattr(module, name)), (entry['directory'], name)
        count += 1
    assert count == 81
    return count


if __name__ == '__main__':
    print(f'{check()} site modules: imports, entry points and request options passed (offline)')
