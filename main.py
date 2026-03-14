#!/usr/bin/env python3
"""
明日方舟通行证素材制作器
Arknights Pass Material Maker
"""
import sys
import os
import logging

# 打包环境兼容处理 (cx_Freeze)
if getattr(sys, 'frozen', False):
    # 冻结环境下获取应用目录
    APP_DIR = os.path.dirname(sys.executable)
    # 设置 PyQt6 插件路径
    plugin_path = os.path.join(APP_DIR, 'lib', 'PyQt6', 'Qt6', 'plugins')
    if os.path.exists(plugin_path):
        os.environ['QT_PLUGIN_PATH'] = plugin_path

    # 修复 GUI 模式下 stdout/stderr 为 None（base="gui" 隐藏控制台）
    import io
    if sys.stdout is None:
        sys.stdout = io.StringIO()
    if sys.stderr is None:
        sys.stderr = io.StringIO()

    # 启用 faulthandler — 捕获 segfault 的 Python traceback
    import faulthandler
    try:
        _crash_log_path = os.path.join(APP_DIR, 'crash.log')
        _crash_log_file = open(_crash_log_path, 'w')
        faulthandler.enable(file=_crash_log_file)
    except Exception:
        faulthandler.enable()
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

# 添加项目根目录到路径
sys.path.insert(0, APP_DIR)

# 扩展模块运行环境设置
os.environ["QT_API"] = "pyqt6"


def check_dependencies():
    """检查必要的依赖是否已安装"""
    missing = []

    try:
        from PyQt6.QtWidgets import QApplication
    except ImportError:
        missing.append("PyQt6")

    try:
        from PyQt6.QtWebEngineWidgets import QWebEngineView
    except ImportError:
        missing.append("PyQt6-WebEngine")

    try:
        import qfluentwidgets
    except ImportError:
        missing.append("QFluentWidgets")

    try:
        import cv2
    except ImportError:
        missing.append("opencv-python")

    try:
        from PIL import Image
    except ImportError:
        missing.append("Pillow")

    try:
        import numpy
    except ImportError:
        missing.append("numpy")

    if missing:
        print("缺少以下依赖:")
        for dep in missing:
            print(f"  - {dep}")
        print("\n请运行以下命令安装:")
        print(f"  pip install {' '.join(missing)}")
        sys.exit(1)


def _main_inner():
    """应用程序实际入口"""
    check_dependencies()

    # 禁用QFluentWidgets启动提示（必须在导入QFluentWidgets之前设置）
    import os
    os.environ["QFluentWidgets_SUPPRESS_TIPS"] = "1"

    # 初始化日志系统
    from utils.logger import setup_logger, cleanup_old_logs
    setup_logger()
    cleanup_old_logs(days=30)

    logger = logging.getLogger(__name__)
    logger.info("=" * 50)
    logger.info("明日方舟通行证素材制作器 启动")
    logger.info("=" * 50)

    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QFont, QIcon
    from PyQt6.QtCore import Qt

    from qfluentwidgets import setTheme, setThemeColor, Theme

    from gui.main_window import MainWindow
    from config.constants import APP_VERSION

    # 创建应用程序
    app = QApplication(sys.argv)
    app.setApplicationName("明日方舟通行证素材制作器")
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("ArknightsPassMaker")

    # 设置Fluent主题
    setTheme(Theme.AUTO)
    setThemeColor("#ff6b8b")

    # 设置应用程序图标
    icon_path = os.path.join(APP_DIR, 'resources', 'icons', 'favicon.ico')
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    # Windows 平台设置中文字体
    if sys.platform == "win32":
        font = QFont("Microsoft YaHei", 9)
        app.setFont(font)

    # 创建并显示主窗口
    logger.info("创建主窗口...")
    window = MainWindow()
    window.show()

    logger.info("应用程序启动完成")

    # 运行应用程序
    exit_code = app.exec()
    logger.info(f"应用程序退出，退出码: {exit_code}")
    sys.exit(exit_code)


def main():
    """应用程序入口 — 包裹全局异常处理"""
    try:
        _main_inner()
    except Exception:
        import traceback
        error_text = traceback.format_exc()
        # 写入崩溃日志
        try:
            log_path = os.path.join(
                os.environ.get('TEMP', '.'),
                'ArknightsPassMaker_crash.log')
            with open(log_path, 'w', encoding='utf-8') as f:
                f.write(error_text)
        except Exception:
            pass
        # 尝试显示错误对话框
        try:
            from PyQt6.QtWidgets import QApplication, QMessageBox
            app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(None, "致命错误", error_text[:1000])
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
