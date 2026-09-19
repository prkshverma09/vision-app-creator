"""Canonical fixture regeneration command."""
import runpy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
runpy.run_path(str(ROOT/"fixtures/generators/generate_synthetic.py"),run_name="__main__")
