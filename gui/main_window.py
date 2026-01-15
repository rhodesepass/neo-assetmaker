"""
主窗口 - 三栏布局
"""
import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QMenuBar, QMenu, QStatusBar,
    QFileDialog, QMessageBox, QLabel
)
from PyQt6.QtCore import Qt, QSettings
from PyQt6.QtGui import QAction, QKeySequence, QIcon

from config.epconfig import EPConfig
from config.constants import APP_NAME, APP_VERSION, get_resolution_spec
from gui.widgets.config_panel import ConfigPanel
from gui.widgets.video_preview import VideoPreviewWidget
from gui.widgets.timeline import TimelineWidget
from gui.widgets.json_preview import JsonPreviewWidget


class MainWindow(QMainWindow):
    """主窗口"""

    def __init__(self, parent=None):
        super().__init__(parent)

        self._config: Optional[EPConfig] = None
        self._project_path: str = ""
        self._base_dir: str = ""
        self._is_modified: bool = False

        self._setup_ui()
        self._setup_menu()
        self._setup_icon()
        self._connect_signals()
        self._load_settings()

        self._update_title()
        logger.info("主窗口初始化完成")

    def _setup_icon(self):
        """设置窗口图标"""
        icon_path = os.path.join(
            os.path.dirname(__file__), '..', 'resources', 'icons', 'favicon.ico'
        )
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            logger.debug(f"已加载窗口图标: {icon_path}")
        else:
            logger.warning(f"窗口图标文件不存在: {icon_path}")

    def _setup_ui(self):
        """设置UI"""
        self.setWindowTitle(f"{APP_NAME} v{APP_VERSION}")
        self.setMinimumSize(1200, 800)

        # 中心部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 主布局
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 三栏分割器
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(self.splitter)

        # === 左侧: 配置面板 ===
        self.config_panel = ConfigPanel()
        self.splitter.addWidget(self.config_panel)

        # === 中间: 视频预览 + 时间轴 ===
        preview_container = QWidget()
        preview_layout = QVBoxLayout(preview_container)
        preview_layout.setContentsMargins(5, 5, 5, 5)
        preview_layout.setSpacing(5)

        self.video_preview = VideoPreviewWidget()
        preview_layout.addWidget(self.video_preview, stretch=1)

        self.timeline = TimelineWidget()
        preview_layout.addWidget(self.timeline)

        self.splitter.addWidget(preview_container)

        # === 右侧: JSON预览 ===
        self.json_preview = JsonPreviewWidget()
        self.splitter.addWidget(self.json_preview)

        # 设置分割比例
        self.splitter.setSizes([350, 600, 350])
        self.splitter.setStretchFactor(0, 0)  # 左侧固定
        self.splitter.setStretchFactor(1, 1)  # 中间可伸缩
        self.splitter.setStretchFactor(2, 0)  # 右侧固定

        # 状态栏
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪")

    def _setup_menu(self):
        """设置菜单"""
        menubar = self.menuBar()

        # 文件菜单
        file_menu = menubar.addMenu("文件(&F)")

        self.action_new = QAction("新建项目(&N)", self)
        self.action_new.setShortcut(QKeySequence.StandardKey.New)
        file_menu.addAction(self.action_new)

        self.action_open = QAction("打开项目(&O)...", self)
        self.action_open.setShortcut(QKeySequence.StandardKey.Open)
        file_menu.addAction(self.action_open)

        self.action_save = QAction("保存(&S)", self)
        self.action_save.setShortcut(QKeySequence.StandardKey.Save)
        file_menu.addAction(self.action_save)

        self.action_save_as = QAction("另存为(&A)...", self)
        self.action_save_as.setShortcut(QKeySequence("Ctrl+Shift+S"))
        file_menu.addAction(self.action_save_as)

        file_menu.addSeparator()

        self.action_exit = QAction("退出(&X)", self)
        self.action_exit.setShortcut(QKeySequence.StandardKey.Quit)
        file_menu.addAction(self.action_exit)

        # 工具菜单
        tools_menu = menubar.addMenu("工具(&T)")

        self.action_validate = QAction("验证配置(&V)", self)
        self.action_validate.setShortcut(QKeySequence("Ctrl+T"))
        tools_menu.addAction(self.action_validate)

        self.action_export = QAction("导出素材(&E)...", self)
        self.action_export.setShortcut(QKeySequence("Ctrl+E"))
        tools_menu.addAction(self.action_export)

        tools_menu.addSeparator()

        self.action_simulator = QAction("模拟预览(&M)...", self)
        self.action_simulator.setShortcut(QKeySequence("Ctrl+M"))
        self.action_simulator.setToolTip("打开通行证模拟器，预览实际显示效果")
        tools_menu.addAction(self.action_simulator)

        tools_menu.addSeparator()

        self.action_batch_convert = QAction("批量转换老素材(&B)...", self)
        tools_menu.addAction(self.action_batch_convert)

        # 帮助菜单
        help_menu = menubar.addMenu("帮助(&H)")

        self.action_about = QAction("关于(&A)", self)
        help_menu.addAction(self.action_about)

    def _connect_signals(self):
        """连接信号"""
        # 菜单动作
        self.action_new.triggered.connect(self._on_new_project)
        self.action_open.triggered.connect(self._on_open_project)
        self.action_save.triggered.connect(self._on_save_project)
        self.action_save_as.triggered.connect(self._on_save_as)
        self.action_exit.triggered.connect(self.close)
        self.action_validate.triggered.connect(self._on_validate)
        self.action_export.triggered.connect(self._on_export)
        self.action_simulator.triggered.connect(self._on_simulator)
        self.action_batch_convert.triggered.connect(self._on_batch_convert)
        self.action_about.triggered.connect(self._on_about)

        # 配置面板
        self.config_panel.config_changed.connect(self._on_config_changed)
        self.config_panel.video_file_selected.connect(self._on_video_file_selected)
        self.config_panel.validate_requested.connect(self._on_validate)
        self.config_panel.export_requested.connect(self._on_export)
        self.config_panel.capture_frame_requested.connect(self._on_capture_frame)

        # 视频预览
        self.video_preview.video_loaded.connect(self._on_video_loaded)
        self.video_preview.frame_changed.connect(self._on_frame_changed)
        self.video_preview.playback_state_changed.connect(self._on_playback_changed)

        # 时间轴
        self.timeline.play_pause_clicked.connect(self.video_preview.toggle_play)
        self.timeline.seek_requested.connect(self.video_preview.seek_to_frame)
        self.timeline.prev_frame_clicked.connect(self.video_preview.prev_frame)
        self.timeline.next_frame_clicked.connect(self.video_preview.next_frame)
        self.timeline.goto_start_clicked.connect(lambda: self.video_preview.seek_to_frame(0))
        self.timeline.goto_end_clicked.connect(
            lambda: self.video_preview.seek_to_frame(self.video_preview.total_frames - 1)
        )
        self.timeline.set_in_point_clicked.connect(self.timeline.set_in_point_to_current)
        self.timeline.set_out_point_clicked.connect(self.timeline.set_out_point_to_current)
        self.timeline.preview_mode_changed.connect(self.video_preview.set_preview_mode)
        self.timeline.rotation_clicked.connect(self.video_preview.rotate_clockwise)
        self.video_preview.rotation_changed.connect(self.timeline.set_rotation)

    def _load_settings(self):
        """加载设置"""
        settings = QSettings("ArknightsPassMaker", "MainWindow")
        geometry = settings.value("geometry")
        if geometry:
            self.restoreGeometry(geometry)
            logger.debug("已恢复窗口几何设置")

    def _save_settings(self):
        """保存设置"""
        settings = QSettings("ArknightsPassMaker", "MainWindow")
        settings.setValue("geometry", self.saveGeometry())
        logger.debug("已保存窗口几何设置")

    def _update_title(self):
        """更新窗口标题"""
        title = f"{APP_NAME} v{APP_VERSION}"
        if self._project_path:
            title = f"{os.path.basename(self._project_path)} - {title}"
        if self._is_modified:
            title = f"* {title}"
        self.setWindowTitle(title)

    def _on_new_project(self):
        """新建项目"""
        if not self._check_save():
            return

        # 选择目录
        dir_path = QFileDialog.getExistingDirectory(
            self, "选择项目目录", ""
        )
        if not dir_path:
            return

        # 创建新配置
        self._config = EPConfig()
        self._base_dir = dir_path
        self._project_path = os.path.join(dir_path, "epconfig.json")
        self._is_modified = True

        # 更新UI
        self.config_panel.set_config(self._config, self._base_dir)
        self.json_preview.set_config(self._config, self._base_dir)
        self.video_preview.set_epconfig(self._config)
        self._update_title()
        self.status_bar.showMessage(f"新建项目: {dir_path}")

    def _on_open_project(self):
        """打开项目"""
        if not self._check_save():
            return

        path, _ = QFileDialog.getOpenFileName(
            self, "打开配置文件", "",
            "JSON文件 (*.json);;所有文件 (*.*)"
        )
        if not path:
            return

        try:
            self._config = EPConfig.load_from_file(path)
            self._project_path = path
            self._base_dir = os.path.dirname(path)
            self._is_modified = False

            # 更新UI
            self.config_panel.set_config(self._config, self._base_dir)
            self.json_preview.set_config(self._config, self._base_dir)
            self.video_preview.set_epconfig(self._config)

            # 尝试加载循环视频（延迟执行，避免阻塞UI）
            if self._config.loop.file:
                video_path = self._config.loop.file
                # 如果是相对路径，转换为绝对路径
                if not os.path.isabs(video_path):
                    video_path = os.path.join(self._base_dir, video_path)
                logger.info(f"尝试加载循环视频: {video_path}")
                if os.path.exists(video_path):
                    # 使用 singleShot 延迟加载，让UI先完成更新
                    from PyQt6.QtCore import QTimer
                    QTimer.singleShot(100, lambda vp=video_path: self.video_preview.load_video(vp))
                else:
                    logger.warning(f"循环视频文件不存在: {video_path}")

            self._update_title()
            self.status_bar.showMessage(f"已打开: {path}")

        except Exception as e:
            QMessageBox.critical(self, "错误", f"打开文件失败:\n{e}")

    def _on_save_project(self):
        """保存项目"""
        if not self._config:
            return

        if not self._project_path:
            self._on_save_as()
            return

        try:
            self._config.save_to_file(self._project_path)
            self._is_modified = False
            self._update_title()
            self.status_bar.showMessage(f"已保存: {self._project_path}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败:\n{e}")

    def _on_save_as(self):
        """另存为"""
        if not self._config:
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "保存配置文件",
            self._project_path or "epconfig.json",
            "JSON文件 (*.json)"
        )
        if not path:
            return

        try:
            self._config.save_to_file(path)
            self._project_path = path
            self._base_dir = os.path.dirname(path)
            self._is_modified = False
            self._update_title()
            self.status_bar.showMessage(f"已保存: {path}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存失败:\n{e}")

    def _on_validate(self):
        """验证配置"""
        if not self._config:
            QMessageBox.information(self, "提示", "请先创建或打开项目")
            return

        from core.validator import EPConfigValidator

        validator = EPConfigValidator(self._base_dir)
        results = validator.validate_config(self._config)

        if not validator.has_errors():
            QMessageBox.information(self, "验证通过", validator.get_summary())
        else:
            errors = validator.get_errors()
            warnings = validator.get_warnings()

            msg = f"{validator.get_summary()}\n\n"
            if errors:
                msg += "错误:\n"
                for r in errors[:5]:
                    msg += f"  - {r}\n"
            if warnings:
                msg += "\n警告:\n"
                for r in warnings[:5]:
                    msg += f"  - {r}\n"

            QMessageBox.warning(self, "验证结果", msg)

    def _on_export(self):
        """导出素材"""
        if not self._config:
            QMessageBox.information(self, "提示", "请先创建或打开项目")
            return

        # 验证配置
        from core.validator import EPConfigValidator
        validator = EPConfigValidator(self._base_dir)
        validator.validate_config(self._config)

        if validator.has_errors():
            errors = validator.get_errors()
            msg = "配置验证失败，无法导出:\n\n"
            for r in errors[:5]:
                msg += f"  - {r}\n"
            QMessageBox.critical(self, "验证失败", msg)
            return

        # 检查视频是否加载
        if not self.video_preview.video_path:
            QMessageBox.warning(
                self, "警告",
                "请先加载视频文件\n\n"
                "在配置面板的'视频配置'选项卡中选择循环视频文件"
            )
            return

        # 选择导出目录
        dir_path = QFileDialog.getExistingDirectory(
            self, "选择导出目录", self._base_dir
        )
        if not dir_path:
            return

        # 收集导出数据
        try:
            export_data = self._collect_export_data()
        except Exception as e:
            logger.error(f"收集导出数据失败: {e}")
            QMessageBox.critical(self, "错误", f"收集导出数据失败:\n{e}")
            return

        # 处理arknights叠加的自定义图片
        try:
            self._process_arknights_custom_images(dir_path)
        except Exception as e:
            logger.error(f"处理自定义图片失败: {e}")
            QMessageBox.warning(self, "警告", f"处理自定义图片失败:\n{e}\n\n将继续导出其他内容。")

        # 创建导出服务和进度对话框
        from core.export_service import ExportService
        from gui.dialogs.export_progress_dialog import ExportProgressDialog

        self._export_service = ExportService(self)
        self._export_dialog = ExportProgressDialog(self)

        # 连接信号
        self._export_service.progress_updated.connect(
            self._export_dialog.update_progress
        )
        self._export_service.export_completed.connect(
            lambda msg: self._on_export_completed(True, msg)
        )
        self._export_service.export_failed.connect(
            lambda msg: self._on_export_completed(False, msg)
        )
        self._export_dialog.cancel_requested.connect(
            self._export_service.cancel
        )

        # 启动导出
        self._export_service.export_all(
            output_dir=dir_path,
            epconfig=self._config,
            logo_mat=export_data.get('logo_mat'),
            overlay_mat=export_data.get('overlay_mat'),
            loop_video_params=export_data.get('loop_video_params'),
            intro_video_params=export_data.get('intro_video_params')
        )

        # 显示进度对话框
        self._export_dialog.exec()

    def _on_simulator(self):
        """打开模拟器预览"""
        if not self._config:
            QMessageBox.information(self, "提示", "请先创建或打开项目")
            return

        # 检查是否有循环视频
        if not self._config.loop.file:
            QMessageBox.warning(
                self, "警告",
                "请先配置循环视频文件\n\n"
                "在配置面板的'视频配置'选项卡中选择循环视频文件"
            )
            return

        # 创建并显示模拟器对话框
        from gui.dialogs.pass_simulator_dialog import PassSimulatorDialog

        dialog = PassSimulatorDialog(self)
        dialog.set_config(self._config, self._base_dir)
        dialog.exec()

    def _on_batch_convert(self):
        """批量转换老素材"""
        from core.legacy_converter import LegacyConverter

        # 选择源目录
        src_dir = QFileDialog.getExistingDirectory(
            self, "选择老素材所在目录", ""
        )
        if not src_dir:
            return

        # 选择目标目录
        dst_dir = QFileDialog.getExistingDirectory(
            self, "选择转换后的保存目录", ""
        )
        if not dst_dir:
            return

        # 选择overlay处理模式
        overlay_mode, auto_ocr, ok = self._ask_overlay_mode()
        if not ok:
            return

        # 确认转换
        if overlay_mode == "auto":
            mode_desc = "自动检测（OCR识别干员）"
        elif overlay_mode == "arknights":
            mode_desc = "arknights模板" + ("（OCR识别）" if auto_ocr else "（默认值）")
        else:
            mode_desc = "保留原有overlay图片"

        result = QMessageBox.question(
            self, "确认转换",
            f"将从以下目录转换老素材:\n\n"
            f"源目录: {src_dir}\n"
            f"目标目录: {dst_dir}\n"
            f"Overlay模式: {mode_desc}\n\n"
            f"注意: 视频将重新编码（旋转180度校正），可能需要较长时间。\n"
            f"如果启用OCR识别，首次运行需要下载模型（约100MB）。\n\n"
            f"是否继续?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if result != QMessageBox.StandardButton.Yes:
            return

        # 执行转换
        logger.info(f"开始批量转换: {src_dir} -> {dst_dir}, overlay_mode={overlay_mode}, auto_ocr={auto_ocr}")

        try:
            from gui.dialogs.batch_convert_dialog import BatchConvertDialog

            converter = LegacyConverter()

            # 设置OCR确认回调
            confirm_callback = self._on_ocr_confirm if auto_ocr else None

            # 使用进度对话框
            dialog = BatchConvertDialog(self)
            dialog.start(
                converter, src_dir, dst_dir,
                overlay_mode, auto_ocr,
                confirm_callback=confirm_callback
            )
            dialog.exec()

            results = dialog.get_results()

            # 显示结果摘要
            if results:
                success_count = sum(1 for r in results if r.success)
                summary = f"转换完成: {success_count}/{len(results)} 成功"
                self.status_bar.showMessage(summary)
            else:
                QMessageBox.warning(
                    self, "转换结果",
                    f"未找到可转换的老素材文件夹\n\n"
                    f"老素材格式应包含:\n"
                    f"  - loop.mp4 (必需)\n"
                    f"  - epconfig.txt (可选)\n"
                    f"  - logo.argb (可选)\n"
                    f"  - overlay.argb (可选)\n"
                    f"  - intro.mp4 (可选)"
                )
                self.status_bar.showMessage("未找到老素材")

        except Exception as e:
            logger.error(f"批量转换失败: {e}")
            QMessageBox.critical(self, "错误", f"转换失败:\n{e}")
            self.status_bar.showMessage("转换失败")

    def _ask_overlay_mode(self):
        """询问用户overlay处理模式"""
        from PyQt6.QtWidgets import QInputDialog

        items = [
            "auto - 自动检测（OCR识别干员，非标准模板用图片）[推荐]",
            "arknights - 使用arknights模板（OCR识别干员名称）",
            "arknights_default - 使用arknights模板（默认干员名称）",
            "image - 保留并转换老overlay图片"
        ]
        item, ok = QInputDialog.getItem(
            self,
            "选择Overlay模式",
            "如何处理老素材的overlay.argb文件？\n\n"
            "推荐选择 auto 模式，将自动识别干员信息。\n"
            "首次使用OCR功能需要下载模型（约100MB）。",
            items,
            0,  # 默认选择auto
            False  # 不可编辑
        )
        if ok:
            if "auto" in item:
                return "auto", True, True
            elif "arknights_default" in item:
                return "arknights", False, True
            elif "arknights" in item:
                return "arknights", True, True
            else:
                return "image", False, True
        return "auto", True, False

    def _on_ocr_confirm(self, ocr_text: str, candidates: list):
        """
        OCR模糊匹配确认回调

        Args:
            ocr_text: OCR识别的文本
            candidates: 候选干员列表 [(OperatorInfo, score), ...]

        Returns:
            用户选择的干员，或None
        """
        from gui.dialogs.operator_confirm_dialog import OperatorConfirmDialog
        from core.operator_lookup import get_operator_lookup

        try:
            lookup = get_operator_lookup()
            dialog = OperatorConfirmDialog(
                ocr_text, candidates,
                operator_lookup=lookup,
                parent=self
            )

            if dialog.exec() == dialog.Accepted:
                return dialog.get_selected_operator()
            return None

        except Exception as e:
            logger.error(f"OCR确认对话框出错: {e}")
            return None

    def _on_about(self):
        """关于"""
        QMessageBox.about(
            self, f"关于 {APP_NAME}",
            f"<h3>{APP_NAME}</h3>"
            f"<p>版本: {APP_VERSION}</p>"
            f"<p>明日方舟通行证素材制作器</p>"
            f"<p>by Rafael_ban</p>"
        )

    def _on_config_changed(self):
        """配置变更"""
        self._is_modified = True
        self._update_title()

        # 更新JSON预览
        if self._config:
            self.json_preview.set_config(self._config, self._base_dir)
            # 更新视频预览的叠加UI配置
            self.video_preview.set_epconfig(self._config)

    def _on_video_file_selected(self, path: str):
        """视频文件被选择"""
        logger.info(f"视频文件被选择: {path}")
        if path and os.path.exists(path):
            self.video_preview.load_video(path)
        else:
            logger.warning(f"视频文件不存在: {path}")

    def _on_video_loaded(self, total_frames: int, fps: float):
        """视频加载完成"""
        self.timeline.set_total_frames(total_frames)
        self.timeline.set_fps(fps)
        self.timeline.set_in_point(0)
        self.timeline.set_out_point(total_frames - 1)
        self.status_bar.showMessage(f"视频已加载: {total_frames} 帧, {fps:.1f} FPS")

    def _on_frame_changed(self, frame: int):
        """帧变更"""
        self.timeline.set_current_frame(frame)

    def _on_playback_changed(self, is_playing: bool):
        """播放状态变更"""
        self.timeline.set_playing(is_playing)

    def _on_capture_frame(self):
        """截取当前视频帧作为图标"""
        if not self._base_dir:
            QMessageBox.warning(self, "警告", "请先创建或打开项目")
            return

        # 获取当前帧
        frame = self.video_preview.current_frame
        if frame is None:
            QMessageBox.warning(self, "警告", "请先加载视频")
            return

        # 保存为图标文件
        import cv2
        icon_path = os.path.join(self._base_dir, "icon.png")
        cv2.imwrite(icon_path, frame)

        # 更新配置
        self.config_panel.edit_icon.setText("icon.png")
        self.status_bar.showMessage("已截取视频帧作为图标")

    def _collect_export_data(self) -> dict:
        """收集导出所需的数据"""
        from core.export_service import VideoExportParams
        from core.image_processor import ImageProcessor

        data = {}

        # 收集 Logo/Icon 图片
        icon_path = self._config.icon
        if icon_path:
            if not os.path.isabs(icon_path):
                icon_path = os.path.join(self._base_dir, icon_path)
            if os.path.exists(icon_path):
                logo_img = ImageProcessor.load_image(icon_path)
                if logo_img is not None:
                    data['logo_mat'] = ImageProcessor.process_for_logo(logo_img)

        # 收集循环视频参数
        if self.video_preview.video_path:
            cropbox = self.video_preview.get_cropbox()
            in_point = self.timeline.get_in_point()
            out_point = self.timeline.get_out_point()

            data['loop_video_params'] = VideoExportParams(
                video_path=self.video_preview.video_path,
                cropbox=cropbox,
                start_frame=in_point,
                end_frame=out_point,
                fps=self.video_preview.video_fps,
                resolution=self._config.screen.value
            )

        # 收集入场视频参数 (如果启用)
        if self._config.intro.enabled and self._config.intro.file:
            intro_path = self._config.intro.file
            if not os.path.isabs(intro_path):
                intro_path = os.path.join(self._base_dir, intro_path)

            if os.path.exists(intro_path):
                import cv2
                cap = cv2.VideoCapture(intro_path)
                if cap.isOpened():
                    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
                    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                    cap.release()

                    data['intro_video_params'] = VideoExportParams(
                        video_path=intro_path,
                        cropbox=(0, 0, width, height),
                        start_frame=0,
                        end_frame=total_frames,
                        fps=fps,
                        resolution=self._config.screen.value
                    )

        return data

    def _process_arknights_custom_images(self, output_dir: str):
        """
        处理arknights叠加的自定义图片

        将自定义的logo和operator_class_icon缩放后复制到导出目录

        Args:
            output_dir: 导出目录
        """
        from config.epconfig import OverlayType
        from config.constants import ARK_CLASS_ICON_SIZE, ARK_LOGO_SIZE
        from core.image_processor import ImageProcessor
        import cv2

        if not self._config:
            return

        # 检查是否为arknights类型叠加
        if self._config.overlay.type != OverlayType.ARKNIGHTS:
            return

        ark_opts = self._config.overlay.arknights_options
        if not ark_opts:
            return

        # 处理职业图标 (50x50)
        if ark_opts.operator_class_icon:
            src_path = ark_opts.operator_class_icon
            if not os.path.isabs(src_path):
                src_path = os.path.join(self._base_dir, src_path)

            if os.path.exists(src_path):
                img = ImageProcessor.load_image(src_path)
                if img is not None:
                    # 缩放到目标尺寸
                    img = cv2.resize(img, ARK_CLASS_ICON_SIZE)
                    # 保存到导出目录
                    dst_filename = "class_icon.png"
                    dst_path = os.path.join(output_dir, dst_filename)
                    success, encoded = cv2.imencode('.png', img)
                    if success:
                        with open(dst_path, 'wb') as f:
                            f.write(encoded.tobytes())
                        # 更新配置中的路径为相对路径
                        ark_opts.operator_class_icon = dst_filename
                        logger.info(f"已导出职业图标: {dst_path}")

        # 处理Logo (75x35)
        if ark_opts.logo:
            src_path = ark_opts.logo
            if not os.path.isabs(src_path):
                src_path = os.path.join(self._base_dir, src_path)

            if os.path.exists(src_path):
                img = ImageProcessor.load_image(src_path)
                if img is not None:
                    # 缩放到目标尺寸
                    img = cv2.resize(img, ARK_LOGO_SIZE)
                    # 保存到导出目录
                    dst_filename = "ark_logo.png"
                    dst_path = os.path.join(output_dir, dst_filename)
                    success, encoded = cv2.imencode('.png', img)
                    if success:
                        with open(dst_path, 'wb') as f:
                            f.write(encoded.tobytes())
                        # 更新配置中的路径为相对路径
                        ark_opts.logo = dst_filename
                        logger.info(f"已导出Logo: {dst_path}")

    def _on_export_completed(self, success: bool, message: str):
        """导出完成回调"""
        if hasattr(self, '_export_dialog') and self._export_dialog:
            self._export_dialog.set_completed(success, message)

        if success:
            self.status_bar.showMessage(message)
            logger.info(f"导出成功: {message}")
        else:
            self.status_bar.showMessage("导出失败")
            logger.error(f"导出失败: {message}")

    def _check_save(self) -> bool:
        """检查是否需要保存"""
        if not self._is_modified:
            return True

        result = QMessageBox.question(
            self, "保存更改",
            "当前项目有未保存的更改，是否保存?",
            QMessageBox.StandardButton.Save |
            QMessageBox.StandardButton.Discard |
            QMessageBox.StandardButton.Cancel
        )

        if result == QMessageBox.StandardButton.Save:
            self._on_save_project()
            return not self._is_modified
        elif result == QMessageBox.StandardButton.Discard:
            return True
        else:
            return False

    def closeEvent(self, event):
        """关闭事件"""
        if self._check_save():
            self._save_settings()
            event.accept()
        else:
            event.ignore()
