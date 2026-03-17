#!/usr/bin/env python3
"""
明日方舟通行证素材制作器
Arknights Pass Material Maker
"""
import sys
import os
import logging

if getattr(sys, 'frozen', False):
    APP_DIR = os.path.dirname(sys.executable)
    plugin_path = os.path.join(APP_DIR, 'lib', 'PyQt6', 'Qt6', 'plugins')
    if os.path.exists(plugin_path):
        os.environ['QT_PLUGIN_PATH'] = plugin_path

    # 修复 GUI 模式下 stdout/stderr 为 None（base="gui" 隐藏控制台）
    # cx_Freeze FAQ 推荐重定向到文件而非 StringIO，否则异常诊断信息会丢失
    # https://cx-freeze.readthedocs.io/en/stable/faq.html
    import io
    if sys.stdout is None:
        try:
            sys.stdout = open(os.path.join(APP_DIR, 'stdout.log'), 'w', encoding='utf-8')
        except Exception:
            sys.stdout = io.StringIO()
    if sys.stderr is None:
        try:
            sys.stderr = open(os.path.join(APP_DIR, 'stderr.log'), 'w', encoding='utf-8')
        except Exception:
            sys.stderr = io.StringIO()

    import faulthandler
    try:
        _crash_log_path = os.path.join(APP_DIR, 'crash.log')
        _crash_log_file = open(_crash_log_path, 'w')
        faulthandler.enable(file=_crash_log_file)
    except Exception:
        faulthandler.enable()
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

sys.path.insert(0, APP_DIR)



def check_dependencies():
    """检查必要的依赖是否已安装

    注意：此函数必须在 QApplication 创建之后调用。
    QtWebEngine 在 QApplication 之前加载会导致 COM 初始化冲突，
    触发 Windows fatal exception 0x8001010d (RPC_E_CANTCALLOUT_ININPUTSYNCCALL)。
    参考: https://doc.qt.io/qt-6/qopenglwidget.html (AA_ShareOpenGLContexts)
    """
    missing = []

    try:
        from PyQt6.QtWidgets import QApplication
    except ImportError:
        missing.append("PyQt6")

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

    # QtWebEngine 检查放在最后 — 必须在 QApplication 创建之后导入，
    # 否则 Chromium DLL 的 CoInitializeEx(COINIT_MULTITHREADED) 会与
    # Qt OLE 子系统的 COINIT_APARTMENTTHREADED 冲突
    try:
        from PyQt6.QtWebEngineWidgets import QWebEngineView
    except ImportError:
        missing.append("PyQt6-WebEngine")

    if missing:
        print("缺少以下依赖:")
        for dep in missing:
            print(f"  - {dep}")
        print("\n请运行以下命令安装:")
        print(f"  pip install {' '.join(missing)}")
        sys.exit(1)


def _main_inner():
    """应用程序实际入口"""
    # 创建命名互斥量，配合 installer.iss 的 AppMutex 防止安装时应用正在运行
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.kernel32.CreateMutexW(None, False, "ArknightsPassMakerMutex")

    # 禁用QFluentWidgets启动提示（必须在导入QFluentWidgets之前设置）
    os.environ["QFluentWidgets_SUPPRESS_TIPS"] = "1"

    from utils.logger import setup_logger, cleanup_old_logs
    setup_logger()
    cleanup_old_logs(days=30)

    logger = logging.getLogger(__name__)

    # 安装全局异常钩子 — 防止 PyQt6 slot 中未处理异常导致 abort
    # PyQt6 行为：slot/callback 中未处理异常调用 sys.excepthook，
    # 默认实现打印到 stderr 后 qFatal() → abort。
    # 自定义 hook 记录异常后正常返回，sip 不再调用 qFatal()。
    # https://docs.python.org/3/library/sys.html#sys.excepthook
    def _excepthook(exc_type, exc_value, exc_tb):
        import traceback
        msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logger.critical(f"未捕获异常:\n{msg}")
        try:
            sys.stderr.write(msg)
            sys.stderr.flush()
        except Exception:
            pass

    sys.excepthook = _excepthook

    logger.info("=" * 50)
    logger.info("明日方舟通行证素材制作器 启动")
    logger.info("=" * 50)

    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QFont, QIcon
    from PyQt6.QtCore import Qt

    # 同时使用 QOpenGLWidget 和 QWebEngineView 时，必须在 QApplication 之前设置
    # https://doc.qt.io/qt-6/qopenglwidget.html
    # > If your application uses both QOpenGLWidget and QWebEngineView,
    # > make sure that you call setAttribute(Qt::AA_ShareOpenGLContexts)
    # > before the QApplication constructor.
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

    app = QApplication(sys.argv)

    # 依赖检查必须在 QApplication 之后，避免 QtWebEngine 在 QApplication 之前
    # 加载导致 COM 公寓模型冲突 (Windows fatal exception 0x8001010d)
    check_dependencies()

    from qfluentwidgets import setTheme, setThemeColor, Theme

    from gui.main_window import MainWindow
    from config.constants import APP_VERSION
    app.setApplicationName("明日方舟通行证素材制作器")
    app.setApplicationVersion(APP_VERSION)
    app.setOrganizationName("ArknightsPassMaker")

    setTheme(Theme.AUTO)
    setThemeColor("#ff6b8b")

    icon_path = os.path.join(APP_DIR, 'resources', 'icons', 'favicon.ico')
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    if sys.platform == "win32":
        font = QFont("Microsoft YaHei", 9)
        app.setFont(font)

    logger.info("创建主窗口...")
    window = MainWindow()
    window.show()

    logger.info("应用程序启动完成")

    exit_code = app.exec()
    logger.info(f"应用程序退出，退出码: {exit_code}")
    logging.shutdown()
    sys.exit(exit_code)


def main():
    """应用程序入口 — 包裹全局异常处理"""
    try:
        _main_inner()
    except Exception:
        import traceback
        error_text = traceback.format_exc()
        try:
            log_path = os.path.join(
                os.environ.get('TEMP', '.'),
                'ArknightsPassMaker_crash.log')
            with open(log_path, 'w', encoding='utf-8') as f:
                f.write(error_text)
        except Exception:
            pass
        try:
            from PyQt6.QtWidgets import QApplication, QMessageBox
            app = QApplication.instance() or QApplication(sys.argv)
            QMessageBox.critical(None, "致命错误", error_text[:1000])
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
