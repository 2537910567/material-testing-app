# 🏗️ 工程材料送检分析系统 V6.1.3

> 基于 AI 的智能送检计划生成工具 — CAD/PDF 图纸解析 + DeepSeek 文本分析 + Qwen-VL 视觉分析 → 合规 Excel 送检计划

[![Windows](https://img.shields.io/badge/Platform-Windows%2010%2F11-blue)](https://github.com/2537910567/material-testing-app/releases)
[![Python](https://img.shields.io/badge/Python-3.12-green)](https://www.python.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)
[![Release](https://img.shields.io/badge/Release-v6.1.3-brightgreen)](https://github.com/2537910567/material-testing-app/releases/latest)

---

## 📖 目录

- [功能特性](#-功能特性)
- [系统要求](#-系统要求)
- [安装指南](#-安装指南)
- [使用教程](#-使用教程)
- [技术架构](#-技术架构)
- [性能数据](#-性能数据)
- [开发指南](#-开发指南)
- [更新日志](#-更新日志)
- [常见问题](#-常见问题)
- [免责声明](#-免责声明)

---

## ✨ 功能特性

### 文件支持
| 格式 | 说明 |
|------|------|
| 🟦 **DWG / DXF** | AutoCAD 图纸，自动转换 → 文本提取 + 渲染为 PNG |
| 🟥 **PDF** | 施工图 PDF，按页类型智能分类（文字页/图纸页/扫描页），按类型分 DPI 渲染 |
| 📝 **Word (.docx)** | 设计说明文档，提取全量文本 |
| 📊 **Excel (.xlsx)** | 检测计划表、材料清单，提取表格数据 |

### AI 分析管线
| 阶段 | 模型 | 功能 |
|------|------|------|
| 🔍 **Vision 分析** | Qwen-VL (qwen3.7-plus) | 横断面/平面图识别，5线程并行 |
| 🧠 **文本分析** | DeepSeek (deepseek-v4-flash) | 多轮分步分析：结构检测 → 材料分析，Few-Shot 按专业分组 |
| 📚 **标准匹配** | 91本预置标准库 | 关键词匹配 Top-5，自动注入 Prompt |

### 输出
- 📄 **Excel 3-4 Sheet**：封面 + 送检计划(17列) + 施工工序流程(12列) + 施工步骤明细
- 📊 按路段分组，交替行色，自动宽度，专业排版

---

## 💻 系统要求

| 项目 | 最低配置 | 推荐配置 |
|------|---------|---------|
| 操作系统 | Windows 10 (64-bit) | Windows 11 (64-bit) |
| 内存 | 4 GB | 8 GB+ |
| 磁盘空间 | 3 GB | 5 GB+ |
| 网络 | 宽带 (AI分析) | 宽带 |
| 额外依赖 | VC++ Redist 2015-2022 | ODA File Converter 27.x (安装包自动安装) |

---

## 📥 安装指南

### 方式一：安装包（推荐）

1. 从 [Releases](https://github.com/2537910567/material-testing-app/releases/latest) 下载 `MaterialTestingTool-Setup-vX.X.X.exe`
2. 双击运行，选择安装路径
3. 安装程序自动检测并安装：
   - ✅ Visual C++ Redistributable 2015-2022（自动静默安装）
   - ✅ ODA File Converter 27.1（自动静默安装）
4. 桌面和开始菜单自动创建快捷方式

### 方式二：源码运行（开发者）

```bash
git clone https://github.com/2537910567/material-testing-app.git
cd material-testing-app
pip install -r requirements.txt
py -3 main.py
```

需自行安装 [ODA File Converter](https://www.opendesign.com/guestfiles/oda_file_converter)。

### 配置 API Key

| Key | 用途 | 获取地址 |
|-----|------|---------|
| DeepSeek | 文本分析 | [platform.deepseek.com](https://platform.deepseek.com/api_keys) |
| Qwen-VL | 视觉分析 | [dashscope.console.aliyun.com](https://dashscope.console.aliyun.com/apiKey) |

> 🔒 API Key 使用 Windows DPAPI 加密存储（`~/.material_testing_tool/config.json`），绑定当前 Windows 用户身份，其他用户无法解密。

---

## 📝 使用教程

```
创建项目 → 导入文件 → 开始转换 → AI 分析 → 导出 Excel
```

### 1. 创建项目
点击工具栏 **"新建项目"**，输入项目名称。

### 2. 导入文件
拖拽或选择 DWG/PDF/Word/Excel 文件。混合导入时自动判断 CAD+PDF 策略。

### 3. 开始转换
```
Phase 0: 文件预分析（自动判断 PDF 页类型 + CAD 复杂度）
Phase 1: 策略转换（PDF → 文字+表格+PNG，CAD → DXF 文字+可选手动渲染）
```
大文件经验值：183MB/224页 PDF ≈ 8.5 分钟，15MB DWG ≈ 48秒。

### 4. AI 分析
```
Phase 2-1: Qwen-VL 视觉分析（5线程并行）
Phase 2-2: DeepSeek 文本分析（智能分片 + 标准匹配 + Few-Shot）
Phase 2-3: 后端处理去重 + 桩号精度修正
```

### 5. 导出 Excel
生成 3-4 个 Sheet，含送检计划 + 工序流程 + 施工步骤明细。

---

## 🏛️ 技术架构

```
QML UI Layer (7 components, 2731 lines)
    ↕ Signals/Slots
Bridge Layer (AppState singleton, 6 QThread workers, 5 Models, ThemeEngine)
    ↕ Direct calls
Engine Layer (Parsers + AI + Pre-analysis)
    ↕ SQLite WAL
Database Layer (11 tables, V1→V13 migration, 91 seed standards)

Data Flow:
  DWG/PDF/Word/Excel → FileProfiler → StrategyConversion
    → Vision Analysis (Qwen-VL ×5) + Text Analysis (DeepSeek multi-pass)
      → Dedup + Station Fix → Excel Export (3-4 sheets)
```

| 技术 | 用途 |
|------|------|
| Python 3.12 | 主语言 |
| PySide6 / QML | GUI 框架 |
| PyMuPDF (fitz) | PDF 解析/渲染/表格提取 |
| ezdxf | DXF 解析 |
| ODA File Converter | DWG→DXF 转换 |
| DeepSeek API | 大模型文本分析 |
| Qwen-VL API | 视觉模型图纸分析 |
| SQLite (WAL) | 本地数据存储 |
| PyInstaller | 打包 exe |
| NSIS | 安装包制作 |
| GitHub Actions | CI/CD 自动构建 |

---

## 📊 性能数据

| 场景 | 文件 | 耗时 | 内存 | 产出 |
|------|------|------|------|------|
| 超大 PDF | 183MB / 224页 | 8.5 min | 373 MB | 195 PNG + 35 表格 |
| 大 PDF | 91MB / 104页 | 8.4 min | 628 MB | 94 PNG + 17 表格 |
| 中 PDF | 67MB / 79页 | 7.2 min | 777 MB | 62 PNG + 10 表格 |
| 大 DWG | 15.2 MB | 48 s | 392 MB | 35,229 实体 |
| 中 DWG | 7.2 MB | 19 s | 383 MB | 2,028 实体 |

> 以上数据来自某市政道路项目实际测试（2026-06-16）。表格提取使用 PyMuPDF `find_tables()`，内存较 pdfplumber 降低 97%。

---

## 🛠️ 开发指南

```bash
# 安装依赖
pip install -r material-testing-app/requirements.txt

# 运行应用
cd material-testing-app && py -3 main.py

# 运行测试（130个用例）
cd material-testing-app && py -3 -B -m pytest tests/ -v

# 打包 exe
py -3 -m PyInstaller material_testing.spec \
  --distpath "C:/Users/Administrator/Desktop/dist" \
  --workpath "%TEMP%/pyinstaller_build" --noconfirm

# 编译安装包（需 NSIS + redist 目录含 vc_redist.x64.exe 和 ODAFC_Setup.msi）
cd /tmp && iconv -f UTF-8 -t GBK installer/installer.nsi > install.nsi && makensis install.nsi
```

项目结构见 [CLAUDE.md](CLAUDE.md)。

---

## 📋 更新日志

| 版本 | 主要更新 |
|------|---------|
| **V6.1.3** | 修复手动检查更新 24h 缓存拦截 + force=True 绕过缓存 |
| **V6.1.2** | 集成 ODAFC + VC Redist 到安装包 + 修复静默失败 + 导入错误可见提示 |
| **V6.1.1** | Win11 批量导入弹窗修复 + unittest 缺失 + 更新提示条布局 + 许可证乱码 + 检查更新 |
| **V6.1.0** | PyInstaller 打包 + NSIS 安装包 + GitHub Actions CI + 自动更新 + 系统托盘通知 + PyMuPDF 全量表提取 |
| V6.0.0 | Vision 全量 + 模型手动切换 + 编辑保存 + 混合文件类型检测 + 标准年度替换 |
| V5.3.0 | 智能分片保留文档顺序 + 专业 Few-Shot + 文档标准提取 + 桩号精度修正 |
| V5.0.0 | QML 组件化 + 消双份 QML + 工程化重构 |
| V4.9.x | 智能转换管线 + Vision 并行 ×3 + Word/Excel 导入 + 断点恢复 |
| V4.0-4.8 | QML GUI + SQLite + 多模型 + 蓝白主题 + AI 缓存 |

详细变更见 [CHANGELOG.md](CHANGELOG.md)。

---

## ❓ 常见问题

<details>
<summary><b>Q: API Key 安全吗？</b></summary>
完全安全。使用 Windows DPAPI 加密存储，仅当前 Windows 用户可解密。Key 不在安装目录、不在代码中、不在 GitHub 上。
</details>

<details>
<summary><b>Q: 需要 Python 环境吗？</b></summary>
不需要。安装包已包含所有运行时依赖。下载 exe 安装即可使用。
</details>

<details>
<summary><b>Q: 支持哪些文件格式？</b></summary>
DWG、DXF、PDF、Word (.docx)、Excel (.xlsx)。CAD+PDF 混合导入时自动优化策略（CAD 不渲染，PDF 负责视觉分析）。
</details>

<details>
<summary><b>Q: 大文件有没有问题？</b></summary>
已验证支持 183MB / 224页 PDF。CAD 最大测试过 15MB DWG（35,229 实体）。超大文件会自动限制表格提取范围防止内存溢出。
</details>

<details>
<summary><b>Q: Win11 能用吗？</b></summary>
可以。Python 3.12 + PySide6 + PyMuPDF 均官方支持 Win11。但不排除 UI 细节差异。
</details>

<details>
<summary><b>Q: 如何更新？</b></summary>
应用启动时自动检查 GitHub Release。发现新版本会弹出提示，点击即可下载安装。更新是覆盖安装，保留所有用户数据。
</details>

<details>
<summary><b>Q: 安装包为什么这么大（461MB）？</b></summary>
内含 PySide6 (Qt)、PyMuPDF、scipy、numpy、pandas 等完整依赖，外加 VC Redist (25MB) 和 ODAFC (28MB)。压缩后 461MB 已接近理论极限。
</details>

---

## ⚠️ 免责声明

本软件仅供个人学习和工作使用。AI 生成结果仅供参考，实际送检计划请以相关规范和监理要求为准。

API Key 由用户自行申请，费用由 API 提供商（DeepSeek/阿里云 DashScope）收取，与本软件无关。

---

## 📄 许可

MIT License © 2026

---

## 🔗 相关链接

- [GitHub 仓库](https://github.com/2537910567/material-testing-app)
- [下载最新版](https://github.com/2537910567/material-testing-app/releases/latest)
- [DeepSeek API](https://platform.deepseek.com)
- [Qwen-VL API](https://dashscope.console.aliyun.com)
- [ODA File Converter](https://www.opendesign.com/guestfiles/oda_file_converter)
