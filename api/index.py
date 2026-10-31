"""Vercel entrypoint: the Django API as a single Python function (vercel.json routes /api/* here)."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
os.environ.setdefault("DJANGO_DEBUG", "false")

from config.wsgi import application as app  # noqa: E402
