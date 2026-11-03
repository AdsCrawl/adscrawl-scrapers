"""Offline checks for the validation and acceptance harness.

These tests do not call AdsCrawl and do not require ADSCRAWL_API_KEY.
"""
import ast
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _site_test_files():
    return sorted(ROOT.glob('*-scraper/test.py'))


def _declared_tests(path: Path) -> int:
    tree = ast.parse(path.read_text(), filename=str(path))
    return sum(
        1 for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith('test_')
    )


def test_every_site_acceptance_module_collects_in_one_session():
    """Same-named test.py modules must not abort the acceptance run.

    Pytest's default prepend importer registers every file as the module
    ``test``. The second site then raises import-file mismatch and the process
    exits 2 (interrupted) or 4 (usage error) before those tests can run, so a
    batch acceptance run mis-classifies every site after the first.
    """
    files = _site_test_files()
    assert len(files) == 81
    expected = sum(_declared_tests(path) for path in files)
    assert expected > 81
    completed = subprocess.run(
        [sys.executable, '-m', 'pytest', '--collect-only', '-q', '--tb=line', '-p', 'no:cacheprovider',
         *[str(path) for path in files]],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, 'PYTEST_ADDOPTS': ''},
    )
    output = completed.stdout + completed.stderr
    assert completed.returncode == 0, output
    assert 'import file mismatch' not in output
    assert f'{expected} tests collected' in output


def test_site_directories_collect_from_the_repository_root():
    """``pytest amazon-scraper`` must see that directory's test.py.

    Each site config sets ``python_files = "test.py"``, but a run whose rootdir
    is the repository uses the root config only. The default pattern ignores
    ``test.py``, so the command collects nothing and exits 5.
    """
    completed = subprocess.run(
        [sys.executable, '-m', 'pytest', '--collect-only', '-q', '-p', 'no:cacheprovider',
         'amazon-scraper', 'bing-scraper'],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, 'PYTEST_ADDOPTS': ''},
    )
    output = completed.stdout + completed.stderr
    assert completed.returncode == 0, output
    assert 'amazon-scraper/test.py::test_product_scraping' in output
    assert 'bing-scraper/test.py::test_serp_scraping' in output


def test_offline_acceptance_checks_from_different_sites_run_together():
    completed = subprocess.run(
        [sys.executable, '-m', 'pytest', '-q', '--tb=short', '-p', 'no:cacheprovider',
         'glassdoor-scraper/test.py::test_glassdoor_url',
         'glassdoor-scraper/test.py::test_salary_range_parsing',
         'autoscout24-scraper/test.py::test_page_url'],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, 'PYTEST_ADDOPTS': ''},
    )
    output = completed.stdout + completed.stderr
    assert completed.returncode == 0, output
    assert '3 passed' in output


def test_smoke_missing_key_is_a_precondition_failure(monkeypatch):
    monkeypatch.delenv('ADSCRAWL_API_KEY', raising=False)
    completed = subprocess.run(
        [sys.executable, str(ROOT / 'scripts' / 'smoke.py')],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={key: value for key, value in os.environ.items() if key != 'ADSCRAWL_API_KEY'},
    )
    assert completed.returncode == 2, completed.stdout + completed.stderr
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert payload['status'] == 'failed'
    assert payload['code'] == 'MISSING_API_KEY'
    assert payload['error_type'] != 'TypeError'
    assert 'ADSCRAWL_API_KEY' not in completed.stdout


def test_live_test_usage_errors_do_not_look_like_test_failures():
    missing = subprocess.run(
        [sys.executable, str(ROOT / 'scripts' / 'live_test.py')],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={key: value for key, value in os.environ.items() if key not in {'ADSCRAWL_API_KEY', 'SELECTED_SCRAPER'}},
    )
    assert missing.returncode == 2
    assert 'SELECTED_SCRAPER' in missing.stderr

    unknown = subprocess.run(
        [sys.executable, str(ROOT / 'scripts' / 'live_test.py')],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, 'SELECTED_SCRAPER': 'not-a-site', 'ADSCRAWL_API_KEY': ''},
    )
    assert unknown.returncode == 2
    assert 'catalog.json' in unknown.stderr

    no_key = subprocess.run(
        [sys.executable, str(ROOT / 'scripts' / 'live_test.py')],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={key: value for key, value in os.environ.items() if key != 'ADSCRAWL_API_KEY'} | {'SELECTED_SCRAPER': 'bing-scraper'},
    )
    assert no_key.returncode == 2
    assert 'ADSCRAWL_API_KEY' in no_key.stderr
    assert 'TypeError' not in no_key.stdout + no_key.stderr
    assert 'ADSCRAWL_DEFAULT_COUNTRY' not in no_key.stderr


def _live_test_module():
    spec = importlib.util.spec_from_file_location('live_test_harness', ROOT / 'scripts' / 'live_test.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_live_child_defaults_blank_country_to_us(monkeypatch):
    monkeypatch.delenv('ADSCRAWL_DEFAULT_COUNTRY', raising=False)
    assert _live_test_module().child_environment()['ADSCRAWL_DEFAULT_COUNTRY'] == 'US'
    monkeypatch.setenv('ADSCRAWL_DEFAULT_COUNTRY', '  ')
    assert _live_test_module().child_environment()['ADSCRAWL_DEFAULT_COUNTRY'] == 'US'


def test_live_child_keeps_explicit_country(monkeypatch):
    monkeypatch.setenv('ADSCRAWL_DEFAULT_COUNTRY', ' gb ')
    assert _live_test_module().child_environment()['ADSCRAWL_DEFAULT_COUNTRY'] == 'GB'
