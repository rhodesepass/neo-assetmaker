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


def main():
    """应用程序入口"""
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


if __name__ == "__main__":
    main()
