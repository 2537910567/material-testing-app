"""
V5.2.0: 结构化异常层级

替代裸 except Exception 的通用捕获，为错误日志提供结构化信息。
"""


class AppError(Exception):
    """应用根异常 — 所有自定义异常的基类"""
    def __init__(self, message: str, code: str = "UNKNOWN",
                 file_id: int = None, project_id: str = None,
                 phase: str = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.file_id = file_id
        self.project_id = project_id
        self.phase = phase  # "import" | "profile" | "conversion" | "analysis" | "export"

    def to_dict(self) -> dict:
        d = {"error_code": self.code, "message": self.message}
        if self.file_id is not None:
            d["file_id"] = self.file_id
        if self.project_id is not None:
            d["project_id"] = self.project_id
        if self.phase is not None:
            d["phase"] = self.phase
        return d

    def __str__(self):
        parts = [f"[{self.code}]"]
        if self.phase:
            parts.append(f"({self.phase})")
        parts.append(f" {self.message}")
        return "".join(parts)


class ConversionError(AppError):
    """转换阶段错误 — ODAFC 失败、渲染失败、超时等"""
    def __init__(self, message: str, code: str = "CONV_ERROR",
                 file_id: int = None, project_id: str = None):
        super().__init__(message, code, file_id, project_id, "conversion")


class AnalysisError(AppError):
    """AI 分析阶段错误 — API 调用失败、JSON 解析失败等"""
    def __init__(self, message: str, code: str = "ANALYSIS_ERROR",
                 file_id: int = None, project_id: str = None):
        super().__init__(message, code, file_id, project_id, "analysis")


class APIError(AppError):
    """API 通信错误 — 超时、认证失败、限流等"""
    def __init__(self, message: str, code: str = "API_ERROR",
                 provider: str = None, status_code: int = None):
        super().__init__(message, code, phase="analysis")
        self.provider = provider
        self.status_code = status_code


class ParseError(AppError):
    """文件解析错误 — DWG/PDF/DOCX/XLSX 解析失败"""
    def __init__(self, message: str, code: str = "PARSE_ERROR",
                 file_id: int = None, project_id: str = None):
        super().__init__(message, code, file_id, project_id, "import")


class ConfigError(AppError):
    """配置错误 — API Key 缺失、路径不存在等"""
    def __init__(self, message: str, code: str = "CONFIG_ERROR"):
        super().__init__(message, code, phase="init")
