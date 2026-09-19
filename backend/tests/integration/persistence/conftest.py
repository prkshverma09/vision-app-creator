"""Shared fixtures and skips for the Firestore persistence integration suite."""
import os

import pytest


def _emulator_available() -> tuple[bool, str]:
    if not os.environ.get("FIRESTORE_EMULATOR_HOST"):
        return False, "FIRESTORE_EMULATOR_HOST is not set; Firestore emulator unavailable"
    try:
        from google.cloud import firestore  # noqa: F401
    except ImportError as exc:
        return False, f"google-cloud-firestore is not installed: {exc}"
    return True, ""


@pytest.fixture(scope="session")
def firestore_available() -> tuple[bool, str]:
    return _emulator_available()
