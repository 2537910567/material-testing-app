# 工程材料送检分析系统 V6.1

基于 AI 的智能送检计划生成工具，分析 CAD/PDF 图纸 → DeepSeek + Qwen-VL 多模型 → Excel 送检计划。

## 系统要求

- Windows 10/11 (64-bit)
- 4GB+ 内存
- 3GB+ 可用磁盘空间
- 互联网连接（AI分析需要）

## 安装

1. 下载 `MaterialTestingTool-Setup.exe`
2. 双击运行，按提示选择安装路径
3. 安装程序会自动检测并安装所需环境：
   - Visual C++ Redistributable 2015-2022
   - ODA File Converter (DWG转换必需)
4. 安装完成后桌面和开始菜单会创建快捷方式

## 配置 API Key

1. 启动应用 → 点击 ⚙ 设置
2. 输入 **DeepSeek API Key**（文本分析，[获取](https://platform.deepseek.com/api_keys)）
3. 输入 **Qwen-VL API Key**（视觉分析，[获取](https://dashscope.console.aliyun.com/apiKey)）
4. API Key 使用 Windows DPAPI 加密存储，仅本机可用

## 使用流程

```
导入文件 → 转换 → AI分析 → 导出Excel
```

1. **创建项目** — 点击 "新建项目"
2. **导入文件** — 支持 DWG/DXF/PDF/Word/Excel
3. **开始转换** — 自动预分析 → 提取文本/表格/渲染图纸
4. **AI 分析** — Vision 分析图纸 → DeepSeek 生成送检计划
5. **导出 Excel** — 3-4 Sheet：封面 + 送检计划(17列) + 工序流程

## 更新

应用启动时自动检查 GitHub Release 是否有新版本。
如有更新会弹出提示，可选择立即更新或稍后。

## 常见问题

**Q: ODA File Converter 是什么？**
A: DWG 转 DXF 的免费工具。安装程序会自动安装。如手动安装，请从 [ODA官网](https://www.opendesign.com/guestfiles/oda_file_converter) 下载。

**Q: API Key 安全吗？**
A: API Key 使用 Windows DPAPI 加密，绑定当前 Windows 用户身份，其他用户无法解密。

**Q: 大文件支持？**
A: 已验证支持 183MB / 224页 PDF 转换，195 张图纸渲染，全量表格提取。

## 技术栈

Python 3.12 / PySide6 QML / PyMuPDF / ezdxf / DeepSeek API / Qwen-VL API
