"""
性能测试工具 — 计时器 + 资源监控 + 数据收集
"""

import time
import os
import json
import threading
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import Optional, Callable

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


# ── 性能测量 ─────────────────────────────────────────────────────────


@dataclass
class PerfMeasurement:
    """单次性能测量结果"""
    test_id: str
    operation: str
    file_path: str = ""
    file_size_mb: float = 0.0
    file_type: str = ""
    duration_ms: float = 0.0
    strategy: str = ""
    peak_memory_mb: float = 0.0
    cpu_percent: float = 0.0
    output_count: Optional[int] = None
    output_size_mb: Optional[float] = None
    error: Optional[str] = None
    notes: str = ""


class PerfTimer:
    """高精度性能计时器(上下文管理器)"""

    def __init__(self, label: str = ""):
        self._start = None
        self._mem_start = None
        self._cpu_start = None
        self._proc = psutil.Process(os.getpid()) if HAS_PSUTIL else None
        self.label = label
        self.duration_ms = 0.0
        self.memory_delta = 0.0
        self.peak_memory = 0.0

    def __enter__(self):
        self._start = time.perf_counter()
        if self._proc:
            self._mem_start = self._proc.memory_info().rss / (1024 * 1024)
        return self

    def __exit__(self, *args):
        self.duration_ms = (time.perf_counter() - self._start) * 1000
        if self._proc:
            self.peak_memory = self._proc.memory_info().rss / (1024 * 1024)
            self.memory_delta = self.peak_memory - (self._mem_start or self.peak_memory)


def get_file_size_mb(path: str) -> float:
    """获取文件大小(MB)"""
    try:
        return Path(path).stat().st_size / (1024 * 1024)
    except Exception:
        return 0.0


# ── 资源监控守护线程 ─────────────────────────────────────────────────


class ResourceSample:
    """资源采样点"""
    __slots__ = ("timestamp", "cpu_pct", "mem_rss_mb", "mem_vms_mb",
                 "disk_read_mb", "disk_write_mb", "handles", "threads")

    def __init__(self, ts, cpu, mem_rss, mem_vms, disk_r, disk_w, hnd, thr):
        self.timestamp = ts
        self.cpu_pct = cpu
        self.mem_rss_mb = mem_rss
        self.mem_vms_mb = mem_vms
        self.disk_read_mb = disk_r
        self.disk_write_mb = disk_w
        self.handles = hnd
        self.threads = thr


class ResourceMonitor:
    """后台资源监控 daemon，每 0.5s 采样一次"""

    def __init__(self, interval: float = 0.5):
        self._interval = interval
        self._samples = []
        self._running = False
        self._thread = None
        self._process = psutil.Process(os.getpid()) if HAS_PSUTIL else None
        self._disk_start = None
        if HAS_PSUTIL:
            self._disk_start = psutil.disk_io_counters()

    def start(self):
        if not HAS_PSUTIL:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
        return self.get_report()

    def _loop(self):
        while self._running:
            try:
                cpu = self._process.cpu_percent() if self._process else 0
                mem = self._process.memory_info()
                disk = psutil.disk_io_counters()
                ds = self._disk_start
                self._samples.append(ResourceSample(
                    ts=time.time(),
                    cpu_pct=cpu,
                    mem_rss_mb=mem.rss / (1024 * 1024),
                    mem_vms_mb=mem.vms / (1024 * 1024),
                    disk_read_mb=(disk.read_bytes - ds.read_bytes) / (1024 * 1024) if ds else 0,
                    disk_write_mb=(disk.write_bytes - ds.write_bytes) / (1024 * 1024) if ds else 0,
                    hnd=self._process.num_handles() if self._process else 0,
                    thr=self._process.num_threads() if self._process else 0,
                ))
            except Exception:
                pass
            time.sleep(self._interval)

    def get_report(self) -> dict:
        """生成资源监控报告"""
        if not self._samples:
            return {"error": "No samples collected"}
        samples = self._samples
        mem_rss = [s.mem_rss_mb for s in samples]
        cpus = [s.cpu_pct for s in samples]
        handles = [s.handles for s in samples]
        threads = [s.threads for s in samples]
        disk_w = [s.disk_write_mb for s in samples]

        # 内存泄漏检测: 最后30秒的斜率
        leak = self._detect_leak(mem_rss)

        return {
            "duration_s": round(samples[-1].timestamp - samples[0].timestamp, 1),
            "sample_count": len(samples),
            "memory": {
                "peak_mb": round(max(mem_rss), 1),
                "avg_mb": round(sum(mem_rss) / len(mem_rss), 1),
                "start_mb": round(mem_rss[0], 1) if mem_rss else 0,
                "end_mb": round(mem_rss[-1], 1) if mem_rss else 0,
                "leak_mb_per_min": leak,
            },
            "cpu": {
                "peak_pct": round(max(cpus), 1),
                "avg_pct": round(sum(cpus) / len(cpus), 1) if cpus else 0,
            },
            "handles": {
                "peak": max(handles),
                "leak_per_min": self._detect_leak(handles),
            },
            "threads": {
                "peak": max(threads),
                "avg": round(sum(threads) / len(threads), 1) if threads else 0,
            },
            "disk_write_mb": round(disk_w[-1] - disk_w[0], 1) if len(disk_w) > 1 else 0,
        }

    def _detect_leak(self, values: list, window_seconds: int = 30) -> float:
        """检测资源泄漏: 返回 MB/min 斜率"""
        if len(values) < 5:
            return 0.0
        recent = values[-min(len(values), max(5, int(window_seconds / self._interval))):]
        n = len(recent)
        if n < 3:
            return 0.0
        xs = list(range(n))
        sx = sum(xs)
        sy = sum(recent)
        sxx = sum(x * x for x in xs)
        sxy = sum(x * y for x, y in zip(xs, recent))
        slope = (n * sxy - sx * sy) / (n * sxx - sx * sx) if (n * sxx - sx * sx) else 0
        return round(slope * (60.0 / self._interval), 2)


# ── 结果收集 ─────────────────────────────────────────────────────────


class TestResults:
    """测试结果收集器"""

    def __init__(self, dimension: str, description: str = ""):
        self.dimension = dimension
        self.description = description
        self.timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        self.results = []
        self.perf_measurements = []

    def add(self, test_id: str, name: str, passed: bool,
            duration_ms: float = 0, error: str = "", details: dict = None):
        self.results.append({
            "id": test_id, "name": name, "passed": passed,
            "duration_ms": round(duration_ms, 1), "error": error,
            "details": details or {},
        })

    def add_perf(self, m: PerfMeasurement):
        self.perf_measurements.append(asdict(m))

    @property
    def summary(self) -> dict:
        total = len(self.results)
        passed = sum(1 for r in self.results if r["passed"])
        failed = total - passed
        return {
            "dimension": self.dimension,
            "description": self.description,
            "timestamp": self.timestamp,
            "total": total,
            "passed": passed,
            "failed": failed,
            "pass_rate_pct": round(passed / total * 100, 1) if total else 0,
            "avg_duration_ms": round(sum(r["duration_ms"] for r in self.results) / total, 1) if total else 0,
            "failures": [r for r in self.results if not r["passed"]],
        }

    def save(self, path: str):
        import tempfile as _tf
        report = self.summary
        report["results"] = self.results
        report["perf_measurements"] = self.perf_measurements
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            return path
        except (OSError, PermissionError):
            fb = os.path.join(_tf.gettempdir(), os.path.basename(path))
            with open(fb, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            print(f"[fallback] 结果保存到: {fb}")
            return fb
