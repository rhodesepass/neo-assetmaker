# 明日方舟通行证素材制作器

Arknights Pass Material Maker — 用于制作明日方舟电子通行证 2.0 素材的图形化工具。

## 功能概览

### 素材制作（核心功能）

- 可视化配置编辑界面，支持基础模式和高级模式
- 实时 JSON 配置预览
- 视频预览与裁剪，支持 0°/90°/180°/270° 旋转
- 时间轴控制与帧精准定位
- 多分辨率支持：360x640、480x854、720x1080
- 配置验证（UUID、颜色值、文件路径等）
- 截取帧编辑，从视频中截取帧并保存为图标
- 过渡效果预览（fade、move、swipe 等）

### 明日方舟叠加 UI

- Arknights 风格叠加层：干员名称、代号、条码、职业图标
- 自定义左上角文字（替代 Rhodes Island logo）
- 自定义右上栏文字
- 自定义图片叠加
- 600+ 干员信息库，支持模糊搜索

### 通行证模拟预览

- Rust 编写的 egui 模拟器，360x640 设备模拟
- 完整播放流程：入场过渡 → 入场视频 → 循环过渡 → 循环视频 + 叠加层
- Python ↔ Rust 通过 Windows 命名管道 IPC 通信

### 素材商城

- 在线素材市场，支持搜索、分类过滤、排序
- OAuth + FIDO2 认证登录
- 多线程下载引擎（最多 3 并发）
- 本地素材库管理
- USB/MTP 设备管理

### 其他功能

- 自动保存（5 分钟间隔）与崩溃恢复
- 自动更新检查（多源竞速：GitHub API + 代理源）
- 临时项目（启动即可编辑，首次保存时迁移）
- 固件烧录工具集成（FEL 模式、DFU 模式）
- 用户设置系统（主题、字体、视频、导出、网络）
- 快捷键帮助（F1）

## 系统要求

