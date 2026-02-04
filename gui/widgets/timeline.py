"""
时间轴组件 - 播放控制和时间标记
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QRect, QPoint
from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QMouseEvent, QPaintEvent


class TimelineSlider(QWidget):
    """自定义时间轴滑块"""

    seek_requested = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)

        self._total_frames = 100
        self._current_frame = 0
        self._in_point = 0
        self._out_point = 100
        self._dragging = False

        self._margin = 10
        self._track_height = 30

        # 颜色
        self._bg_color = QColor(50, 50, 50)
        self._track_color = QColor(70, 70, 70)
        self._selection_color = QColor(66, 133, 244, 100)
        self._in_color = QColor(76, 175, 80)  # 绿色
        self._out_color = QColor(244, 67, 54)  # 红色
        self._current_color = QColor(255, 255, 255)  # 白色

        self.setMinimumHeight(50)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)

    @property
    def _safe_frame_divisor(self) -> int:
        """获取安全的帧数除数（避免除以零）"""
        return max(1, self._total_frames - 1)

    def set_total_frames(self, count: int):
        """设置总帧数"""
        self._total_frames = max(1, count)
        # 确保所有帧索引在有效范围内
        max_frame = max(0, self._total_frames - 1)
        self._in_point = min(self._in_point, max_frame)
        self._out_point = min(self._out_point, max_frame)
        self._current_frame = min(self._current_frame, max_frame)
        self.update()

    def set_current_frame(self, index: int):
        """设置当前帧"""
        self._current_frame = max(0, min(index, self._total_frames - 1))
        self.update()

    def set_in_point(self, frame: int):
        """设置入点"""
        self._in_point = max(0, min(frame, self._total_frames - 1))
        if self._in_point > self._out_point:
            self._out_point = self._in_point
        self.update()

    def set_out_point(self, frame: int):
        """设置出点"""
        self._out_point = max(0, min(frame, self._total_frames - 1))
        if self._out_point < self._in_point:
            self._in_point = self._out_point
        self.update()

    def get_in_point(self) -> int:
        """获取入点"""
        return self._in_point

    def get_out_point(self) -> int:
        """获取出点"""
        return self._out_point

    def _frame_to_x(self, frame: int) -> int:
        """帧号转X坐标"""
        track_width = self.width() - 2 * self._margin
        if self._total_frames <= 1:
            return self._margin
        return int(self._margin + (frame / self._safe_frame_divisor) * track_width)

    def _x_to_frame(self, x: int) -> int:
        """X坐标转帧号"""
        track_width = self.width() - 2 * self._margin
        if track_width <= 0:
            return 0
        ratio = max(0, min(1, (x - self._margin) / track_width))
        return int(ratio * self._safe_frame_divisor)

    def paintEvent(self, event: QPaintEvent):
        """绘制"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w, h = self.width(), self.height()
        track_y = (h - self._track_height) // 2
        track_width = w - 2 * self._margin

        # 背景
        painter.fillRect(0, 0, w, h, self._bg_color)

        # 轨道
        painter.fillRect(
            QRect(self._margin, track_y, track_width, self._track_height),
            self._track_color
        )

        # 选中范围
        if self._total_frames > 1:
            in_x = self._frame_to_x(self._in_point)
            out_x = self._frame_to_x(self._out_point)
            painter.fillRect(
                QRect(in_x, track_y, out_x - in_x, self._track_height),
                self._selection_color
            )

        # 入点标记
        in_x = self._frame_to_x(self._in_point)
        painter.setBrush(QBrush(self._in_color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon([
            QPoint(in_x - 6, track_y - 6),
            QPoint(in_x + 6, track_y - 6),
            QPoint(in_x, track_y)
        ])

        # 出点标记
        out_x = self._frame_to_x(self._out_point)
        painter.setBrush(QBrush(self._out_color))
        bottom_y = track_y + self._track_height
        painter.drawPolygon([
            QPoint(out_x - 6, bottom_y + 6),
            QPoint(out_x + 6, bottom_y + 6),
            QPoint(out_x, bottom_y)
        ])

        # 当前位置
        cur_x = self._frame_to_x(self._current_frame)
        painter.setPen(QPen(self._current_color, 2))
        painter.drawLine(cur_x, track_y - 5, cur_x, track_y + self._track_height + 5)
        painter.setBrush(QBrush(self._current_color))
        painter.drawEllipse(QPoint(cur_x, track_y + self._track_height // 2), 5, 5)

    def mousePressEvent(self, event: QMouseEvent):
        """鼠标按下"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self.seek_requested.emit(self._x_to_frame(int(event.position().x())))

    def mouseMoveEvent(self, event: QMouseEvent):
        """鼠标移动"""
        if self._dragging:
            self.seek_requested.emit(self._x_to_frame(int(event.position().x())))

    def mouseReleaseEvent(self, event: QMouseEvent):
        """鼠标释放"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False


class TimelineWidget(QWidget):
    """时间轴组件"""

    # 信号
    play_pause_clicked = pyqtSignal()
    seek_requested = pyqtSignal(int)
    prev_frame_clicked = pyqtSignal()
    next_frame_clicked = pyqtSignal()
    goto_start_clicked = pyqtSignal()
    goto_end_clicked = pyqtSignal()
    set_in_point_clicked = pyqtSignal()
    set_out_point_clicked = pyqtSignal()
    simulator_requested = pyqtSignal()  # 模拟器启动请求信号
    rotation_clicked = pyqtSignal()  # 旋转按钮点击信号

    def __init__(self, parent=None):
        super().__init__(parent)

        self._total_frames = 100
        self._current_frame = 0
        self._fps = 30.0
        self._is_playing = False

        self._init_ui()
        self._connect_signals()

    def _init_ui(self):
        """初始化UI"""
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        # 控制按钮
        control_layout = QHBoxLayout()
        control_layout.setSpacing(3)

        self.btn_goto_start = QPushButton("|<")
        self.btn_goto_start.setFixedWidth(35)
        self.btn_goto_start.setToolTip("跳到开始")
        control_layout.addWidget(self.btn_goto_start)

        self.btn_prev_frame = QPushButton("<")
        self.btn_prev_frame.setFixedWidth(35)
        self.btn_prev_frame.setToolTip("上一帧 (\u2190)")
        control_layout.addWidget(self.btn_prev_frame)

        self.btn_play_pause = QPushButton("播放")
        self.btn_play_pause.setFixedWidth(50)
        self.btn_play_pause.setToolTip("播放/暂停 (Space)")
        control_layout.addWidget(self.btn_play_pause)

        self.btn_next_frame = QPushButton(">")
        self.btn_next_frame.setFixedWidth(35)
        self.btn_next_frame.setToolTip("下一帧 (\u2192)")
        control_layout.addWidget(self.btn_next_frame)

        self.btn_goto_end = QPushButton(">|")
        self.btn_goto_end.setFixedWidth(35)
        self.btn_goto_end.setToolTip("跳到结束")
        control_layout.addWidget(self.btn_goto_end)

        control_layout.addWidget(QLabel("|"))

        self.btn_set_in = QPushButton("[ 入点")
        self.btn_set_in.setToolTip("设置入点")
        control_layout.addWidget(self.btn_set_in)

        self.btn_set_out = QPushButton("] 出点")
        self.btn_set_out.setToolTip("设置出点")
        control_layout.addWidget(self.btn_set_out)

        control_layout.addWidget(QLabel("|"))

        self.label_frame = QLabel("0 / 100")
        self.label_frame.setMinimumWidth(80)
        control_layout.addWidget(self.label_frame)

        self.label_fps = QLabel("30.0 FPS")
        control_layout.addWidget(self.label_fps)

        control_layout.addWidget(QLabel("|"))

        # 模拟预览按钮
        self.btn_preview = QPushButton("模拟预览")
        self.btn_preview.setToolTip("启动模拟器预览实际显示效果")
        control_layout.addWidget(self.btn_preview)

        # 旋转按钮
        self.btn_rotate = QPushButton("旋转 0°")
        self.btn_rotate.setToolTip("旋转视频（点击顺时针旋转90度）")
        self.btn_rotate.setMinimumWidth(85)
        control_layout.addWidget(self.btn_rotate)

        control_layout.addStretch()

        # 时间轴滑块
        self.timeline_slider = TimelineSlider()
        self.timeline_slider.setToolTip("拖动或点击跳转")

        main_layout.addLayout(control_layout)
        main_layout.addWidget(self.timeline_slider)

        self.setMinimumHeight(100)
        self.setMaximumHeight(150)
        self.setStyleSheet("""
            TimelineWidget {
                background-color: #2d2d2d;
                border-top: 1px solid #444;
            }
            QPushButton {
                background-color: #444;
                color: #ddd;
                border: 1px solid #555;
                border-radius: 3px;
                padding: 4px 8px;
            }
            QPushButton:hover {
                background-color: #555;
            }
            QPushButton:checked {
                background-color: #4285f4;
                color: #fff;
                border: 1px solid #3367d6;
            }
            QLabel {
                color: #ccc;
            }
        """)

    def _connect_signals(self):
        """连接信号"""
        self.btn_goto_start.clicked.connect(self.goto_start_clicked.emit)
        self.btn_prev_frame.clicked.connect(self.prev_frame_clicked.emit)
        self.btn_play_pause.clicked.connect(self.play_pause_clicked.emit)
        self.btn_next_frame.clicked.connect(self.next_frame_clicked.emit)
        self.btn_goto_end.clicked.connect(self.goto_end_clicked.emit)
        self.btn_set_in.clicked.connect(self.set_in_point_clicked.emit)
        self.btn_set_out.clicked.connect(self.set_out_point_clicked.emit)
        self.timeline_slider.seek_requested.connect(self.seek_requested.emit)
        self.btn_preview.clicked.connect(self.simulator_requested.emit)
        self.btn_rotate.clicked.connect(self.rotation_clicked.emit)

    def set_total_frames(self, count: int):
        """设置总帧数"""
        self._total_frames = max(1, count)
        self.timeline_slider.set_total_frames(count)
        self._update_label()

    def set_current_frame(self, index: int):
        """设置当前帧"""
        self._current_frame = max(0, min(index, self._total_frames - 1))
        self.timeline_slider.set_current_frame(index)
        self._update_label()

    def set_in_point(self, frame: int):
        """设置入点"""
        self.timeline_slider.set_in_point(frame)

    def set_out_point(self, frame: int):
        """设置出点"""
        self.timeline_slider.set_out_point(frame)

    def set_in_point_to_current(self):
        """将入点设置为当前帧"""
        self.set_in_point(self._current_frame)

    def set_out_point_to_current(self):
        """将出点设置为当前帧"""
        self.set_out_point(self._current_frame)

    def get_in_point(self) -> int:
        """获取入点"""
        return self.timeline_slider.get_in_point()

    def get_out_point(self) -> int:
        """获取出点"""
        return self.timeline_slider.get_out_point()

    def set_fps(self, fps: float):
        """设置FPS"""
        self._fps = fps
        self.label_fps.setText(f"{fps:.1f} FPS")

    def set_playing(self, is_playing: bool):
        """设置播放状态"""
        self._is_playing = is_playing
        self.btn_play_pause.setText("暂停" if is_playing else "播放")

    def _update_label(self):
        """更新帧标签"""
        self.label_frame.setText(f"{self._current_frame} / {self._total_frames}")

    def set_rotation(self, degrees: int):
        """更新旋转按钮显示"""
        self.btn_rotate.setText(f"旋转 {degrees}°")
