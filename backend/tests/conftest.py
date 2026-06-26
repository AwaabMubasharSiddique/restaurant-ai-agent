import pytest

from tools import store


@pytest.fixture(autouse=True)
def clean_store():
    store.get_supabase.cache_clear()
    store._MEMORY.clear()
    yield
    store._MEMORY.clear()
