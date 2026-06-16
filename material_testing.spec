# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置 — 工程材料送检分析系统 V6.1
    pyinstaller material_testing.spec
"""

import sys
from pathlib import Path

_here = Path(SPECPATH)  # spec 文件所在目录

a = Analysis(
    [str(_here / 'main.py')],
    pathex=[],
    binaries=[],
    datas=[
        # QML 文件（扁平化，无子目录）
        (str(_here / 'app' / 'qml'), 'qml'),
        # 应用图标
        (str(_here / 'app_icon.png'), '.'),
        # 标准种子数据
        (str(_here / 'app' / 'database' / 'standards_seed.json'), 'database'),
    ],
    hiddenimports=[
        # QML 引擎内部依赖
        'PySide6.QtQuickControls2',
        'PySide6.QtQml',
        'PySide6.QtCore',
        'PySide6.QtGui',
        # 引擎模块（动态导入）
        'app.engine.dwg_parser',
        'app.engine.pdf_parser',
        'app.engine.word_parser',
        'app.engine.excel_parser',
        'app.engine.ai_agent',
        'app.engine.model_provider',
        'app.engine.qwen_vl',
        'app.engine.file_profiler',
        'app.engine.prompts',
        'app.engine.standards_matcher',
        'app.engine.standards_updater',
        'app.engine.image_preprocess',
        'app.engine.ocr_helper',
        # 报告
        'app.report.report_generator',
        # 数据库
        'app.database.db_manager',
        'app.database.schema',
        # 桥接
        'app.bridge.app_state',
        'app.bridge.theme',
        'app.bridge.theme_tokens',
        'app.bridge.project_model',
        'app.bridge.file_model',
        'app.bridge.section_model',
        'app.bridge.plan_table_model',
        'app.bridge.project_tree_model',
        # 公共模块
        'app.config',
        'app.logger',
        'app.errors',
        # 第三方
        'fitz',  # PyMuPDF
        'ezdxf',
        'pdfplumber',
        'openpyxl',
        'PIL',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 排除不需要的大模块以缩小体积
        'matplotlib',
        'matplotlib.backends',
        'tkinter',
        'unittest',
        'pytest',
        'pip',
        'setuptools',
        'wheel',
        # 测试代码和开发工具
        'tests',
        'installer',
        # 可选依赖（如未安装则忽略）
        'paddleocr',
        'pytesseract',
        'cv2',
        'cairo',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='MaterialTestingTool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # GUI 应用，不显示控制台
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch='x86_64',
    codesign_identity=None,
    entitlements_file=None,
    icon=str(_here / 'app_icon.png'),
)

# 收集所有文件到 onedir 目录
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='MaterialTestingTool',
)
