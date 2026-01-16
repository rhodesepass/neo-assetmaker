# 明日方舟通行证素材制作器

Arknights Pass Material Maker - 用于制作明日方舟电子通行证2.0素材的图形化工具。

## 项目简介

本工具融合了 ep_material_maker 和 decompiled 两个项目的功能，提供完整的通行证素材制作解决方案。

主要功能：
- 可视化配置编辑界面
- 实时JSON配置预览
- 视频预览与裁剪
- 时间轴控制
- 配置验证
- 老素材格式批量转换

## 系统要求

- Python 3.10+
- Windows / macOS / Linux

## 安装说明

### 1. 克隆或下载项目

```bash
git clone <repository-url>
cd arknights_pass_maker
```

### 2. 创建虚拟环境（推荐）

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS/Linux
source .venv/bin/activate
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 运行程序

```bash
python main.py
```

## 依赖列表

- PyQt6 >= 6.5.0 - GUI框架
- opencv-python >= 4.8.0 - 视频处理
- Pillow >= 10.0.0 - 图片处理
- numpy >= 1.24.0 - 数组运算
- jsonschema >= 4.17.0 - JSON验证
- easyocr >= 1.7.0 - OCR文字识别（用于识别干员名称）
- thefuzz >= 0.22.0 - 模糊字符串匹配
- python-Levenshtein >= 0.25.0 - 加速模糊匹配

## 使用方法

### 创建新项目

1. 文件 -> 新建项目
2. 选择项目目录
3. 在左侧配置面板中填写各项配置
4. 文件 -> 保存

### 打开现有项目

1. 文件 -> 打开项目
2. 选择 epconfig.json 文件

### 配置说明

左侧配置面板包含四个选项卡：

**基本信息**
- UUID: 唯一标识符
- 名称: 素材名称
- 描述: 素材描述
- 分辨率: 360x640, 480x854, 720x1080
- 图标: 可选的图标文件

**视频配置**
- 循环视频: 必选，循环播放的视频文件
- 入场视频: 可选，首次播放的入场动画

**过渡效果**
- 进入过渡: 视频开始时的过渡效果
- 循环过渡: 循环播放时的过渡效果
- 支持类型: none, fade, slide_down, slide_up, slide_left, slide_right

**叠加UI**
- 类型: none, arknights, image
- 明日方舟模板: 干员名称、代号、条码等
- 图片叠加: 自定义叠加图片

### 老素材转换

工具 -> 批量转换老素材

支持将老版本素材格式（epconfig.txt + logo.argb + overlay.argb + loop.mp4 + intro.mp4）转换为新格式。

老素材文件结构：
- loop.mp4 循环播放的视频（必选），384x640，h.264，颠倒180度。实际显示的是360x640
- overlay.argb：干员信息的UI叠层图片（可选，不存在就不显示），360x640，按bgra格式给出，颠倒180度。
- intro.mp4 入场视频（可选，存在则先播8s入场动画，再切换到循环播放视频），384x640，h.264，颠倒180度。实际显示的是360x640
- logo.argb：过场显示的图片。（可选，不存在则显示“罗德岛“logo），256x256，按bgra格式给出，X轴翻转。
- epconfig.txt 配置文件（可选）

## 配置文件格式

配置文件为JSON格式（epconfig.json），示例：

```json
{
  "version": 1,
  "uuid": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "name": "示例素材",
  "description": "素材描述",
  "screen": "360x640",
  "icon": "icon.png",
  "loop": {
    "file": "loop.mp4"
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
      "color": "#000000"
    }
  }
}
```

## 目录结构

```
arknights_pass_maker/
├── main.py                 # 应用入口
├── requirements.txt        # 依赖列表
├── README.md              # 说明文档
├── config/                # 配置模块
│   ├── constants.py       # 常量定义
│   └── epconfig.py        # 配置数据模型
├── core/                  # 核心业务逻辑
│   ├── validator.py       # 配置验证器
│   ├── video_processor.py # 视频处理
│   ├── image_processor.py # 图片处理
│   ├── export_service.py  # 导出服务
│   ├── legacy_converter.py # 老素材转换器
│   ├── operator_lookup.py # 干员信息查询 (v1.0.1)
│   ├── ocr_service.py     # OCR识别服务 (v1.0.1)
│   └── overlay_renderer.py # 叠加层渲染器
├── gui/                   # 图形界面
│   ├── main_window.py     # 主窗口
│   ├── dialogs/           # 对话框
│   │   ├── export_progress_dialog.py  # 导出进度
│   │   ├── operator_confirm_dialog.py # 干员确认 (v1.0.1)
│   │   ├── batch_convert_dialog.py    # 批量转换对话框
│   │   ├── welcome_dialog.py          # 欢迎对话框
│   │   └── shortcuts_dialog.py        # 快捷键帮助
│   └── widgets/           # UI组件
│       ├── config_panel.py    # 配置面板
│       ├── video_preview.py   # 视频预览
│       ├── timeline.py        # 时间轴
│       └── json_preview.py    # JSON预览
├── utils/                 # 工具函数
│   ├── logger.py          # 日志系统
│   ├── file_utils.py      # 文件操作
│   └── color_utils.py     # 颜色处理
├── resources/             # 资源文件
│   ├── icons/             # 图标
│   ├── class_icons/       # 职业图标
│   └── data/              # 数据文件 (v1.0.1)
│       ├── character_table.json    # 干员信息表
│       ├── handbookpos_table.json  # 干员颜色表
│       └── overlay_template.png    # 模板匹配图
└── logs/                  # 日志文件
```

