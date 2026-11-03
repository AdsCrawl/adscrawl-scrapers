"""Make site acceptance modules importable in one pytest session.

importlib mode (see pyproject.toml) keeps each ``test.py`` from colliding with
the others. Those modules still do ``import amazon`` / ``import glassdoor``
from their own directory, which is not a package on the default path.
"""
from __future__ import annotations

import sys
from pathlib import Path


def pytest_configure(config):
    root = Path(config.rootpath)
    for directory in sorted(path for path in root.iterdir() if path.is_dir() and path.name.endswith("-scraper")):
        location = str(directory)
        if location not in sys.path:
            sys.path.append(location)
