"""Shared fixtures for the Marstek tests.

The suite runs against a real Home Assistant installation; see tests/README.md
for how to create the environment.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Make the custom_components directory visible to Home Assistant."""
    yield
