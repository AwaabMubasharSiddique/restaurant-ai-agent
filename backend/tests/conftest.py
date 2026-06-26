"""Test fixtures.

These tests are fully offline: they exercise the pure logic (slot-counting,
persistence fallback, schema validation) with no OpenAI key and no Supabase.
With SUPABASE_URL/KEY unset, tools.store uses its in-memory backend, which we
reset around every test.
"""
import pytest

from tools import store


@pytest.fixture(autouse=True)
def clean_store():
    store.get_supabase.cache_clear()  # ensure we resolve the backend fresh
    store._MEMORY.clear()
    yield
    store._MEMORY.clear()
