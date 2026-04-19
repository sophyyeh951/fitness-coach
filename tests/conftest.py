import pytest
from unittest.mock import patch

@pytest.fixture
def mock_supabase():
    """Mock Supabase client for unit tests."""
    with patch("app.db.client.supabase") as mock:
        yield mock
