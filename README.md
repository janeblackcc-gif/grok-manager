# Grok Manager

[简体中文](#简体中文) | [English](#english)

---

## 简体中文

### 项目简介
Grok Manager 是一个基于 **CustomTkinter** 开发的桌面应用，用于统一管理本地 Grok 相关服务与工作流。

它的目标是把以下能力整合到一个可视化界面中：

- 本地服务启动、停止、重启与状态监控
- AI Search 多轮搜索与历史会话管理
- Creative Studio 图片/视频生成与局部微调
- Prompt 智能润色与预览确认
- 全局划词悬浮搜索
- Test Lab 可复现测试工作台
- 导出、剪贴板、调试包、运行记录等工程化辅助能力

### 主要功能

#### 1. Dashboard
- 查看服务运行状态
- 启动 / 停止 / 重启本地服务
- 查看最近运行记录
- 导出调试包

#### 2. AI Search
- 基于本地 `grok2api` 提供 AI 搜索能力
- 支持多轮对话
- 支持历史会话切换
- 支持导出 Markdown / JSON
- 支持全局热键唤起搜索
- 支持提示词智能润色与预览确认

#### 3. Creative Studio
- 图片生成
- 视频生成
- 图片局部微调
- 导出 PNG
- 复制图片到系统剪贴板
- 导出素材包
- 输出目录管理
- 历史记录浏览与版本回退

#### 4. Floating Search
- 通过全局热键触发悬浮搜索窗
- 自动读取划词内容
- 展示 AI 搜索结果
- 结果可写入 AI Search 历史

#### 5. Test Lab
- 预置测试用例
- 可复现执行不同工作流
- 用于功能回归与后续 NSFW 边界测试

#### 6. Engineering Utilities
- RunRecord 运行记录
- Debug Bundle 调试包导出
- 热键与运行设置持久化
- 统一任务状态中心

### 项目结构

```text
grok-manager/
├─ assets/                 # 图标与静态资源
├─ gui/
│  ├─ pages/               # 各页面
│  ├─ utils/               # 客户端、存储、记录、热键等工具
│  ├─ widgets/             # 自定义组件
│  ├─ app.py               # 主应用窗口
│  ├─ sidebar.py           # 侧边栏
│  └─ theme.py             # 主题与配色
├─ main_gui.py             # 程序入口
├─ service_manager.py      # 本地服务管理
├─ config.py               # 配置模型
├─ requirements.txt        # Python 依赖
└─ build.bat               # Windows 打包脚本
```

### 运行环境
- Python 3.11+
- Windows 优先
- 已安装依赖：
  - `customtkinter`
  - `requests`
  - `Pillow`
  - 以及 `requirements.txt` 中的其它依赖

### 依赖服务
本项目主要面向以下本地服务：

- `grok2api`
  - 默认地址：`http://127.0.0.1:8000`
- `grok-maintainer`
  - 用于账号注册和 Token 推送

### 安装

```bash
pip install -r requirements.txt
```

### 启动

```bash
python main_gui.py
```

### 配置说明
应用运行时会使用本地配置文件和本地状态数据。
出于安全考虑，以下内容默认不建议提交到仓库：

- `.ace-tool/`
- `config.yaml`
- `outputs/`
- `logs/`
- `search_history.json`
- `.venv/`

### Git 仓库说明
当前仓库只跟踪 `grok-manager` 应用本身，不包含：

- 本地运行产物
- 本地缓存
- 本地日志
- 敏感配置
- 其他相关项目仓库内容

### 当前状态
当前版本已经完成主要工作流与核心增强，适合作为：

- 阶段性开发验收版本
- 内测版本
- 后续继续迭代的基础版本

目前仍在持续打磨的方向包括：

- NSFW 边界行为测试
- 更细粒度的错误分类
- UI 细节 polish
- 更多自动化测试与稳定性验证

### 注意事项
- NSFW 开关会传递到生图链路，但不代表上游一定放行所有 R18 内容。
- 涉及 NSFW / R18 的生成存在动态审核与限流的不确定性。
- 本项目依赖本地服务状态，若 `grok2api` 未运行，相关能力会失败。

### License
如需开源，请根据你的实际需求自行补充 License。

---

## English

### Overview
Grok Manager is a **CustomTkinter-based desktop application** for managing local Grok-related services and workflows.

It provides a unified GUI for:

- Local service lifecycle management
- Multi-turn AI Search and session history
- Creative Studio for image/video generation and iterative editing
- Prompt enhancement with preview and confirmation
- Global floating search
- Test Lab for reproducible workflow testing
- Export, clipboard, debug bundle, and runtime diagnostics

### Key Features

#### 1. Dashboard
- Service status overview
- Start / stop / restart local services
- Recent run records
- Debug bundle export

#### 2. AI Search
- AI-powered search via local `grok2api`
- Multi-turn conversations
- Session history management
- Markdown / JSON export
- Global hotkey support
- Prompt enhancement with preview confirmation

#### 3. Creative Studio
- Image generation
- Video generation
- Iterative image editing
- PNG export
- Copy image to clipboard
- Artifact bundle export
- Output directory management
- History browsing and version rollback

#### 4. Floating Search
- Triggered by a global hotkey
- Captures selected text
- Shows AI search results in a floating window
- Persists successful searches into AI Search history

#### 5. Test Lab
- Built-in test presets
- Reproducible workflow execution
- Useful for regression checks and future NSFW boundary testing

#### 6. Engineering Utilities
- RunRecord logging
- Debug bundle export
- Persistent hotkeys and runtime settings
- Unified task status center

### Project Structure

```text
grok-manager/
├─ assets/                 # Icons and static assets
├─ gui/
│  ├─ pages/               # UI pages
│  ├─ utils/               # Clients, storage, logging, hotkeys, etc.
│  ├─ widgets/             # Custom widgets
│  ├─ app.py               # Main application window
│  ├─ sidebar.py           # Sidebar
│  └─ theme.py             # Theme and colors
├─ main_gui.py             # Entry point
├─ service_manager.py      # Local service management
├─ config.py               # Config model
├─ requirements.txt        # Python dependencies
└─ build.bat               # Windows build script
```

### Requirements
- Python 3.11+
- Windows recommended
- Dependencies from `requirements.txt`

### Related Local Services
This app is mainly designed to work with:

- `grok2api`
  - default endpoint: `http://127.0.0.1:8000`
- `grok-maintainer`
  - used for account registration and token delivery

### Installation

```bash
pip install -r requirements.txt
```

### Run

```bash
python main_gui.py
```

### Configuration Notes
This project uses local config files and local runtime state.
For safety, the following are typically excluded from version control:

- `.ace-tool/`
- `config.yaml`
- `outputs/`
- `logs/`
- `search_history.json`
- `.venv/`

### Repository Scope
This repository tracks the `grok-manager` application only.
It does not include:

- local runtime outputs
- local caches
- local logs
- sensitive config
- other related project repositories

### Current Status
The current version already covers the primary workflows and core enhancements, and is suitable as:

- a development milestone build
- an internal beta
- a base for further iteration

Ongoing focus areas include:

- NSFW boundary testing
- more granular error classification
- UI polish
- stronger automated testing and stability checks

### Notes
- The NSFW toggle is passed through the image generation pipeline, but it does not guarantee that all R18 content will be accepted upstream.
- NSFW / R18 generation can still be affected by dynamic moderation and rate limiting.
- The app depends on local services; if `grok2api` is not running, related features will fail.

### License
Add a license based on your actual open-source plan.
