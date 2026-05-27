import os
import sys
import pytest

# Ensure the api directory is on sys.path so imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Force test database path before any imports
_test_db_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".test_db")
os.makedirs(_test_db_dir, exist_ok=True)
os.environ["DATABASE_PATH"] = os.path.join(_test_db_dir, "call_me_test.db")
os.environ["JWT_SECRET"] = "test-secret-key-for-testing-32bytes-long"
os.environ["WORKER_INTERNAL_SECRET"] = "test-worker-secret"
os.environ["ADMIN_USERNAME"] = "admin"
os.environ["ADMIN_PASSWORD"] = "admin123"
os.environ["DASHSCOPE_API_KEY"] = "test_dashscope_key"
os.environ["LIVEKIT_URL"] = "https://livekit.example.com"
os.environ["LIVEKIT_API_KEY"] = "test_api_key"
os.environ["LIVEKIT_API_SECRET"] = "test_api_secret"
os.environ["SEED_BUILTIN_VOICES"] = "Cherry"
os.environ["SEED_TTS_FLASH_MODEL"] = "qwen3-tts-flash-realtime"
os.environ["DEFAULT_LLM_MODEL"] = "qwen-plus"


@pytest.fixture(autouse=True)
def clean_db():
    """Remove and reinitialize the test database for each test."""
    db_path = os.environ["DATABASE_PATH"]
    if os.path.exists(db_path):
        os.remove(db_path)
    from database import init_db
    init_db()
    yield
    if os.path.exists(db_path):
        os.remove(db_path)
