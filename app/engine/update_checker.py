"""
V6.1: GitHub Release 自动更新检查
启动时后台检查 — 发现新版本 → 提示用户下载更新
"""

import time
import logging
from pathlib import Path
from typing import Optional, Dict
import json

logger = logging.getLogger(__name__)

# 默认更新检查配置
GITHUB_API = "https://api.github.com/repos/2537910567/material-testing-app/releases/latest"
CHECK_INTERVAL_HOURS = 24  # 检查间隔，避免频繁请求


def check_for_updates(current_version: str,
                      cache_dir: Optional[Path] = None,
                      force: bool = False) -> Optional[Dict]:
    """
    检查 GitHub Release 是否有新版本。

    Args:
        current_version: 当前版本号（如 "6.1.0"）
        cache_dir: 缓存目录，用于存储上次检查时间
        force: True = 忽略24小时缓存，强制重新请求 (V6.1.2)

    Returns:
        None = 无更新或检查失败
        {"version": "6.2.0", "url": "...", "body": "..."}
    """
    if cache_dir is None:
        cache_dir = Path.home() / ".material_testing_tool"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / "update_check.json"

    # 24小时内不重复检查（force=True 时跳过）
    now = time.time()
    if not force:
        try:
            if cache_file.exists():
                cache = json.loads(cache_file.read_text(encoding="utf-8"))
                if now - cache.get("last_check", 0) < CHECK_INTERVAL_HOURS * 3600:
                    # 返回缓存的检查结果
                    cached = cache.get("cached_result")
                    return cached if cached and _version_newer(cached.get("version", ""), current_version) else None
        except Exception:
            pass

    result = None
    try:
        import requests
        resp = requests.get(
            GITHUB_API,
            headers={"Accept": "application/vnd.github.v3+json",
                     "User-Agent": "MaterialTestingTool-UpdateCheck"},
            timeout=10  # 10秒超时，不影响启动
        )
        if resp.status_code == 200:
            release = resp.json()
            latest = release.get("tag_name", "").lstrip("vV")
            if _version_newer(latest, current_version):
                # 找 .exe 安装包
                download_url = release.get("html_url", "")
                for asset in release.get("assets", []):
                    name = asset.get("name", "")
                    if name.endswith(".exe"):
                        download_url = asset.get("browser_download_url", download_url)
                        break
                result = {
                    "version": latest,
                    "url": download_url,
                    "body": release.get("body", ""),
                }
    except Exception as e:
        logger.debug("update_check: 检查失败 — %s", e)

    # 缓存结果
    try:
        cache_file.write_text(json.dumps({
            "last_check": now,
            "cached_result": result,
        }, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

    return result


def download_update(url: str, dest_path: str,
                    progress_callback=None) -> bool:
    """
    下载更新安装包，支持断点续传和进度回调。

    Args:
        url: 下载地址
        dest_path: 保存路径
        progress_callback: 进度回调 (downloaded_bytes, total_bytes, percentage)

    Returns:
        下载成功/失败
    """
    import requests
    dest = Path(dest_path)
    downloaded = 0

    # 断点续传
    if dest.exists():
        downloaded = dest.stat().st_size

    headers = {"User-Agent": "MaterialTestingTool-UpdateDownload"}
    if downloaded > 0:
        headers["Range"] = f"bytes={downloaded}-"

    try:
        resp = requests.get(url, headers=headers, stream=True, timeout=300)
        if resp.status_code in (200, 206):
            total = downloaded
            if "Content-Length" in resp.headers:
                total = downloaded + int(resp.headers["Content-Length"])

            mode = "ab" if downloaded > 0 else "wb"
            with open(dest_path, mode) as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if progress_callback and total > 0:
                            pct = int(downloaded * 100 / total)
                            progress_callback(downloaded, total, pct)
            return True
    except Exception as e:
        logger.warning("update_check: 下载失败 — %s", e)
    return False


def install_update(installer_path: str, install_dir: str) -> bool:
    """
    静默运行安装包进行原地覆盖升级。

    Args:
        installer_path: 安装包路径
        install_dir: 安装目录

    Returns:
        安装成功/失败
    """
    import subprocess
    try:
        # NSIS 静默安装: /S = silent, /D=安装路径
        cmd = [installer_path, "/S", f"/D={install_dir}"]
        subprocess.run(cmd, check=True, timeout=300)
        return True
    except Exception as e:
        logger.warning("update_check: 安装失败 — %s", e)
        return False


def _version_newer(latest: str, current: str) -> bool:
    """比较版本号，latest > current 返回 True"""
    try:
        l_parts = [int(x) for x in latest.replace("-", ".").split(".")[:3]]
        c_parts = [int(x) for x in current.replace("-", ".").split(".")[:3]]
        while len(l_parts) < 3:
            l_parts.append(0)
        while len(c_parts) < 3:
            c_parts.append(0)
        return l_parts > c_parts
    except Exception:
        return latest != current and len(latest) > 0