- Windows
- Python 3.10+
- [uv](https://docs.astral.sh/uv/)（包管理器）
- Rust 工具链（仅编译模拟器时需要）

## 安装与运行

### 1. 克隆项目

```bash
git clone <repository-url>
cd neo-assetmaker
```

### 2. 安装依赖

```bash
uv sync --no-install-project
```

### 3. 运行程序

```bash
uv run python main.py
```

## 使用方法

### 侧边栏导航

软件左侧侧边栏包含以下模块：

1. **固件烧录** — 为迷你 Linux 手持开发板烧录固件，支持 FEL 模式和 DFU 模式
2. **素材制作** — 核心功能，创建和编辑通行证素材
3. **素材商城** — 在线素材资源下载
4. **项目介绍** — 访问项目官网获取最新信息
5. **设置** — 主题、界面、视频、导出、网络等配置

### 创建项目

1. 点击顶部导航栏"文件" → "新建项目"
2. 选择项目目录
3. 在配置面板中填写各项配置
4. 点击"文件" → "保存"保存项目

### 打开现有项目

1. 点击"文件" → "打开项目"
2. 选择 `epconfig.json` 文件

### 配置面板

**基础模式：** 简化界面，适合快速创建素材，仅显示循环视频标签页。

**高级模式：** 完整功能，包含四个选项卡：

| 选项卡 | 内容 |
|--------|------|
| 基本信息 | UUID、名称、描述、分辨率、图标 |
| 视频配置 | 循环视频（必选）、入场视频（可选） |
| 过渡效果 | 进入过渡、循环过渡（none / fade / slide_down / slide_up / slide_left / slide_right） |
| 叠加 UI | none / arknights（干员模板）/ image（自定义图片） |

### 截取帧编辑

1. 在中间预览区切换到"截取帧编辑"标签页
2. 加载视频并定位到需要截取的帧
3. 点击"保存为图标"保存当前帧

### 临时项目

- 启动时自动创建临时项目，用户可立即开始编辑
- 首次保存时自动触发"另存为"，迁移到永久目录
- 关闭软件时自动清理临时项目

## 配置文件格式

配置文件为 JSON 格式（`epconfig.json`）：

```json
{
  "version": 1,
  "uuid": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "name": "示例素材",
  "description": "素材描述",
  "screen": "360x640",
  "icon": "icon.png",
  "loop": {
    "file": "loop.mp4",
    "is_image": false
  },
  "intro": {
    "enabled": false,
    "file": "",
    "duration": 5000000
  },
  "transition_in": {
    "type": "fade",
    "options": {
      "duration": 500000,
      "background_color": "#000000"
    }
  },
  "transition_loop": {
    "type": "none"
  },
  "overlay": {
    "type": "arknights",
    "arknights_options": {
      "appear_time": 100000,
      "operator_name": "OPERATOR",
      "operator_code": "ARKNIGHTS - UNK0",
      "barcode_text": "OPERATOR - ARKNIGHTS",
      "aux_text": "Operator of Rhodes Island",
      "staff_text": "STAFF",
      "color": "#000000",
      "top_left_rhodes": "",
      "top_right_bar_text": ""
    }
  }
}
```

时间单位为微秒（1 秒 = 1,000,000 微秒）。

## 目录结构

```
neo-assetmaker/
├── main.py                          # 应用入口
├── pyproject.toml                   # 项目配置和依赖管理
├── build.py                         # cx_Freeze + Inno Setup 构建脚本
├── build.bat                        # 批处理构建包装器
├── installer.iss                    # Inno Setup 安装程序配置
│
├── config/                          # 配置模块
│   ├── constants.py                 # 常量定义（分辨率、格式、默认值）
│   ├── epconfig.py                  # EPConfig 统一数据模型
│   └── operator_db.py               # 干员数据库（600+ 干员）
│
├── core/                            # 核心业务逻辑
│   ├── validator.py                 # EPConfig 配置校验器
│   ├── image_processor.py           # 图片缩放、旋转、格式转换
│   ├── video_processor.py           # 视频处理
│   ├── optimized_processor.py       # 优化的视频处理器
│   ├── overlay_renderer.py          # 叠加 UI 渲染器
│   ├── export_service.py            # 素材导出和打包服务
│   ├── auto_save_service.py         # 自动保存服务（5 分钟间隔）
│   ├── crash_recovery_service.py    # 崩溃恢复服务
│   ├── error_handler.py             # 错误处理（模式匹配 + 用户提示）
│   └── update_service.py            # 自动更新检查服务
│
├── gui/                             # 图形用户界面
│   ├── main_window.py               # 主窗口（无边框、自定义标题栏）
│   ├── widgets/                     # UI 组件
│   │   ├── config_panel.py          # 高级配置面板
│   │   ├── basic_config_panel.py    # 基础配置面板
│   │   ├── video_preview.py         # 视频预览
│   │   ├── json_preview.py          # JSON 配置预览
│   │   ├── timeline.py              # 时间轴控制
│   │   └── transition_preview.py    # 过渡效果预览
│   └── dialogs/                     # 对话框
│       ├── welcome_dialog.py        # 欢迎引导
│       ├── update_dialog.py         # 更新日志
│       ├── export_progress_dialog.py # 导出进度
│       ├── flasher_dialog.py        # 固件烧录
│       ├── shortcuts_dialog.py      # 快捷键帮助
│       └── crash_recovery_dialog.py # 崩溃恢复
│
├── utils/                           # 工具函数
│   ├── logger.py                    # 日志系统（轮转文件 + 自动清理）
│   ├── color_utils.py               # 颜色转换（hex ↔ RGB ↔ BGR）
│   └── file_utils.py                # 文件操作工具
│
├── _mext/                           # 素材商城扩展模块
│   ├── core/                        # API 配置、服务管理
│   ├── services/                    # API 客户端、OAuth 认证、FIDO2、下载引擎、USB/MTP
│   ├── models/                      # 素材、用户、下载状态数据模型
│   ├── ui/                          # 市场页、下载页、素材库页、登录页、USB 页、设置页
│   └── utils/                       # 平台检测、加密工具
│
├── resources/                       # 资源文件
│   ├── icons/                       # 应用图标
│   ├── data/                        # 干员信息库、叠加 UI 模板和素材
│   ├── class_icons/                 # 干员职业图标（8 个职业）
│   └── installer/                   # 安装程序资源（向导图、语言包、许可证）
│
├── simulator/                       # Rust 通行证模拟器
│   ├── src/                         # egui 应用、IPC、视频解码、渲染、动画
│   ├── resources/fonts/             # 嵌入字体（DejaVuSans-Bold）
│   └── Cargo.toml                   # Rust 项目配置
│
└── .github/workflows/               # CI/CD
    ├── build.yml                    # 自动构建（Rust + Python + Inno Setup）
    └── release.yml                  # 自动发布（CHANGELOG 版本变更触发）
```

## 构建与打包

### 本地构建

```bash
# 完整构建（exe + 安装程序）
uv run python build.py

# 清理构建目录
uv run python build.py --clean

# 跳过安装程序打包
uv run python build.py --no-installer

# 跳过 flasher bin 检查
uv run python build.py --skip-flasher

# 或使用批处理包装器（自动安装依赖）
build.bat
```

### 编译 Rust 模拟器

```bash
cd simulator && cargo build --release
```

### CI/CD

GitHub Actions 工作流位于 `.github/workflows/`：

- **build.yml** — push/PR 时自动构建：Rust 模拟器编译 → Python 应用打包 → Inno Setup 安装程序
- **release.yml** — `CHANGELOG.md` 版本号变更时自动创建 GitHub Release

构建环境：Windows Latest, Python 3.11, uv, Rust stable, FFmpeg, Inno Setup

## 开发说明

### 技术栈

| 层级 | 技术 | 位置 |
|------|------|------|
| GUI | PyQt6 + QFluentWidgets (Fluent Design) | `gui/` |
| 核心逻辑 | 服务模式、数据类模型 | `core/` |
| 配置系统 | dataclass + Enum + JSON Schema | `config/` |
| 扩展模块 | OAuth + PKCE、FIDO2、MTP | `_mext/` |
| 模拟器 | Rust (egui + FFmpeg) | `simulator/` |
| IPC | Windows 命名管道 (JSON) | `simulator/src/ipc/` |
| 视频处理 | OpenCV (Python) + FFmpeg (Rust) | `core/`, `simulator/` |
| 打包 | cx_Freeze + Inno Setup | `build.py` |
| 依赖管理 | uv + pyproject.toml | `pyproject.toml` |
| CI/CD | GitHub Actions | `.github/workflows/` |

### 架构概览

```
用户输入 (config_panel) → EPConfig 数据模型 (epconfig.py)
    → 验证器 (validator.py) → 错误处理 (error_handler.py)
    → 导出服务 (export_service.py)
        ├→ 图片处理 (image_processor.py)
        ├→ 叠加 UI 渲染 (overlay_renderer.py)
        └→ 视频处理 (video_processor.py)
    → 模拟器 (simulator) ← IPC 命名管道
```

核心数据模型 `EPConfig`（`config/epconfig.py`）是贯穿整个应用的统一配置对象。

### 代码规范

- 类名：PascalCase（`EPConfig`、`MainWindow`）
- 函数/方法：snake_case（`validate_config`、`setup_logger`）
- 常量：UPPER_SNAKE_CASE（`APP_VERSION`、`SCREEN_WIDTH`）
- 私有成员：`_leading_underscore`
- 异步 UI：`QThread` + 信号/槽模式
- 错误处理：集中式 `ErrorHandler`（`core/error_handler.py`）

## 日志系统

运行时在 `logs/` 目录下生成日志文件，格式为 `app_YYYYMMDD.log`。

| 级别 | 说明 |
|------|------|
| DEBUG | 详细调试信息（仅写入文件） |
| INFO | 一般信息（控制台 + 文件） |
| WARNING | 警告信息 |
| ERROR | 错误信息 |

日志使用 `RotatingFileHandler`，自动清理 30 天前的日志文件。日志目录按优先级降级：应用目录 → AppData → 系统临时目录。

## 许可证

本项目仅供学习和研究使用。

## 更新日志

详见 [CHANGELOG.md](CHANGELOG.md)。
