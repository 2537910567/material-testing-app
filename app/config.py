"""
应用程序配置管理（V4.5.1）
API Key 使用 Windows DPAPI 加密存储，绑定当前 Windows 用户身份。
"""

import base64
import json
from pathlib import Path
from typing import Optional


try:
    import ctypes
    import ctypes.wintypes

    class _DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", ctypes.wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    _CRYPTPROTECT_UI_FORBIDDEN = 0x01
    _HAS_DPAPI = True
except Exception:
    _HAS_DPAPI = False


def _encrypt_key(plaintext: str) -> str:
    """Windows DPAPI 加密 → base64 输出。非 Windows 环境返回原文。"""
    if not plaintext:
        return ""
    if not _HAS_DPAPI:
        return plaintext
    try:
        data = plaintext.encode("utf-16-le")
        buf = (ctypes.c_char * len(data)).from_buffer_copy(data)
        blob_in = _DATA_BLOB(len(data), buf)
        blob_out = _DATA_BLOB()
        ret = ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(blob_in), None, None, None, None,
            _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out),
        )
        if not ret:
            return ""
        encrypted = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)
        return base64.b64encode(encrypted).decode("ascii")
    except Exception:
        return ""


def _decrypt_key(encrypted_b64: str) -> str:
    """base64 DPAPI 密文解密。非 Windows 环境直接返回输入。"""
    if not encrypted_b64:
        return ""
    if not _HAS_DPAPI:
        return encrypted_b64
    try:
        encrypted = base64.b64decode(encrypted_b64)
    except Exception:
        return ""
    try:
        buf = (ctypes.c_char * len(encrypted)).from_buffer_copy(encrypted)
        blob_in = _DATA_BLOB(len(encrypted), buf)
        blob_out = _DATA_BLOB()
        ret = ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), None, None, None, None,
            _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out),
        )
        if not ret:
            return ""
        decrypted = ctypes.string_at(blob_out.pbData, blob_out.cbData)
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)
        return decrypted.decode("utf-16-le")
    except Exception:
        return ""


class AppConfig:
    """应用程序配置（API Key 经 DPAPI 加密存储）"""

    def __init__(self):
        self.config_dir = Path.home() / ".material_testing_tool"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.config_dir / "config.json"
        self._config = self._load()

    def _load(self) -> dict:
        """加载配置"""
        if self.config_file.exists():
            try:
                return json.loads(self.config_file.read_text(encoding="utf-8"))
            except Exception:
                return {}
        return {}

    def _save(self):
        """保存配置"""
        self.config_file.write_text(
            json.dumps(self._config, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )

    @property
    def api_key(self) -> str:
        """获取 DeepSeek API Key（自动解密存储的密文，兼容旧版明文）"""
        enc = self._config.get("api_key_enc", "")
        if enc:
            return _decrypt_key(enc) or ""
        # 回退：旧版明文存储（V4.5.0 及之前）
        legacy = self._config.get("api_key", "")
        if legacy:
            return legacy
        # 回退：更旧的 api_key.txt（V4.0 及之前）
        legacy_file = self.config_dir / "api_key.txt"
        if legacy_file.exists():
            return legacy_file.read_text().strip()
        return ""

    @api_key.setter
    def api_key(self, value: str):
        """设置 DeepSeek API Key（加密后存储）"""
        if value:
            self._config["api_key_enc"] = _encrypt_key(value)
        else:
            self._config["api_key_enc"] = ""
        # 清除旧版明文存储
        self._config.pop("api_key", None)
        legacy_file = self.config_dir / "api_key.txt"
        if legacy_file.exists():
            legacy_file.unlink()
        self._save()

    @property
    def last_project_dir(self) -> Optional[str]:
        return self._config.get("last_project_dir")

    @last_project_dir.setter
    def last_project_dir(self, value: str):
        self._config["last_project_dir"] = value
        self._save()

    @property
    def output_dir(self) -> str:
        return self._config.get("output_dir", str(Path.home() / "Desktop"))

    @output_dir.setter
    def output_dir(self, value: str):
        self._config["output_dir"] = value
        self._save()

    @property
    def log_dir(self) -> str:
        return self._config.get("log_dir", str(self.config_dir / "logs"))

    @log_dir.setter
    def log_dir(self, value: str):
        self._config["log_dir"] = value
        self._save()

    @property
    def temp_dir(self) -> str:
        return self._config.get("temp_dir", str(self.config_dir / "temp"))

    @temp_dir.setter
    def temp_dir(self, value: str):
        self._config["temp_dir"] = value
        self._save()

    # ===== V4.1 multi-model settings =====
    # DeepSeek 固定使用 deepseek-v4-flash，无需切换
    # Qwen-VL 模型由程序根据文件名自动选择（断面→8b-thinking，平面→4b-instruct）

    @property
    def qwen_api_key(self) -> str:
        """Qwen-VL (DashScope) API Key（自动解密）"""
        enc = self._config.get("qwen_api_key_enc", "")
        if enc:
            return _decrypt_key(enc) or ""
        return self._config.get("qwen_api_key", "")

    @qwen_api_key.setter
    def qwen_api_key(self, value: str):
        """Qwen-VL (DashScope) API Key（加密后存储）"""
        if value:
            self._config["qwen_api_key_enc"] = _encrypt_key(value)
        else:
            self._config["qwen_api_key_enc"] = ""
        self._config.pop("qwen_api_key", None)
        self._save()

    @property
    def theme_mode(self) -> str:
        """V5.2: 主题模式 "light" | "dark" """
        return self._config.get("theme_mode", "light")

    @theme_mode.setter
    def theme_mode(self, value: str):
        self._config["theme_mode"] = value
        self._save()

    # ===== V6.0: 模型手动切换 =====

    @property
    def deepseek_model(self) -> str:
        """当前选择的 DeepSeek 模型（默认 deepseek-v4-flash）"""
        return self._config.get("deepseek_model", "deepseek-v4-flash")

    @deepseek_model.setter
    def deepseek_model(self, value: str):
        self._config["deepseek_model"] = value or "deepseek-v4-flash"
        self._save()

    @property
    def qwen_model(self) -> str:
        """当前选择的 Qwen-VL 模型（默认 qwen3.7-plus）"""
        return self._config.get("qwen_model", "qwen3.7-plus")

    @qwen_model.setter
    def qwen_model(self, value: str):
        self._config["qwen_model"] = value or "qwen3.7-plus"
        self._save()
