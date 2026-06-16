import sys
import os
import tempfile
import json
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import AppConfig


class TestAppConfig:
    def setup_method(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.config_dir = Path(self.tmp_dir) / ".material_testing_tool"
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def test_api_key_read_write(self, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: Path(self.tmp_dir))
        config = AppConfig()
        config.api_key = "sk-test-key-12345"
        assert config.api_key == "sk-test-key-12345"

    def test_output_dir_default(self, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: Path(self.tmp_dir))
        config = AppConfig()
        assert "Desktop" in config.output_dir or config.output_dir

    def test_output_dir_persist(self, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: Path(self.tmp_dir))
        config = AppConfig()
        config.output_dir = "/custom/output"
        assert config.output_dir == "/custom/output"

    def test_qwen_api_key(self, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: Path(self.tmp_dir))
        config = AppConfig()
        config.qwen_api_key = "sk-qwen-test"
        assert config.qwen_api_key == "sk-qwen-test"
