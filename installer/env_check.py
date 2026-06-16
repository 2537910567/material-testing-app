"""
V6.1: 安装前环境检测
用法: py -3 env_check.py [all|odafc|vcredist|space|admin]
返回: JSON
"""

import sys, os, json, ctypes, winreg, shutil
from pathlib import Path


def check_vcredist() -> dict:
    keys = [
        r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64",
        r"SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64",
    ]
    for subkey in keys:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, subkey) as k:
                v, _ = winreg.QueryValueEx(k, "Installed")
                if v == 1:
                    return {"ok": True, "message": "VC++ Redist 已安装"}
        except Exception:
            pass
    return {"ok": False, "message": "需要安装 VC++ Redist"}


def check_odafc() -> dict:
    for base in [r"C:\Program Files\ODA", r"C:\Program Files (x86)\ODA"]:
        if os.path.isdir(base):
            for d in os.listdir(base):
                exe = os.path.join(base, d, "ODAFileConverter.exe")
                if os.path.isfile(exe):
                    return {"ok": True, "message": f"ODAFC 已安装: {exe}"}
    oda = shutil.which("ODAFileConverter.exe")
    if oda:
        return {"ok": True, "message": f"ODAFC 在 PATH: {oda}"}
    return {"ok": False, "message": "需要安装 ODA File Converter"}


def check_disk_space(min_gb: int = 3) -> dict:
    try:
        drive = os.path.splitdrive(os.path.expandvars(r"%ProgramFiles%"))[0] + "\\"
        free = ctypes.c_ulonglong(0)
        total = ctypes.c_ulonglong(0)
        ctypes.windll.kernel32.GetDiskFreeSpaceExW(
            ctypes.c_wchar_p(drive), None, ctypes.pointer(total), ctypes.pointer(free))
        free_gb = free.value / (1024**3)
        if free_gb >= min_gb:
            return {"ok": True, "message": f"磁盘空间充足 ({free_gb:.1f}GB)"}
        return {"ok": False, "message": f"磁盘空间不足: 需{min_gb}GB, 仅{free_gb:.1f}GB"}
    except Exception as e:
        return {"ok": False, "message": f"磁盘检测失败: {e}"}


def check_admin() -> dict:
    try:
        ok = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        ok = False
    return {"ok": ok, "message": "管理员权限 OK" if ok else "建议管理员运行"}


def check_all() -> list:
    return [
        {"name": "admin", **check_admin()},
        {"name": "space", **check_disk_space()},
        {"name": "vcredist", **check_vcredist()},
        {"name": "odafc", **check_odafc()},
    ]


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    fn = {"admin": check_admin, "space": check_disk_space,
          "vcredist": check_vcredist, "odafc": check_odafc,
          "all": check_all}.get(cmd)
    if fn:
        print(json.dumps(fn(), ensure_ascii=False, indent=2))