## 日志

程序运行时会在 logs/ 目录下生成日志文件，格式为 app_YYYYMMDD.log。

日志级别：
- DEBUG: 详细调试信息（仅文件）
- INFO: 一般信息（控制台和文件）
- WARNING: 警告信息
- ERROR: 错误信息

## 开发说明

### 技术栈

- PyQt6: GUI框架
- OpenCV: 视频读取和处理
- Pillow: 图片处理
- dataclass: 配置数据模型

### 代码结构

- config/ - 配置相关代码
- core/ - 核心业务逻辑
- gui/ - 图形界面
- utils/ - 通用工具

## 许可证

本项目仅供学习和研究使用。

## 更新日志

### v1.0.4

**新功能**
- 新增首次运行欢迎引导对话框，介绍基本操作流程
- 新增快捷键帮助对话框 (F1)，分类展示所有快捷键
- 为所有控件添加 Tooltip 提示，方便用户理解功能

**UI 优化**
- 修复配置面板文本截断问题，增加面板宽度
- 修复旋转按钮显示不全问题 ("旋转 270°")
- 优化小窗口下的布局自适应，降低视频预览最小尺寸
- 使用 QStackedWidget 重构叠加UI选项卡，消除切换时的布局抖动
- 优化 Splitter 伸缩策略，改善窗口大小调整体验

**代码优化**
- 从仓库移除 ffmpeg.exe/ffprobe.exe (125MB)，改由 CI 自动下载
- 修复 config/firmware 模块缺少 __init__.py 导致打包失败的问题
- 统一版本号管理，修复各文件版本不一致问题

### v1.0.3
- 新增通行证模拟预览功能（工具 → 模拟预览）
  - 360×640 独立窗口模拟真机显示效果（50fps）
  - 完整播放流程：入场过渡 → 入场视频 → 循环过渡 → 循环视频+叠加层
  - 支持三种过渡效果：FADE（淡入淡出）、MOVE（贝塞尔滑动）、SWIPE（像素扫动）
  - 叠加层动画效果：
    - 入场动画：从底部向上滑入（1秒ease-in-out）
    - 文字打字机效果：干员名/代号逐字符显示
    - EINK电子墨水效果：条码/职业图标黑白闪烁后显示（5状态×15帧）
    - 颜色渐晕：右下角径向渐变
    - 进度条/分割线：贝塞尔曲线宽度动画
    - 箭头循环：持续上下扫动
  - 支持播放/暂停/重置控制
  - 首次过渡强制使用 SWIPE（与固件行为一致）
- 新增数据驱动架构
  - 固件配置提取器：从 C 源码自动提取 118 个常量和枚举
  - FirmwareConfig 数据模型：42 个便捷属性访问配置值
  - ConfigManager 配置管理器：单例模式，支持多配置切换
  - JSON 配置文件：`config/firmware/default.firmware.json`
  - 固件更新时只需重新运行提取脚本，无需修改 Python 代码
- 新增视频旋转预览功能
  - 支持 0°/90°/180°/270° 旋转
  - 时间轴添加旋转按钮，方便查看倒置的源视频素材
- 重构构建系统：从 7Z_SFX 改为 cx_Freeze + Inno Setup
- 添加自定义安装界面（欢迎文字、logo图片）
- 添加中文安装界面语言支持
- 添加许可协议页面（CC BY-NC-SA 风格）
- GitHub Actions 版本号自动同步到构建文件
- 视频编码质量提升（CRF 18，码率 3000k）

### v1.0.2
- 过渡效果图片自动调整为360x640分辨率
- 修复制作素材途中停止导致编辑器卡死的问题
- 修复导入素材时编辑器暂时卡死的问题
- 基本信息图标支持截取当前视频帧
- 循环视频支持图片模式（从图片生成1秒循环视频）
- 重构构建系统（cx_Freeze + 7Z_SFX）
- GitHub Actions支持README版本号变化自动发布

### v1.0.1
- 新增OCR自动识别干员名称功能
  - 使用EasyOCR从overlay图片中识别干员名称
  - 支持精确匹配和模糊匹配（相似度>80%）
  - 模糊匹配时弹窗让用户确认选择
- 新增干员信息库（600+干员）
  - 包含干员名称、代号、职业、势力、颜色等信息
  - 支持中英文名称搜索
- 批量转换增加overlay模式选项
  - auto：自动检测模板，OCR识别干员（推荐）
  - arknights：使用arknights模板 + OCR识别
  - arknights_default：使用arknights模板 + 默认值
  - image：保留原overlay图片
- 生成完整的arknights overlay配置
  - 自动填充干员名称、代号、职业图标
  - 自动获取干员专属颜色
- 新增依赖：easyocr, thefuzz, python-Levenshtein

### v1.0.0
- 初始版本
- 合并 ep_material_maker 和 decompiled 项目
- 三栏布局：配置面板 + 视频预览 + JSON预览
- 配置验证功能
- 老素材批量转换功能
