# Changelog

所有重要变更均记录在此文件。

格式基于 [Keep a Changelog](https://keepachangelog.com/)，版本号遵循语义化版本。

---

## V6.1.0 (2026-06-16) — 打包分发 + 自动更新 + 上线准备

### 背景
V6.0 核心功能稳定，大文件转换验证通过。正式进入上线准备阶段。

### 打包分发
- **PyInstaller 打包**: `material_testing.spec` — onedir 模式, 含 QML + 图标 + 数据库种子
- **NSIS 安装包**: `installer/installer.nsi` — 安装路径选择 + 卸载 + 升级覆盖 + 注册表
- **环境检测**: `installer/env_check.py` — VC Redist / ODAFC / 磁盘空间 / 管理员权限
- **安装包内含**: VC++ Redist (25MB) + ODAFC MSI (28MB)，自动静默安装
- 最终产物: 461MB 安装包，压缩率 50.7%

### 自动更新
- **更新检查**: `app/engine/update_checker.py` — GitHub Release API, 24h 缓存, 版本比较
- **下载安装**: 断点续传 + 进度回调 + 静默覆盖安装
- **QML 提示条**: `main.qml` 顶部更新提示条（发现新版本 → 下载 → 安装）
- `AppState` 新增: `updateAvailable` / `updateVersion` / `updateUrl` / `updateBody` 属性 + `downloadUpdate()` / `dismissUpdate()` / `installUpdate()` slot

### 系统通知
- `main.py`: QSystemTrayIcon — 托盘图标 + 气泡通知
- 转换完成 → "✅ 转换完成！可以开始 AI 分析"
- AI 分析完成 → "✅ AI 分析完成！可以导出 Excel"
- 导入完成不弹通知

### 大文件测试
- SⅠ道路 183MB / 224页 PDF: 预分析 2m30s + 转换 6m4s (195 PNG, 35 表格)
- SⅡ交通 91MB / 104页 PDF: 预分析 1m38s + 转换 6m48s (94 PNG, 17 表格)
- DWG 15MB: parse_dwg 47.5s (35,229 实体)
- 全量表提取: PyMuPDF `find_tables()` 替代 pdfplumber，内存 8.6GB→200MB

### Bug 修复 (V6.0.1 合并)
- pdfplumber 全量表提取内存爆炸 → PyMuPDF `find_tables()` (内存降 97%)
- pdfminer DEBUG 日志 3.9GB → `logger.py` 抑制为 WARNING
- 表格数据被丢弃 → 存入 `text_entities` 传入 AI 分析
- 转换进度无文件名 → `[3/10] SⅠ-11.dwg` 格式
- 预分析进度污染转换计数器 → 拆分为独立 indeterminate 模式
- AI 分析进度固定 100 → 从消息解析真实步骤数
- 导出无限旋转 → ExportThread 新增 `progress` 信号 + report_generator 回调
- StandardsWindow QML 文字不可见 → 全硬编码颜色 (独立引擎无法共享 AppTheme)
- `openStandardsWindow` UnboundLocalError → `_MEIPASS` 路径兼容
- ActionButton `variant` 属性不存在 → 改用 Rectangle + Label

### 工程化
- **GitHub Actions**: `.github/workflows/release.yml` — 打 tag v* 自动构建
- **README.md**: 完整文档（功能特性 + 架构 + 性能数据 + FAQ + 开发指南）
- **CLAUDE.md**: 重写精简 + 权限解决方案 + 打包注意事项 + Release 流程
- **.gitignore**: 排除 config.json / api_key.txt / tests / build / dist
- **版本号**: 统一 6.1.0（app_state + main.py + installer.nsi）

### 修改文件 (V6.1.0)
- 新增: `material_testing.spec`, `installer/installer.nsi`, `installer/env_check.py`, `installer/license.txt`, `app/engine/update_checker.py`, `.github/workflows/release.yml`, `README.md`, `.gitignore`
- 修改: `main.py`, `app/bridge/app_state.py`, `app/qml/main.qml`, `app/qml/StandardsWindow.qml`, `app/engine/pdf_parser.py`, `app/logger.py`, `app/report/report_generator.py`, `app/database/db_manager.py`

---

## V6.0.0 (2026-06-15) — 画质拉满+Vision全量+多专业扩展+模型切换+导出重构

### 背景
基于桌面 V6.0 升级计划执行 Phase 2-6。Phase 1 (CAD渲染画质拉满) 此前已完成。

### Pre-phase: Bug 修复 (6项)
- B1: `db_manager.py` `update_standards()` 移除不存在的 `mandatory` 列引用
- B2: `image_preprocess.py` `preprocess_batch()` 默认值对齐 V6.0 (4096/100)
- B3: `db_manager.py` 关键词存储格式统一为逗号分隔字符串
- B4: `standards_seed.json` 全部条目添加 `series` 字段
- B5: `conftest.py` `sample_plan` 添加缺失的 `lane_count`
- B6: `ai_agent.py` 缓存键使用全部 chunks hash (非仅 chunk[0])

### Phase 2: 智能转换策略 + Vision 全量 + PDF 画质拉满
- **2.1 文件类型判断**: `StrategyConversionThread._run_impl()` 检测 CAD+PDF 混合项目，混合时 CAD 仅提取文字不渲染 PNG
- **2.2 文字去重**: `ai_agent.py` 新增 `_deduplicate_text()` — CAD+PDF 混合时行级去重
- **2.3 Vision 全量**: 移除 `pngs[:3]` 限制，所有图纸页全量发送
- **2.4 多图 Vision**: `model_provider.py` `QwenVLProvider.call_with_image()` 支持多图列表；`qwen_vl.py` `analyze_drawing()` 4张/批
- **2.5 PDF 画质拉满**: DPI 按页类型动态调整 (text=200, drawing=400, scan=300)，渲染超时 180s
- **2.6 表格全量提取**: 取消 30页限制 + 大文件缩减 + 仅 text 页限制
- `image_preprocess.py`: `max_long_edge` 0 (不缩放)，`_resize_if_needed` 处理 max_long_edge<=0
- Vision 并发 3→5, 进度显示总图片数

### Phase 3: 多专业扩展
- **3.1 标准库**: `standards_seed.json` 68→89 本 (+21 本: 给排水6/交通5/照明3/电气4/通信3)
- **3.2 Few-Shot**: `prompts.py` 新增 7 条示例 (给排水/地基基础/附属设施/照明/电气/通信/交通工程)
- **3.3 提示词**: `_inject_standards_to_prompt()` 和 `_build_material_system_prompt()` 接受 `discipline` 参数
- **3.4 关键词库**: `standards_matcher.py` `DISCIPLINE_KEYWORDS` 扩展交通/照明/电气/通信; `_detect_discipline()` 别名扩展

### Phase 4: API 模型手动切换 ⭐
- **4.1 模型列表**: `ModelProviderFactory.list_deepseek_models()` / `list_qwen_models()` — DS从API获取, VL预定义
- **4.2 偏好存储**: `AppConfig.deepseek_model` / `qwen_model` — 持久化到 config.json
- **4.3 AppState**: 5 properties + 3 slots + 5 signals (fetchModels/switchDeepseekModel/switchQwenModel)
- **4.4 UI**: `SettingsPanel.qml` 添加 DeepSeek/Qwen-VL ComboBox + 刷新按钮, 面板高度 500→620
- **4.5 生效**: `AIAnalysisThread` 从 config 读取模型名创建 provider

### Phase 5: 导出表格优化
- **5.1 Sheet 3**: 10列→12列4级层级 (路段桩号/路幅/施工层序/层工序/施工要点/材料/规格/检测)
- **5.2 导出修复**: `exportExcel()` 从 `testing_plan_items` 读取（用户编辑后数据），回退到 analysis_results
- **5.3 Sheet 4**: 施工步骤明细表（9列），AI 返回 procedures 时生成
- **5.4 打印设置**: A3横向, 重复标题行, fitToPage, 冻结首行

### 版本号
- 全部 5 处: main.py / app_state.py ×2 / CLAUDE.md / CHANGELOG.md → 6.0.0

---

## V5.3.0 (2026-06-14) — 止血固基提质：29 项修复优化，Phase 1-3

### 背景
基于 7 个 Explore Agent 并行全项目审查（~179 发现）+ 用户深度讨论后的优先级落地。

### Bug 修复 (17个)

**P0 崩溃修复:**
- `dwg_parser.py`: `time.sleep(0)` 缺少 `import time` → NameError 崩溃
- `pdf_parser.py`: `logger.warning()` 缺少 logger 定义 → NameError 崩溃
- `app_state.py`: `getApiUsageStats` 列映射交换（tokens/latency 数值互换）
- `SettingsPanel.qml`: `testConnection` 返回 null 时 QML 崩溃 — 加 `if (!r)` 守卫
- `report_generator.py`: 输入参数无类型校验 → 加 `isinstance` 防守

**P1 数据安全:**
- `db_manager.py`: `close()` 未关闭 `_read_conn` → WAL 文件句柄泄漏
- `app_state.py`: `renameProject` 绕过 DB 锁直接 UPDATE → 改用 `update_project_name()`
- `app_state.py`: `cancelAnalysis` 先清引用再 cancel → 竞态修复 + 重复赋值删除
- `db_manager.py`: 启动加 `PRAGMA integrity_check`，损坏提前发现
- `pdf_parser.py`: 大文件(>50MB)表格提取完全跳过 → 改为至少提取前30页
- 5 处 `except: pass` 改 `logger.warning(...)` + 2 处线程崩溃加 `error.emit()`

**P2 AI 分析:**
- `model_provider.py`: QwenVL text call 用 `json.loads` 替代 robust `_parse_json_response`
- `model_provider.py`: AI 响应日志泄漏 500 字符 → 截断到 100 字符
- `ai_agent.py`: 去重函数非 hashable 值崩溃 → `str()` 包装
- `main.qml`: API 错误无条件归零 `totalRows` → 保留已有数据

### 性能优化 (6项)

**UI 流畅度:**
- `dwg_parser.py`: ODAFC 子进程 `IDLE_PRIORITY_CLASS`（原 BELOW_NORMAL）— 转换期间 UI 不再卡顿
- `app_state.py`: 删 `QApplication.processEvents()` — 消除事件循环重入
- `app_state.py`: 降并发上限 8/4/3→4/3/2 — 减少 CPU 争抢
- `app_state.py`: 启动网络检查异步化（3s 阻塞→后台线程）— 冷启动窗口即时出现

**AI 输入质量:**
- `image_preprocess.py`: `max_long_edge` 2048→3072, JPEG quality 85→90
- `qwen_vl.py`: 横断面不设 CLAHE（CAD 线稿被 CLAHE 劣化）

### 数据库优化

- `db_manager.py`: `list_projects()` N+1→1 条批量 JOIN（10 项目从 60 条 SQL→1 条）
- `db_manager.py`: 启动 `PRAGMA integrity_check`

### AI 分析质量 (6项)

- `model_provider.py`: `requests.Session()` HTTP 连接池 — 复用 TCP 连接
- `ai_agent.py`: 智能分片保留原始文档顺序（工程桩号不乱序）
- `ai_agent.py`: 结构检测失败 fallback 仅用 chunk[0] — 加 warning
- `file_profiler.py`: CAD 策略 2-5MB 不再放弃渲染（用 reduced_render）
- `file_profiler.py`: 预分析升级全量分类时保留已采样页
- `ai_agent.py`: AI 缓存 key 用全部 chunks hash（Phase 5 完整落地）

### 架构决策

- **否掉** 多进程 Worker 架构（方案二）— 根因是进程优先级，直接用 `SetPriorityClass` 解决
- **否掉** 断面图拼接验证 — 工程文件顺序乱，拼接无参考价值
- **否掉** 大项目预览通道
- **否掉** AI 缓存 TTL — 同份文档不重复花钱，未来加 `prompt_version` 管理缓存失效

### 修改文件清单

| 文件 | 改动 |
|------|------|
| `app/engine/dwg_parser.py` | `import time`, ODAFC IDLE 优先级 |
| `app/engine/pdf_parser.py` | logger 定义, 大文件表格恢复, 3处 except→warning |
| `app/engine/image_preprocess.py` | max_long_edge 3072, JPEG 90 |
| `app/engine/file_profiler.py` | CAD 策略 2-5MB reduced_render, 采样保留 |
| `app/engine/model_provider.py` | Session 连接池, JSON 解析加强, 日志脱敏 |
| `app/engine/ai_agent.py` | 文档顺序, fallback 警告, 去重防御 |
| `app/engine/qwen_vl.py` | 横断面 drawing 类型 |
| `app/bridge/app_state.py` | 删 processEvents, 降并发, 网络异步, stats 修复, cancelAnalysis 修复, rename 修复, 2处 except→warning+emit |
| `app/bridge/project_tree_model.py` | except→warning |
| `app/database/db_manager.py` | close _read_conn, list_projects JOIN, integrity_check |
| `app/qml/SettingsPanel.qml` | testConnection null 守卫 |
| `app/qml/main.qml` | API 错误保留数据 |
| `app/report/report_generator.py` | 输入 isinstance 校验 |
| `tests/test_file_profiler.py` | CAD 策略测试更新 |

### 测试
101 tests passed, 0 regressions（Phase 1-3 完成后）

---

## V6.0.0 (2026-06-15) — 画质拉满+Vision全量+多专业+模型切换+导出重构

### Pre-phase: Bug修复 (6)
- `db_manager.py`: `update_standards()` 移除不存在 `mandatory` 列; keywords 统一逗号分隔
- `image_preprocess.py`: `preprocess_batch()` 默认值对齐 V6.0 (4096/100)
- `standards_seed.json`: 全部添加 `series` 字段
- `conftest.py`: `sample_plan` 补 `lane_count`
- `ai_agent.py`: 缓存键使用全部 chunks hash

### Phase 2: 智能转换+Vision全量+PDF画质拉满
- **文件类型判断**: 混合 CAD+PDF 时 CAD 仅提取文字不渲染 PNG
- **文字去重**: `_deduplicate_text()` 行级合并去重
- **Vision 全量**: 移除 `pngs[:3]` 限制, 5 并行
- **多图 Vision**: `call_with_image()` 支持批量 (4张/批)
- **PDF DPI**: 按页类型动态 (drawing=400/scan=300/text=200), 超时 180s
- **表格全量**: 取消 30页+大文件限制，全页面类型提取
- **VL不缩放**: `max_long_edge=0` 保留全部像素

### Phase 3: 多专业扩展
- **标准库 68→91**: 新增给排水/交通/照明/电气/通信 (6专业 +21本)
- **Few-Shot +7**: 给排水/地基基础/附属设施/照明/电气/通信/交通
- **Discipline 传递**: prompt→标准匹配全链路

### Phase 4: API模型手动切换
- **模型列表**: DS API获取 / VL 预定义列表
- **偏好存储**: `AppConfig.deepseek_model` / `qwen_model`
- **UI**: `SettingsPanel.qml` ComboBox + 刷新按钮

### Phase 5: 导出优化
- **Sheet 3**: 10→12列 (路段/路幅/层序/层工序/施工要点/材料/规格...)
- **导出修复**: 从 `testing_plan_items` 读取编辑后数据
- **Sheet 4**: 施工步骤明细表
- **打印设置**: A3横向/重复标题行/fitToPage

### UI修复
- **编辑流程**: 保存后自动退出编辑; 按钮状态修复; 数据立即刷新
- **弹窗圆角**: 新建/重命名/删除三弹窗圆角+按钮居中
- **标准库**: 芯片高亮(JS直接设色) + Flow自动换行 + 12专业完整显示
- **删除项目**: 树不再折叠 (增量更新代替全量刷新)

### 性能修复
- **PDF导入**: 串行处理 (防内存争抢+进度正常跳动)
- **转换并发**: 渲染策略 worker 上限收紧
- **文件类型**: 自动检测扩展名修正 cad→pdf/word/excel
- **种子同步**: 每次启动增量导入新标准

### 版本号: 5.3.0 → 6.0.0 (5处同步)

---

## V6.0 路1: CAD渲染画质拉满 (2026-06-15)

**策略**: 不改架构，仅调参数，DPI 猛拉。

### 改动文件

| 文件 | 改动 |
|------|------|
| `app/engine/file_profiler.py` | CAD阈值重设: 0.5/2/5/10MB；_cad_strategy 新增 standard_high/standard_plus |
| `app/engine/dwg_parser.py` | 新增 standard_high(400dpi)/standard_plus(350dpi)；reduced→200dpi; text_only→120dpi |
| `app/engine/image_preprocess.py` | max_long_edge 3072→4096; JPEG quality 90→100 |
| `app/bridge/app_state.py` | 转换管线支持新策略名；并发降为2(高DPI省内存) |
| `tests/test_file_profiler.py` | 测试同步更新 |
| `tests/test_integration_03_perf.py` | 集成测试阈值更新 |

### 效果对比（3.1MB 路面结构图）

| | 旧管线 | 新管线 | 提升 |
|---|--------|--------|------|
| DPI | 100 | 350 | 3.5× |
| 像素 | 3972×2805 | 11585×8182 | 8.5× |
| 文件 | 460KB | 2260KB | — |

### 最终策略

| 文件大小 | 策略 | DPI |
|----------|------|-----|
| <0.5MB | standard_render | 150 |
| 0.5-2MB | standard_high | 400 |
| 2-5MB | standard_plus | 350 |
| 5-10MB | reduced_render | 200 |
| >10MB | text_only | 120 |

---

## V5.3.0 第二阶段 (2026-06-14) — Phase 3暂缓+Phase 4增能+Phase 5优化

### Phase 3 暂缓项落地 (4项)

- **PDF 并行渲染:** `pdf_parser.py` `extract_pdf_with_strategy()` 改用 `ThreadPoolExecutor(max_workers=4)`，每线程独立 `fitz.Document`，138页35s→10s
- **DXF 完整性校验:** `dwg_parser.py` 新增 `_validate_dxf_eof()` 检查 EOF 标记；`app_state.py` ThreadPoolExecutor shutdown 改 `wait=True`
- **领域知识关键词匹配:** 新建 `app/engine/standards_matcher.py` — `extract_keywords()` 从内容提取专业/材料/结构/检测项 → `match_standards()` 在67本标准中匹配Top-5 → 注入AI prompt
- **Few-Shot 按专业选择:** `prompts.py` `FEWSHOT_BY_DISCIPLINE` 按7专业分组 + `DISCIPLINE_ALIASES` SⅠ-SⅦ映射 → `build_material_system_with_fewshot(discipline)` 动态选择

### Phase 4 增能 (3大功能)

- **表格编辑模式:** `plan_table_model.py` 17列全可编辑 + `setEditingMode()`/`getModifiedCells()`；`TestingPlanTable.qml` `isEditMode` 属性（淡黄底+绿标记）；`main.qml` 编辑/保存按钮；`db_manager.py` `batch_update_plan_items()` 事务批量保存
- **标准年度替换:** 新建 `app/engine/standards_updater.py`（解析/系列匹配/预览生成）；`schema.py` V13迁移（standards.series列）；`db_manager.py` `update_standards()` 事务替换；`SettingsPanel.qml` 新增"标准"Tab
- **混合文件类型提示:** `app_state.py` `mixedFileTypesDetected` 信号；`main.qml` 导入CAD+PDF时弹窗提示

### Phase 5 优化 (6项)

- **动态Worker数:** `_calc_worker_count()` 硬件自适应（CPU-2核, 1-8范围, <4GB内存减半, fallback=4）
- **Section并行:** 材料分析 `max_workers` 5→3，避免API限流
- **AI缓存Key修正:** `analyze_with_provider()` 缓存key使用全部chunks的hash（非仅chunk[0]）
- **tmp文件清理:** 删除240个 `*.tmp.*` 残留文件
- **版本号统一:** `app_state.py` 两处 "5.2.0"→"5.3.0"
- **CLAUDE.md更新:** Code Index 同步所有新增/修改文件和符号

### 修改文件清单 (第二阶段)

| 文件 | 改动 |
|------|------|
| `app/engine/pdf_parser.py` | ThreadPoolExecutor 并行渲染 |
| `app/engine/dwg_parser.py` | _validate_dxf_eof() |
| **`app/engine/standards_matcher.py`** | **新建：关键词→Top-5标准匹配** |
| **`app/engine/standards_updater.py`** | **新建：标准年度替换引擎** |
| `app/engine/prompts.py` | FEWSHOT_BY_DISCIPLINE + build_material_system_with_fewshot(discipline) |
| `app/engine/ai_agent.py` | standards_matcher集成 + 缓存key全chunks + max_workers→3 |
| `app/bridge/app_state.py` | 动态Worker + saveEditingChanges + importStandardsUpdate + mixedFileTypesDetected + 版本号修正 |
| `app/bridge/plan_table_model.py` | 17列全可编辑 + setEditingMode + getModifiedCells |
| `app/database/schema.py` | SCHEMA_VERSION→13, DDL_V13(standards.series) |
| `app/database/db_manager.py` | batch_update_plan_items + update_standards |
| `app/qml/TestingPlanTable.qml` | isEditMode + 编辑态样式 |
| `app/qml/main.qml` | 编辑/保存按钮 + 混合文件弹窗 |
| `app/qml/SettingsPanel.qml` | 标准年度替换Tab |
| `CLAUDE.md` | Code Index 同步更新 |

### 测试
66 core tests passed (ai_agent + db_manager + file_profiler), 0 regressions

---

## V4.9.3 (2026-06-10) — 智能转换管线升级 + 性能实测优化

### 新增功能
- **Phase 0 文件预分析:** `file_profiler.py` — PDF 逐页分类(text/drawing/scan/blank)+CAD复杂度估算+策略决策
- **Phase 1 分策略转换:** `StrategyConversionThread` — 替代一刀切 ConversionThread，按策略分组+不同并行度
- **图片预处理管线:** `image_preprocess.py` — VL API 前空白过滤+自适应压缩(长边≤2048px)+JPEG输出+CLAHE增强
- **OCR 集成:** `ocr_helper.py` — PaddleOCR/Tesseract 统一入口，Tesseract 5.5+中文包

### Bug 修复 (4个)
- **P1-2:** Qwen-VL `call_with_image()` 无重试 → 对齐 DeepSeek 2次重试+指数退避
- **P2-3:** AI 缓存 Key `user_prompt[:2000]` → 完整 prompt hash
- **P2-2:** 文字实体 5000 行截断 → 20000 行
- **P1-3:** 送检指南检测仅 PDF → 扩展到 Word (.docx)

### 性能优化 (3项实测)
- **Opt-1:** `_classify_single_page` 短路 — chars≥2000 直接返回 text，跳过 get_drawings
- **Opt-2:** Tesseract 5.5 + 中文包 chi_sim 安装
- **Opt-3:** pdfplumber 表格提取限 30 页（发现 102s 瓶颈，从 3.3s/页 → 0.6s/页）

### 数据库
- DDL V9: `file_profiles` 表 (file_id+file_md5+profile_json)

### 架构变更
```
V4.9.2: 导入 → ConversionThread(一刀切) → AIAnalysisThread
V4.9.3: 导入 → ProfileThread(Phase 0) → StrategyConversionThread(Phase 1, 分策略) → AIAnalysisThread(Phase 2)
```

### 性能数据（送检指南 168页）
| 阶段 | V4.9.2 | V4.9.3 | 加速比 |
|------|--------|--------|--------|
| Phase 0 | 4.1s | 2.6s | 1.6x |
| Phase 1 | 146.6s | 53.9s | 2.7x |
| **总计** | **150.6s** | **56.5s** | **2.7x** |

### 扫描 PDF OCR（检验监测 65页）
- V4.9.2: 0 chars | V4.9.3: 9,288 chars/5页

### 文件清单
| 操作 | 文件 |
|------|------|
| 新建 | `app/engine/image_preprocess.py`, `app/engine/file_profiler.py`, `app/engine/ocr_helper.py` |
| 新建 | `tests/test_image_preprocess.py` (18 tests), `tests/test_file_profiler.py` (19 tests) |
| 修改 | `main.py`, `requirements.txt`, `pdf_parser.py`, `dwg_parser.py`, `qwen_vl.py`, `model_provider.py`, `ai_agent.py`, `app_state.py`, `schema.py`, `db_manager.py` |

### 测试
109 tests passed (72 original + 37 new)

---

## V4.9.1 (2026-06-09) — QML 警告修复 + 面板布局优化

### Bug 修复 (8个)
- **ACL 权限修复:** 6 个 V4.9 新增文件缺少 Everyone 读权限，Python/pytest 无法读取
- **QML 警告清零 (3个):** anchors in Layout → `Layout.alignment`、undefined 属性 `bgPage`/`radiusMedium` → 已有属性、`result="str"` → `result="QString"`
- **设置面板关闭按钮:** 标题栏右侧添加 ✕ 按钮，解决「关于」Tab 无关闭入口问题
- **面板标题贴边 (4处):** ProjectTree/TestingPlanTable/路段选择/工序流程 — RoundedCard padding 属性未生效 → 根级 ColumnLayout 添加 `anchors.margins`
- **路段卡片底部裁切:** 卡片高度 100→120，补偿 padding
- **工序流程标题位置不一致:** 空状态占位 Label `Layout.alignment` 干扰垂直布局 → `Item{fillHeight}+anchors.centerIn` 包裹
- **路段卡片长文字贴边:** 字号 11→10 + 宽度约束让 elide 省略号生效

### 修改文件
`main.qml`, `SettingsPanel.qml`, `ProjectTree.qml`, `TestingPlanTable.qml`, `app_state.py`, 权限修复: `word_parser.py`, `excel_parser.py`, 3个测试文件

---

## V4.7.0 (2026-06-08) — 工序流程 + 路段细化 + DWG转换 + 文件替换 (14 files)

### 新增功能
- **施工检测工序流程:** 路段→施工层→材料/检测 三级树形视图（ProcessFlow 组件内联到 main.qml）
- **路段细粒度拆分:** AI 结构检测从 3-8 段 → 10-20 段（每段 200m-500m），按道路结构变化点拆分
- **AI 自动批次计算:** DeepSeek 根据桩号长度×路面宽度÷检验批单位量计算 `planned_batches`
- **文件替换:** 右键文件→替换→自动删除旧文件+导入新文件+增量解析
- **Qwen-VL 精确尺寸提取:** 横断面分析返回结构化数值（road_width_m, lane_width_m, layer_thicknesses_mm）
- **DWGG-PNG 管线:** ODAFC v27 DWG→DXF → LibreOffice DXF→PNG（3-5s/DWG，比 ezdxf 快 70x）

### 数据库
- DDL V5: 新增 `construction_layers`/`layer_materials`/`layer_tests` 三表（路段→施工层层级）
- `db_manager.py`: 新增 `store_construction_layers()`/`get_construction_layers()` CRUD

### AI Prompt 增强
- 结构检测 prompt: 路段粒度 200m-500m，拆分每个结构变化点
- 材料分析 prompt: 新增 `construction_layers` 输出字段（施工层+材料+检测工序，从下到上排列）
- 分组策略: 3 路段/组 → 2 路段/组（避免 construction_layers 截断）
- 施工流程标准引用: JTG F40-2004, JTG/T F20-2015, CJJ 1-2008

### UI 改造
- TabBar 双视图：「送检计划表」|「工序流程」
- 路段卡片: ScrollView→ListView 水平滑动（支持 22+ 路段）
- 进度条: 始终 indeterminate 动画（修复暂停时空白问题）
- 文件右键菜单: 替换文件 + 删除文件
- `file_model.py`: 新增 FileIdRole

### Excel 导出
- 删除 Sheet 3（按 GB55032 分类）和 Sheet 4（合同摘要）
- 新增 Sheet 3：施工检测工序流程（按路段→施工层分层，同层合并单元格）

### 模型策略
- Qwen-VL: 平面图和断面图统一使用 `qwen3-vl-8b-thinking`

### 修复
- 修复 `CROSS_SECTION_SYSTEM_PROMPT` 缺少结尾 `"""` 导致 qwen_vl.py 语法错误
- ODAFC v27 PNG CLI 不可用 → DWG→DXF(ODAFC) + DXF→PNG(LibreOffice) 管线
- DWG 中文路径 → ASCII 临时目录拷贝（`_copy_to_ascii_temp`）
- `convert_dwg_to_png` 超时 120s → 15s（ODAFC）+ LibreOffice headless 替代
- ProcessFlow `getSelectedSections()` 返回字符串数组，QML 适配 typeof 检查
- 安装 matplotlib（ezdxf 渲染依赖）和 LibreOffice（DXF→PNG）

### 文件清单
| 文件 | 改动 |
|---|---|
| `app/engine/dwg_parser.py` | 新增 `find_libreoffice`/`convert_dxf_to_png_libreoffice`/`_has_chinese_chars`/`_copy_to_ascii_temp`；重写 `convert_dwg_to_png` |
| `app/engine/ai_agent.py` | 结构检测 prompt 细粒度化；材料 prompt 含 construction_layers+批次计算；分组 3→2 |
| `app/engine/qwen_vl.py` | Rule 6 精确尺寸；CROSS_SECTION_SYSTEM_PROMPT 修复；analyze_cross_section 增强 |
| `app/engine/model_provider.py` | QWEN_PLAN_DRAWING_MODEL → 8B-Thinking |
| `app/database/schema.py` | DDL V5 三表 + SCHEMA_VERSION=5 |
| `app/database/db_manager.py` | store/get_construction_layers CRUD |
| `app/bridge/app_state.py` | replaceFile()/getConstructionLayers()/exportExcel construction_layers |
| `app/bridge/file_model.py` | FileIdRole |
| `app/qml/main.qml` | TabBar+StackLayout；ProcessFlow 内联；ListView 路段卡片；进度条修复 |
| `app/qml/ProjectTree.qml` | 文件右键菜单 |
| `app/report/report_generator.py` | 删除 GB55032/合同 Sheet；新增 _gen_process_flow() |
| `main.py` | 版本号 4.7.0 |
| `tests/test_construction_layers.py` | 新建施工层 CRUD 测试 |
| `tests/test_report_generator.py` | 更新 3-Sheet 测试 |

### 依赖变更
- 新增: `matplotlib`（ezdxf 渲染 DXF→PNG，后被 LibreOffice 替代）
- 新增: LibreOffice 26.2.3（DXF→PNG headless 渲染，3-5s/DWG）

---
# Changelog

所有重要变更均记录在此文件。

格式基于 [Keep a Changelog](https://keepachangelog.com/)，版本号遵循语义化版本。

---

## V4.5.6 (2026-06-06) — 项目树 VS Code 精简 + 三角形修复 + 送检计划联动 (6 files)

- **项目树 VS Code 精简 (Issue #1):** 删除 CAD/PDF 文件数量、更新时间、分析状态指示器（✓/…）；行高 64→36px；`project_model.py` 移除 `CadCountRole`/`PdfCountRole`/`UpdatedAtRole`
- **三角形展开修复 (Issue #1):** 三角形 Label 内嵌独立 `MouseArea`（`anchors.margins: -4` 扩大热区）；主 MouseArea 移除脆弱的 `mouse.x < 28` 区域检测，仅保留项目选中+右键菜单
- **路段卡片文字缩小 (Issue #2):** 路段名称 `13px→11px`，左右幅标签 `9px→8px`
- **送检计划空选择=空表 (Issue #3):** `_apply_filter()` 空选择时返回 `[]`（而非全部行）；`section_model.refresh()` 补发 `selectedChanged` 信号；`onAnalysisFinished` 调序；`TestingPlanTable.qml` 空状态区分
- Files: `ProjectTree.qml`, `project_model.py`, `main.qml`, `plan_table_model.py`, `section_model.py`, `TestingPlanTable.qml`

## V4.5.5 (2026-06-06) — 砍图纸浏览 + 路段卡片 + 表格合并 (8 files)

- **砍掉图纸浏览:** 删除 `DrawingBrowser.qml`；UI 从三栏 SplitView → 固定两栏 RowLayout
- **路段卡片选择:** 水平滚动卡片，多选/全选/全不选
- **送检计划联动过滤:** SectionListModel 卡片选中模式；PlanTableModel 新增 `_apply_filter()`
- **桩号+左右幅合并:** `getMergeRanges()` 重写
- **导出改进:** `exportExcel` 新增 `selected_sections` 参数
- **侧边栏折叠移除:** ProjectTree 去掉 ◀/▶ 按钮
- Files: `main.qml`, `ProjectTree.qml`, `TestingPlanTable.qml`, `section_model.py`, `plan_table_model.py`, `app_state.py`, `project_model.py`, `main.py`；删除 `DrawingBrowser.qml`

## V4.5.4 (2026-06-06) — 6 回归 Bug 修复 (8 files)

- **项目消失:** 恢复 `Component.onCompleted` refresh
- **三角不展开:** 三角区点击不再调 `projectSelected`
- **暂停按钮不可见:** ActionButton 重写 background/contentItem
- **送检计划延迟:** onAnalysisFinished 用 loadFromDatabase 替代 loadFromResult
- **平面图不显示:** 视觉分析后立即持久化 PNG；放宽匹配
- **路段空状态重叠:** SectionListModel 新增 `isEmpty` property
- Files: `ProjectTree.qml`, `project_model.py`, `ActionButton.qml`, `main.qml`, `app_state.py`, `db_manager.py`, `section_model.py`, `DrawingBrowser.qml`

## V4.5.3 (2026-06-06) — 5 bugs fixed + Modern Clean Theme (6 files)

- **刷新竞态修复:** 删除冗余 refresh() 调用，增加 _resetting 防重入
- **VS Code 目录树:** 恢复三角箭头单击展开
- **平面图持久化:** 从临时目录复制到 config_dir/plan_drawing/
- **AI fallback sections:** _extract_sections_from_plan() 逆向提取
- **现代清新主题:** 白底+石板灰+青色辅色；35 个属性全量更新
- Files: `ProjectTree.qml`, `project_model.py`, `app_state.py`, `ai_agent.py`, `DrawingBrowser.qml`, `theme.py`, `main.py`, `main.qml`

## V4.5.2 (2026-06-06) — 7 issues fixed: CAD viewer + UX improvements (5 files)

- **三面板同步刷新:** 修复 camelCase/snake_case key 不匹配
- **空状态居中:** overlay z:10 绝对居中
- **测试连接按钮:** AppState.testConnection()
- **双击展开:** 300ms Timer 双击检测
- **删除确认+面板清空:** MessageDialog + projectDeleted 信号
- **CAD 看图窗口:** DrawingBrowser 重构为全尺寸查看器（拖拽+缩放）
- **总体平面图自动捕获:** AIAnalysisThread 识别首个非横断面 DWG→PNG
- Files: `app_state.py`, `main.qml`, `DrawingBrowser.qml`, `TestingPlanTable.qml`, `ProjectTree.qml`, `SettingsPanel.qml`, `db_manager.py`

## V4.5.1 (2026-06-06) — 安全加固 + 关键 Bug 修复 (7 files)

- **API Key 加密存储:** Windows DPAPI + base64
- **删除 AI 分析双份代码:** 移除 ~160 行死代码
- **FileListModel 级联删除:** DatabaseManager.delete_file()
- **版本号统一:** AppState.appVersion 唯一来源
- **16列表格 Repeater 重构:** 50→15 行
- Files: `config.py`, `ai_agent.py`, `db_manager.py`, `file_model.py`, `TestingPlanTable.qml`, `main.qml`, `app_state.py`, `main.py`

## V4.5.0 (2026-06-05) — UI/UX full redesign (13 files)

- **Design system:** Minimalism + Swiss Style. Industrial Grey + Safety Orange
- **ActionButton refactored:** 5 variants
- **RoundedCard enhanced:** shadowEnabled + padding
- **TestingPlanTable:** 完整 16 列 Flickable 表格
- **app_state.py:** ExportThread + AIAnalysisThread.cancel()
- **plan_table_model.py:** loadFromDatabase() + setData()
- Files: 13 files including theme.py, main.qml, ProjectTree.qml, etc.

## V4.4.1 (2026-06-05) — AI vision freeze fix

- extract_page_images(): max_pages 参数
- convert_dwg_to_png(): max_images 参数
- analyze_drawing() 签名修复
- per-file exception handling
- Files: pdf_parser.py, dwg_parser.py, qwen_vl.py, app_state.py

## V4.4.0 (2026-06-05) — QML UI restructure + engineering cleanup

- QML 3-panel SplitView 重构
- 旧 QWidget GUI 删除
- Git init + pytest 47 tests
- Files: main.py, main.qml, ProjectTree.qml, requirements.txt, 6 test files

## V4.3.0 (2026-06-04) — QML GUI (Phase 3)

- 新 QML GUI (--qml 模式)
- 6 bridge 文件 + 7 QML 文件
- 3-panel SplitView
- 旧 GUI 保留

## V4.2.1 (2026-06-04) — Multi-model auto-selection

- Qwen-VL auto model selection
- DeepSeek 固定 deepseek-v4-flash
- Version tracking

## V4.1.0 (2026-06-04) — SQLite persistence + ModelProvider

- SQLite 11 表替代 JSON
- ModelProvider 抽象
- DWG→PNG + PDF→PNG

## V4.0.0 (2026-06-04) — Tech debt + stability + table upgrade

- ezdxf, logging, temp cleanup
- 15→16 列（插入左/右幅）
- AI chunking, retries, dedup
- 队列导入 + pause/resume/cancel

## Earlier (V1-V3) — Prototype evolution

- **V3:** Multi-pass AI analysis to avoid JSON truncation
- **V2:** 15-column GB55032-2022 template, 4-sheet Excel
- **V1:** 10-column prototype
- ODAFC v27 CLI args discovered; JSON parsing 4 fallback strategies
