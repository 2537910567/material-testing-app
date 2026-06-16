"""
ModelProvider 抽象层 — 封装不同 AI 模型的 API 差异。

V4.8 模型策略：
- DeepSeek V4-Flash：固定文本分析（材料检测 + 送检计划生成）
- Qwen3.7-Plus：所有图纸视觉分析统一使用（百炼平台）
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict, Any, Optional, Callable

import requests

from ..logger import get_logger

logger = get_logger(__name__)

# Model names
QWEN_VL_MODEL = "qwen3.7-plus"          # V4.8: 所有图纸统一用 qwen3.7-plus
DEEPSEEK_TEXT_MODEL = "deepseek-v4-flash"  # 文本分析（固定）


class ModelType(Enum):
    TEXT = "text"
    VISION = "vision"


class ModelProvider(ABC):
    """AI 模型提供者抽象基类"""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """模型名称"""
        ...

    @property
    @abstractmethod
    def model_type(self) -> ModelType:
        """模型类型"""
        ...

    @abstractmethod
    def call(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 32768,
        temperature: float = 0.1,
        timeout: int = 120,
        retries: int = 2,
    ) -> Dict[str, Any]:
        """同步文本 API 调用，自动重试"""
        ...

    @abstractmethod
    def call_with_image(
        self,
        image_data: bytes,
        image_format: str,
        prompt: str,
        timeout: int = 120,
    ) -> Dict[str, Any]:
        """视觉 API 调用（文本模型抛 NotImplementedError）"""
        ...


class DeepSeekProvider(ModelProvider):
    """DeepSeek V4-Flash / V4-Pro API"""

    API_URL = "https://api.deepseek.com/v1/chat/completions"

    def __init__(self, api_key: str, model_name: str = "deepseek-v4-flash"):
        self._api_key = api_key
        self._model_name = model_name
        self._session = requests.Session()  # V5.3: 复用 TCP 连接

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def model_type(self) -> ModelType:
        return ModelType.TEXT

    def call(self, system_prompt, user_prompt, max_tokens=32768,
             temperature=0.1, timeout=120, retries=2):
        import json
        import time
        import requests
        # V5.1: _parse_json_response is now in this module (was in ai_agent)

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }

        t0 = time.time()
        last_error = ""
        for attempt in range(retries + 1):
            try:
                logger.debug("API call (%s): %d prompt chars", self._model_name, len(user_prompt))
                resp = self._session.post(self.API_URL, headers=headers, json=payload, timeout=timeout)
                resp.raise_for_status()
                data = resp.json()
                result = _parse_json_response(data["choices"][0]["message"]["content"])
                usage = data.get("usage", {})
                # V5.2: 附加性能元数据
                result["_meta"] = {
                    "latency_ms": int((time.time() - t0) * 1000),
                    "token_count": usage.get("total_tokens", 0),
                    "retry_count": attempt,
                    "prompt_chars": len(user_prompt),
                    "model": self._model_name,
                }
                return result
            except requests.exceptions.Timeout:
                last_error = "请求超时"
                logger.warning("DeepSeek timeout after %ds (attempt %d/%d)", timeout, attempt + 1, retries + 1)
            except requests.exceptions.ConnectionError:
                last_error = "无法连接"
                logger.error("DeepSeek connection failed")
            except requests.exceptions.HTTPError as e:
                last_error = f"HTTP {e}"
                logger.error("DeepSeek HTTP error: %s", e)
            except Exception as e:
                last_error = str(e)
                logger.exception("DeepSeek unexpected error")

            if attempt < retries:
                wait = 2 ** attempt
                logger.info("Retrying in %ds...", wait)
                time.sleep(wait)

        return {"error": f"DeepSeek API call failed after {retries + 1} attempts: {last_error}",
                "_meta": {"latency_ms": int((time.time() - t0) * 1000), "token_count": 0, "retry_count": retries + 1}}

    def call_with_image(self, image_data, image_format, prompt, timeout=120):
        raise NotImplementedError("DeepSeek does not support vision analysis")


class QwenVLProvider(ModelProvider):
    """Qwen-VL via Alibaba Cloud DashScope API（V4.8: qwen3.7-plus）"""

    API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"

    def __init__(self, api_key: str, model_name: str = QWEN_VL_MODEL):
        self._api_key = api_key
        self._model_name = model_name
        self._session = requests.Session()  # V5.3: 复用 TCP 连接

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def model_type(self) -> ModelType:
        return ModelType.VISION

    def call(self, system_prompt, user_prompt, max_tokens=32768,
             temperature=0.1, timeout=120, retries=2):
        """Text-only call (for completeness; primarily use for vision)"""
        import json
        import time
        import requests

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        last_error = ""
        for attempt in range(retries + 1):
            try:
                resp = self._session.post(self.API_URL, headers=headers, json=payload, timeout=timeout)
                resp.raise_for_status()
                try:
                    data = resp.json()
                except Exception:
                    last_error = "API返回非JSON格式"
                    continue
                try:
                    content = data["choices"][0]["message"]["content"]
                except (KeyError, IndexError, TypeError) as e:
                    last_error = f"API返回格式异常: {e}"
                    continue
                return _parse_json_response(content)  # V5.3: 用 robust parser 替代 json.loads
            except Exception as e:
                last_error = str(e)
                if attempt < retries:
                    time.sleep(2 ** attempt)
        return {"error": last_error}

    def call_with_image(self, image_data, image_format, prompt, timeout=120, retries=2):
        """
        Call Qwen-VL API with one or more images.

        V6.0: 支持单张图片（向后兼容）和多张图片批量发送。
        - image_data: bytes (single) 或 List[Tuple[bytes, str]] (multi)
        - image_format: str (single) 或 None (multi, 每张图自带 format)
        """
        import base64
        import json
        import time
        import requests

        # V6.0: 多图批量模式
        if isinstance(image_data, list):
            return self._call_with_images(image_data, prompt, timeout, retries)

        # ── 单图模式（向后兼容）────────────────────────────────
        image_b64 = base64.b64encode(image_data).decode("utf-8")
        mime = f"image/{image_format}" if image_format != "jpg" else "image/jpeg"

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._model_name,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
                    {"type": "text", "text": prompt},
                ],
            }],
            "max_tokens": 4096,
        }

        t0 = time.time()
        last_error = ""
        for attempt in range(retries + 1):
            try:
                logger.debug("Qwen-VL API call: %d bytes image", len(image_data))
                resp = self._session.post(self.API_URL, headers=headers, json=payload, timeout=timeout)
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                result = _parse_vision_response(content)
                usage = data.get("usage", {})
                result["_meta"] = {
                    "latency_ms": int((time.time() - t0) * 1000),
                    "token_count": usage.get("total_tokens", 0),
                    "retry_count": attempt,
                    "image_bytes": len(image_data),
                    "model": self._model_name,
                }
                return result
            except requests.exceptions.Timeout:
                last_error = "Qwen-VL 请求超时"
                logger.warning("Qwen-VL timeout after %ds (attempt %d/%d)", timeout, attempt + 1, retries + 1)
            except requests.exceptions.ConnectionError:
                last_error = "Qwen-VL 无法连接"
                logger.error("Qwen-VL connection failed")
            except requests.exceptions.HTTPError as e:
                last_error = f"Qwen-VL HTTP {e}"
                logger.error("Qwen-VL HTTP error: %s", e)
            except Exception as e:
                last_error = str(e)
                logger.exception("Qwen-VL unexpected error")

            if attempt < retries:
                wait = 2 ** attempt
                logger.info("Qwen-VL retrying in %ds...", wait)
                time.sleep(wait)

        return {"error": f"Qwen-VL API call failed after {retries + 1} attempts: {last_error}",
                "_meta": {"latency_ms": int((time.time() - t0) * 1000), "token_count": 0, "retry_count": retries + 1}}

    def _call_with_images(self, image_list, prompt, timeout=120, retries=2):
        """
        V6.0: 批量多图 VL API 调用。

        Args:
            image_list: [(image_data: bytes, image_format: str), ...] — 3-5 张一批
            prompt: 文本提示词
            timeout: 超时秒数
            retries: 重试次数

        Returns:
            dict with parsed result and _meta
        """
        import base64
        import time

        # 构建多图 content 数组
        content_parts = []
        total_bytes = 0
        for img_data, img_fmt in image_list:
            image_b64 = base64.b64encode(img_data).decode("utf-8")
            mime = f"image/{img_fmt}" if img_fmt != "jpg" else "image/jpeg"
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{image_b64}"}
            })
            total_bytes += len(img_data)
        content_parts.append({"type": "text", "text": prompt})

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._model_name,
            "messages": [{"role": "user", "content": content_parts}],
            "max_tokens": 8192,  # 多图需要更多 tokens
        }

        t0 = time.time()
        last_error = ""
        for attempt in range(retries + 1):
            try:
                logger.debug("Qwen-VL multi-image call: %d images, %d bytes",
                             len(image_list), total_bytes)
                resp = self._session.post(self.API_URL, headers=headers, json=payload, timeout=timeout)
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                result = _parse_vision_response(content)
                usage = data.get("usage", {})
                result["_meta"] = {
                    "latency_ms": int((time.time() - t0) * 1000),
                    "token_count": usage.get("total_tokens", 0),
                    "retry_count": attempt,
                    "image_bytes": total_bytes,
                    "image_count": len(image_list),
                    "model": self._model_name,
                }
                return result
            except requests.exceptions.Timeout:
                last_error = "Qwen-VL multi-image 请求超时"
                logger.warning("Qwen-VL multi timeout after %ds (attempt %d/%d)", timeout, attempt + 1, retries + 1)
            except requests.exceptions.ConnectionError:
                last_error = "Qwen-VL multi-image 无法连接"
            except requests.exceptions.HTTPError as e:
                last_error = f"Qwen-VL multi HTTP {e}"
                logger.error("Qwen-VL multi HTTP error: %s", e)
            except Exception as e:
                last_error = str(e)
                logger.exception("Qwen-VL multi unexpected error")

            if attempt < retries:
                time.sleep(2 ** attempt)

        return {"error": f"Qwen-VL multi-image failed after {retries + 1} attempts: {last_error}",
                "_meta": {"latency_ms": int((time.time() - t0) * 1000), "token_count": 0}}


def _parse_json_response(content: str) -> Dict[str, Any]:
    """
    容错解析 AI 返回的 JSON（处理 markdown 代码块包裹等情况）。

    V5.1.0: 统一入口 — 从 ai_agent.py 移入，消除重复实现。
    """
    import re
    import json

    # 1. 尝试直接解析
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # 2. 尝试提取 ```json ... ``` 代码块
    match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # 3. 尝试找第一个 { 到最后一个 }
    start = content.find('{')
    end = content.rfind('}')
    if start >= 0 and end > start:
        try:
            return json.loads(content[start:end + 1])
        except json.JSONDecodeError:
            pass

    # 4. 全部失败，检测是否被截断
    open_braces = content.count('{') - content.count('}')
    open_brackets = content.count('[') - content.count(']')
    truncation_hint = ""
    if open_braces > 0 or open_brackets > 0:
        truncation_hint = f" [JSON truncated - open braces: {open_braces}, brackets: {open_brackets}]"
    return {"error": f"AI response not valid JSON ({len(content)} chars). {truncation_hint} First 100: {content[:100]} ...Last 50: {content[-50:]}"}


def _parse_vision_response(content: str) -> Dict[str, Any]:
    """V5.1.0: Delegate to shared _parse_json_response (was duplicated 30-line function)."""
    return _parse_json_response(content)


class ModelProviderFactory:
    """从配置创建 ModelProvider 的工厂类（V6.0: +模型列表获取）"""

    @staticmethod
    def create_text_provider(api_key: str, model_name: str = "deepseek-v4-flash") -> ModelProvider:
        if model_name in ("deepseek-v4-flash", "deepseek-v4-pro"):
            return DeepSeekProvider(api_key, model_name)
        raise ValueError(f"Unknown text model: {model_name}")

    @staticmethod
    def create_vision_provider(api_key: str, model_name: str = QWEN_VL_MODEL) -> ModelProvider:
        return QwenVLProvider(api_key, model_name)

    # ── V6.0: 模型列表获取 ─────────────────────────────────────────

    @staticmethod
    def list_deepseek_models(api_key: str) -> list:
        """V6.0: 从 DeepSeek API 获取可用模型列表。失败回退预定义列表。"""
        import requests
        try:
            resp = requests.get(
                "https://api.deepseek.com/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10,
            )
            resp.raise_for_status()
            models = resp.json().get("data", [])
            if models:
                return models
        except Exception:
            pass
        return [
            {"id": "deepseek-v4-flash"},
            {"id": "deepseek-v4"},
            {"id": "deepseek-chat"},
        ]

    @staticmethod
    def list_qwen_models() -> list:
        """V6.0: Qwen-VL 预定义可用模型列表。"""
        return [
            {"id": "qwen3.7-plus"},
            {"id": "qwen-vl-max"},
            {"id": "qwen-vl-plus"},
            {"id": "qwen2.5-vl-72b-instruct"},
        ]
