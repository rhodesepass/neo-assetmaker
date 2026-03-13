"""QSS 样式表热重载开发工具

用法：设置环境变量 QSS_DEV=1 启动应用即可激活。
修改项目根目录下的 dev.qss 文件，样式会实时生效。

采用智能分发模式：解析 QSS 选择器，按 objectName 匹配 widget
并直接调用其 setStyleSheet()，可覆盖已有样式。
"""

import logging
import os
import re

from PyQt6.QtCore import QFileSystemWatcher, QObject, QTimer
from PyQt6.QtWidgets import QMainWindow, QWidget

logger = logging.getLogger(__name__)

_DEV_QSS_TEMPLATE = """\
/* ============================================
 * QSS 热重载开发文件
 * 修改并保存此文件，样式将实时生效
 *
 * 使用 QWidget#objectName 选择器可直接覆盖
 * 对应 widget 的样式（智能分发模式）
 * ============================================ */

/* === 标题栏 === */
/*
QWidget#header_bar {
    background-color: rgba(40, 40, 40, 0.7);
    color: white;
    border-top-right-radius: 16px;
}
*/

/* === 侧边栏 === */
/*
QWidget#sidebar {
    background-color: rgba(40, 40, 40, 0.7);
    border-bottom-right-radius: 16px;
}
*/

/* === 内容区域 === */
/*
QWidget#content_stack {
    background-color: rgba(255, 255, 255, 0.95);
}
*/

/* === 预览容器 === */
/*
QWidget#preview_container {
    background-color: #1a1a1a;
    border-radius: 8px;
}
*/

/* === 全局规则（应用到 QMainWindow 级别）=== */
/*
QPushButton {
    border-radius: 6px;
}
*/
"""


class QSSHotReloader(QObject):
    """QSS 样式表热重载器（智能分发模式）"""

    def __init__(self, window: QMainWindow, qss_path: str):
        super().__init__(window)
        self._window = window
        self._qss_path = qss_path
        self._pending = False

        self._ensure_file()

        self._watcher = QFileSystemWatcher([qss_path], self)
        self._watcher.fileChanged.connect(self._on_file_changed)

        # 首次加载
        self._reload()
        logger.info("QSS 热重载已激活: %s", qss_path)

    def _ensure_file(self):
        """若文件不存在，创建带注释模板的初始文件"""
        if not os.path.exists(self._qss_path):
            with open(self._qss_path, "w", encoding="utf-8") as f:
                f.write(_DEV_QSS_TEMPLATE)
            logger.info("已创建 QSS 开发模板: %s", self._qss_path)

    def _on_file_changed(self, path: str):
        """文件变化信号处理（含防抖和重新监控）"""
        # 编辑器保存时可能先删除再创建文件，导致 watcher 失效
        if path not in self._watcher.files():
            self._watcher.addPath(path)

        if not self._pending:
            self._pending = True
            QTimer.singleShot(100, self._reload)

    def _reload(self):
        """读取 QSS 文件并应用"""
        self._pending = False
        try:
            with open(self._qss_path, "r", encoding="utf-8") as f:
                content = f.read()
            self._parse_and_apply(content)
            logger.info("QSS 热重载: 样式已更新")
        except FileNotFoundError:
            logger.warning("QSS 热重载: 文件不存在 %s", self._qss_path)
        except Exception:
            logger.exception("QSS 热重载: 加载失败")

    def _parse_and_apply(self, qss_text: str):
        """解析 QSS 并智能分发到对应 widget"""
        # 去除注释
        cleaned = re.sub(r"/\*.*?\*/", "", qss_text, flags=re.DOTALL)

        # 提取选择器块
        global_parts = []
        for match in re.finditer(r"([^{}]+)\{([^}]*)\}", cleaned):
            selector = match.group(1).strip()
            rules = match.group(2).strip()
            if not selector or not rules:
                continue

            obj_name = self._extract_object_name(selector)
            if obj_name:
                widget = self._window.findChild(QWidget, obj_name)
                if widget:
                    widget.setStyleSheet(f"{selector} {{ {rules} }}")
                else:
                    logger.warning(
                        "QSS 热重载: 未找到 widget '%s'", obj_name)
            else:
                global_parts.append(f"{selector} {{ {rules} }}")

        # 全局样式应用到 QMainWindow
        if global_parts:
            self._window.setStyleSheet("\n".join(global_parts))

    @staticmethod
    def _extract_object_name(selector: str) -> str | None:
        """从选择器中提取 #objectName"""
        m = re.search(r"#(\w+)", selector)
        return m.group(1) if m else None

    @staticmethod
    def try_attach(window: QMainWindow) -> "QSSHotReloader | None":
        """检查 QSS_DEV 环境变量，激活则返回实例"""
        if os.environ.get("QSS_DEV") != "1":
            return None
        qss_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "dev.qss"
        )
        return QSSHotReloader(window, qss_path)
