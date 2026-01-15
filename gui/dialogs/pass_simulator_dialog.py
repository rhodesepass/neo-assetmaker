"""
通行证模拟器对话框 - 完整模拟真机显示效果

实现固件中的完整播放流程：
transition_in → intro_video → transition_loop → PRE_OPINFO → loop_video + opinfo

数据驱动架构:
- 所有常量从 FirmwareConfig 读取
- 支持从 JSON 配置文件加载
- 通过 ConfigManager 获取配置
"""
import logging
import os
from typing import Optional, TYPE_CHECKING

import numpy as np

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QWidget, QComboBox
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QImage, QPixmap

if TYPE_CHECKING:
    from config.epconfig import EPConfig
    from config.firmware_config import FirmwareConfig

# 顶层导入，避免循环内导入
from config.epconfig import OverlayType
from config.config_manager import ConfigManager
from core.transition_renderer import TransitionRenderer, TransitionType, TransitionPhase
from core.overlay_animator import OverlayAnimator

logger = logging.getLogger(__name__)


def microseconds_to_frames(us: int, fps: int) -> int:
    """将微秒转换为帧数"""
    return max(1, us * fps // 1000000)


class PassSimulatorDialog(QDialog):
    """通行证模拟器对话框"""

    # 播放状态（简化版，与固件一致）
    STATE_IDLE = 0              # 空闲
    STATE_TRANSITION_IN = 1     # 入场过渡
    STATE_INTRO = 2             # 入场视频
    STATE_TRANSITION_LOOP = 3   # 循环过渡
    STATE_PRE_OPINFO = 4        # 等待 appear_time
    STATE_LOOP = 5              # 循环播放 + 叠加层

    STATE_NAMES = {
        STATE_IDLE: "空闲",
        STATE_TRANSITION_IN: "入场过渡",
        STATE_INTRO: "入场视频",
        STATE_TRANSITION_LOOP: "循环过渡",
        STATE_PRE_OPINFO: "等待显示",
        STATE_LOOP: "循环播放"
    }

    def __init__(self, parent=None, firmware_config: "FirmwareConfig" = None):
        super().__init__(parent)

        # 加载固件配置
        if firmware_config is None:
            firmware_config = ConfigManager.get_firmware()
        self._firmware_config = firmware_config

        # 从配置获取常量
        self._simulator_width = self._firmware_config.overlay_width
        self._simulator_height = self._firmware_config.overlay_height
        self._animation_fps = self._firmware_config.fps
        self._frame_interval_ms = 1000 // self._animation_fps

        # 默认过渡帧数 (从配置获取)
        self._default_transition_frames = self._firmware_config.transition.default_frames

        # 默认 appear_time (帧数) - 固件默认 100000us = 100ms
        self._default_appear_time_frames = microseconds_to_frames(100000, self._animation_fps)

        self._epconfig: Optional["EPConfig"] = None
        self._base_dir: str = ""

        # 视频状态
        self._loop_cap = None
        self._intro_cap = None
        self._loop_fps: float = 30.0
        self._intro_fps: float = 30.0

        # 视频尺寸缓存（用于判断是否需要resize）
        self._loop_need_resize = True
        self._intro_need_resize = True

        # 播放状态
        self._state = self.STATE_IDLE
        self._is_playing = False
        self._frame_counter = 0

        # 过渡效果状态
        self._transition_frame = 0
        self._transition_total_frames = self._default_transition_frames
        self._transition_type = TransitionType.FADE
        self._video_switched = False  # 标记视频是否已切换
        self._is_first_switch = True  # 首次切换标志（固件prts.c:238-240 强制SWIPE）

        # 过渡图片
        self._transition_image: Optional[np.ndarray] = None

        # PRE_OPINFO 等待计数
        self._pre_opinfo_counter = 0
        self._appear_time_frames = self._default_appear_time_frames

        # 帧缓存（减少内存分配）
        self._current_video_frame: Optional[np.ndarray] = None
        self._intro_last_frame: Optional[np.ndarray] = None

        # 预分配RGB缓冲区
        self._rgb_buffer = np.empty((self._simulator_height, self._simulator_width, 3), dtype=np.uint8)

        # 渲染器（使用相同的固件配置）
        self._transition_renderer = TransitionRenderer(self._firmware_config)
        self._overlay_animator = OverlayAnimator(self._firmware_config)

        # 定时器
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_timer_tick)

        self._setup_ui()

    def _setup_ui(self):
        """设置UI"""
        self.setWindowTitle("通行证模拟预览")
        self.setFixedSize(self._simulator_width + 40, self._simulator_height + 140)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        # 标题
        title_label = QLabel(f"通行证模拟预览 ({self._simulator_width}×{self._simulator_height} @ {self._animation_fps}fps)")
        title_label.setStyleSheet("color: #ccc; font-size: 14px; font-weight: bold;")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        # 显示区域容器
        display_container = QWidget()
        display_container.setFixedSize(self._simulator_width + 4, self._simulator_height + 4)
        display_container.setStyleSheet("background-color: #000; border: 2px solid #444;")
        display_layout = QVBoxLayout(display_container)
        display_layout.setContentsMargins(0, 0, 0, 0)

        # 显示标签
        self._display_label = QLabel()
        self._display_label.setFixedSize(self._simulator_width, self._simulator_height)
        self._display_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._display_label.setStyleSheet("background-color: #000;")
        self._display_label.setText("未加载")
        display_layout.addWidget(self._display_label, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(display_container, alignment=Qt.AlignmentFlag.AlignCenter)

        # 过渡效果选择
        transition_layout = QHBoxLayout()
        transition_layout.addWidget(QLabel("入场过渡:"))
        self._combo_transition_in = QComboBox()
        self._combo_transition_in.addItems(["fade", "move", "swipe", "none"])
        self._combo_transition_in.setFixedWidth(80)
        transition_layout.addWidget(self._combo_transition_in)

        transition_layout.addWidget(QLabel("循环过渡:"))
        self._combo_transition_loop = QComboBox()
        self._combo_transition_loop.addItems(["fade", "move", "swipe", "none"])
        self._combo_transition_loop.setFixedWidth(80)
        transition_layout.addWidget(self._combo_transition_loop)

        transition_layout.addStretch()
        layout.addLayout(transition_layout)

        # 控制按钮
        control_layout = QHBoxLayout()
        control_layout.setSpacing(10)

        self._btn_play = QPushButton("播放")
        self._btn_play.setFixedWidth(80)
        self._btn_play.clicked.connect(self._on_play_clicked)
        control_layout.addWidget(self._btn_play)

        self._btn_reset = QPushButton("重置")
        self._btn_reset.setFixedWidth(80)
        self._btn_reset.clicked.connect(self._on_reset_clicked)
        control_layout.addWidget(self._btn_reset)

        self._btn_close = QPushButton("关闭")
        self._btn_close.setFixedWidth(80)
        self._btn_close.clicked.connect(self.close)
        control_layout.addWidget(self._btn_close)

        layout.addLayout(control_layout)

        # 状态标签
        self._status_label = QLabel("状态: 就绪")
        self._status_label.setStyleSheet("color: #888; font-size: 11px;")
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._status_label)

        # 样式
        self.setStyleSheet("""
            QDialog { background-color: #1a1a1a; }
            QPushButton {
                background-color: #444; color: #ddd;
                border: 1px solid #555; border-radius: 3px; padding: 8px 16px;
            }
            QPushButton:hover { background-color: #555; }
            QPushButton:pressed { background-color: #333; }
            QComboBox {
                background-color: #444; color: #ddd;
                border: 1px solid #555; border-radius: 3px; padding: 4px;
            }
            QLabel { color: #ccc; }
        """)

    def set_config(self, config: "EPConfig", base_dir: str):
        """设置配置"""
        self._epconfig = config
        self._base_dir = base_dir
        self._load_videos()
        self._apply_config_transitions()

    def _apply_config_transitions(self):
        """应用配置中的过渡效果设置"""
        if not self._epconfig:
            return

        # 入场过渡
        trans_in_type = self._epconfig.transition_in.type.value
        index = self._combo_transition_in.findText(trans_in_type)
        if index >= 0:
            self._combo_transition_in.setCurrentIndex(index)

        # 循环过渡
        trans_loop_type = self._epconfig.transition_loop.type.value
        index = self._combo_transition_loop.findText(trans_loop_type)
        if index >= 0:
            self._combo_transition_loop.setCurrentIndex(index)

        # 计算appear_time帧数（从叠加层配置读取）
        if self._epconfig.overlay.arknights_options:
            appear_us = self._epconfig.overlay.arknights_options.appear_time
            self._appear_time_frames = microseconds_to_frames(appear_us, self._animation_fps)
        else:
            self._appear_time_frames = self._default_appear_time_frames

    def _load_videos(self):
        """加载视频文件"""
        if not self._epconfig or not HAS_CV2:
            return

        # 加载循环视频
        if self._epconfig.loop.file:
            loop_path = self._epconfig.loop.file
            if not os.path.isabs(loop_path):
                loop_path = os.path.join(self._base_dir, loop_path)

            if os.path.exists(loop_path):
                self._loop_cap = cv2.VideoCapture(loop_path)
                if self._loop_cap.isOpened():
                    w = int(self._loop_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    h = int(self._loop_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    self._loop_fps = self._loop_cap.get(cv2.CAP_PROP_FPS) or 30.0
                    self._loop_need_resize = (w != self._simulator_width or h != self._simulator_height)
                    logger.info(f"模拟器加载循环视频: {loop_path} ({w}x{h})")
                else:
                    self._loop_cap = None

        # 加载入场视频
        if self._epconfig.intro.enabled and self._epconfig.intro.file:
            intro_path = self._epconfig.intro.file
            if not os.path.isabs(intro_path):
                intro_path = os.path.join(self._base_dir, intro_path)

            if os.path.exists(intro_path):
                self._intro_cap = cv2.VideoCapture(intro_path)
                if self._intro_cap.isOpened():
                    w = int(self._intro_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    h = int(self._intro_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    self._intro_fps = self._intro_cap.get(cv2.CAP_PROP_FPS) or 30.0
                    self._intro_need_resize = (w != self._simulator_width or h != self._simulator_height)
                    logger.info(f"模拟器加载入场视频: {intro_path} ({w}x{h})")
                else:
                    self._intro_cap = None

        # 加载过渡图片
        self._load_transition_image()
        self._show_first_frame()

    def _load_transition_image(self):
        """加载过渡图片"""
        if not self._epconfig:
            return

        if self._epconfig.transition_in.options and self._epconfig.transition_in.options.image:
            image_path = self._epconfig.transition_in.options.image
            if not os.path.isabs(image_path):
                image_path = os.path.join(self._base_dir, image_path)
            if os.path.exists(image_path):
                self._transition_image = cv2.imread(image_path, cv2.IMREAD_UNCHANGED)
                if self._transition_image is not None:
                    self._transition_image = cv2.resize(
                        self._transition_image, (self._simulator_width, self._simulator_height)
                    )
                    logger.info(f"加载过渡图片: {image_path}")

    def _show_first_frame(self):
        """显示第一帧"""
        if self._loop_cap and self._loop_cap.isOpened():
            self._loop_cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = self._loop_cap.read()
            if ret:
                if self._loop_need_resize:
                    frame = cv2.resize(frame, (self._simulator_width, self._simulator_height))
                self._current_video_frame = frame
                self._display_frame(frame)
                self._status_label.setText("状态: 就绪 (点击播放)")

    def _on_play_clicked(self):
        """播放按钮点击"""
        if self._is_playing:
            self._pause()
        else:
            self._play()

    def _play(self):
        """开始播放"""
        if not self._loop_cap:
            self._status_label.setText("状态: 未加载视频")
            return

        self._is_playing = True
        self._btn_play.setText("暂停")
        self._frame_counter = 0

        # 重置渲染器状态
        self._overlay_animator.reset()

        # 决定起始状态
        if self._intro_cap and self._intro_cap.isOpened():
            self._state = self.STATE_TRANSITION_IN
            self._transition_frame = 0
            self._video_switched = False
            # 固件行为 (prts.c:238-240): 首次过渡强制使用SWIPE
            # if(is_first_transition){
            #     overlay_transition_swipe(prts->overlay, callback, transition);
            # }
            if self._is_first_switch:
                self._transition_type = TransitionType.SWIPE
                self._is_first_switch = False
            else:
                self._transition_type = self._get_transition_type(self._combo_transition_in.currentText())
            self._transition_total_frames = self._get_transition_frames(is_intro=True)
            # 预读入场视频第一帧
            self._intro_cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        else:
            self._state = self.STATE_TRANSITION_LOOP
            self._transition_frame = 0
            self._video_switched = False
            # 固件行为: 首次过渡强制使用SWIPE
            if self._is_first_switch:
                self._transition_type = TransitionType.SWIPE
                self._is_first_switch = False
            else:
                self._transition_type = self._get_transition_type(self._combo_transition_loop.currentText())
            self._transition_total_frames = self._get_transition_frames(is_intro=False)
            self._loop_cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

        self._update_status()
        self._timer.start(self._frame_interval_ms)

    def _pause(self):
        """暂停播放"""
        self._is_playing = False
        self._timer.stop()
        self._btn_play.setText("播放")
        self._status_label.setText("状态: 已暂停")

    def _on_reset_clicked(self):
        """重置按钮点击"""
        self._pause()
        self._state = self.STATE_IDLE
        self._frame_counter = 0
        self._transition_frame = 0
        self._pre_opinfo_counter = 0
        self._video_switched = False
        self._is_first_switch = True  # 重置首次切换标志

        if self._loop_cap:
            self._loop_cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        if self._intro_cap:
            self._intro_cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

        self._overlay_animator.reset()
        self._show_first_frame()
        self._status_label.setText("状态: 已重置")

    def _get_transition_type(self, name: str) -> TransitionType:
        """获取过渡类型枚举"""
        mapping = {
            "fade": TransitionType.FADE,
            "move": TransitionType.MOVE,
            "swipe": TransitionType.SWIPE,
            "none": TransitionType.NONE
        }
        return mapping.get(name, TransitionType.FADE)

    def _get_transition_frames(self, is_intro: bool = True) -> int:
        """
        获取过渡效果总帧数

        固件行为 (transitions.c):
        - 总时长 = 3 × duration
        - 每个阶段 = duration

        Args:
            is_intro: True=入场过渡, False=循环过渡

        Returns:
            总帧数
        """
        if not self._epconfig:
            return self._default_transition_frames

        if is_intro:
            options = self._epconfig.transition_in.options
        else:
            options = self._epconfig.transition_loop.options

        if options and options.duration > 0:
            # duration是每阶段时长，总时长=3×duration
            stage_frames = microseconds_to_frames(options.duration, self._animation_fps)
            return stage_frames * 3

        return self._default_transition_frames

    def _update_status(self):
        """更新状态显示"""
        state_name = self.STATE_NAMES.get(self._state, "未知")
        self._status_label.setText(f"状态: {state_name} | 帧: {self._frame_counter}")

    def _on_timer_tick(self):
        """定时器回调"""
        if not self._is_playing:
            return

        self._frame_counter += 1

        # 根据状态处理
        if self._state == self.STATE_TRANSITION_IN:
            self._process_transition_in()
        elif self._state == self.STATE_INTRO:
            self._process_intro()
        elif self._state == self.STATE_TRANSITION_LOOP:
            self._process_transition_loop()
        elif self._state == self.STATE_PRE_OPINFO:
            self._process_pre_opinfo()
        elif self._state == self.STATE_LOOP:
            self._process_loop()

        # 每10帧更新一次UI（减少开销）
        if self._frame_counter % 10 == 0:
            self._update_status()

    def _read_video_frame(self, cap, need_resize: bool, loop: bool = True) -> Optional[np.ndarray]:
        """读取视频帧

        Args:
            cap: 视频捕获对象
            need_resize: 是否需要缩放
            loop: 是否循环播放（入场视频=False，循环视频=True）
        """
        if not cap or not cap.isOpened():
            return None

        ret, frame = cap.read()
        if not ret:
            if loop:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, frame = cap.read()
                if not ret:
                    return None
            else:
                return None  # 不循环，视频结束返回None

        if need_resize:
            frame = cv2.resize(frame, (self._simulator_width, self._simulator_height))
        return frame

    def _process_transition_in(self):
        """处理入场过渡"""
        self._transition_frame += 1
        progress = self._transition_frame / self._transition_total_frames

        # 获取当前阶段
        phase = self._transition_renderer.get_phase(progress)

        # 在HOLD阶段切换视频
        if phase == TransitionPhase.PHASE_HOLD and not self._video_switched:
            self._video_switched = True
            # 准备入场视频第一帧
            if self._intro_cap:
                self._intro_cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

        # 获取背景帧和目标帧
        if self._current_video_frame is None:
            bg_frame = np.zeros((self._simulator_height, self._simulator_width, 3), dtype=np.uint8)
        else:
            bg_frame = self._current_video_frame

        # 目标帧（入场视频第一帧）
        if self._intro_cap:
            self._intro_cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, target = self._intro_cap.read()
            if ret:
                if self._intro_need_resize:
                    target = cv2.resize(target, (self._simulator_width, self._simulator_height))
            else:
                target = bg_frame
        else:
            target = bg_frame

        # 渲染过渡
        rendered, _ = self._transition_renderer.render(
            self._transition_type, bg_frame, target, progress, self._transition_image
        )
        self._display_frame(rendered)

        # 过渡完成
        if progress >= 1.0:
            self._state = self.STATE_INTRO
            self._intro_cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    def _process_intro(self):
        """处理入场视频"""
        if not self._intro_cap:
            self._start_transition_loop()
            return

        # 入场视频不循环，播放完毕后进入下一状态
        frame = self._read_video_frame(self._intro_cap, self._intro_need_resize, loop=False)
        if frame is None:
            # 入场视频结束
            self._start_transition_loop()
            return

        self._intro_last_frame = frame
        self._display_frame(frame)

    def _start_transition_loop(self):
        """开始循环过渡"""
        self._state = self.STATE_TRANSITION_LOOP
        self._transition_frame = 0
        self._video_switched = False
        self._transition_type = self._get_transition_type(self._combo_transition_loop.currentText())
        self._transition_total_frames = self._get_transition_frames(is_intro=False)
        self._current_video_frame = self._intro_last_frame

    def _process_transition_loop(self):
        """处理循环过渡"""
        self._transition_frame += 1
        progress = self._transition_frame / self._transition_total_frames

        # 获取当前阶段
        phase = self._transition_renderer.get_phase(progress)

        # 在HOLD阶段切换视频
        if phase == TransitionPhase.PHASE_HOLD and not self._video_switched:
            self._video_switched = True
            if self._loop_cap:
                self._loop_cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

        # 背景帧
        bg_frame = self._current_video_frame if self._current_video_frame is not None else \
            np.zeros((self._simulator_height, self._simulator_width, 3), dtype=np.uint8)

        # 目标帧（循环视频第一帧）
        if self._loop_cap:
            self._loop_cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, target = self._loop_cap.read()
            if ret:
                if self._loop_need_resize:
                    target = cv2.resize(target, (self._simulator_width, self._simulator_height))
            else:
                target = bg_frame
        else:
            target = bg_frame

        # 渲染过渡
        rendered, _ = self._transition_renderer.render(
            self._transition_type, bg_frame, target, progress, self._transition_image
        )
        self._display_frame(rendered)

        # 过渡完成
        if progress >= 1.0:
            self._state = self.STATE_PRE_OPINFO
            self._pre_opinfo_counter = 0
            self._loop_cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    def _process_pre_opinfo(self):
        """处理PRE_OPINFO状态"""
        self._pre_opinfo_counter += 1

        # 播放循环视频
        frame = self._read_video_frame(self._loop_cap, self._loop_need_resize)
        if frame is not None:
            self._display_frame(frame)

        # 等待appear_time后进入LOOP
        if self._pre_opinfo_counter >= self._appear_time_frames:
            self._state = self.STATE_LOOP
            self._overlay_animator.reset()
            self._overlay_animator.start_entry_animation()

    def _process_loop(self):
        """处理循环视频 + 叠加层"""
        # 更新动画
        self._overlay_animator.update()

        # 读取视频帧
        frame = self._read_video_frame(self._loop_cap, self._loop_need_resize)
        if frame is None:
            return

        # 渲染叠加层
        if self._epconfig and self._epconfig.overlay.type == OverlayType.ARKNIGHTS:
            frame = self._overlay_animator.render(
                frame,
                self._epconfig.overlay.arknights_options,
                apply_entry_offset=not self._overlay_animator.is_entry_complete
            )

        self._display_frame(frame)

    def _display_frame(self, frame: np.ndarray):
        """显示帧（优化版）"""
        if frame is None:
            return

        # BGR -> RGB（直接写入预分配缓冲区）
        cv2.cvtColor(frame, cv2.COLOR_BGR2RGB, dst=self._rgb_buffer)

        # 创建QImage（使用预分配缓冲区）
        q_image = QImage(
            self._rgb_buffer.data,
            self._simulator_width, self._simulator_height,
            self._simulator_width * 3,
            QImage.Format.Format_RGB888
        )
        self._display_label.setPixmap(QPixmap.fromImage(q_image))

    def closeEvent(self, event):
        """关闭事件"""
        self._pause()
        if self._loop_cap:
            self._loop_cap.release()
        if self._intro_cap:
            self._intro_cap.release()
        super().closeEvent(event)

    @property
    def firmware_config(self) -> "FirmwareConfig":
        """获取固件配置"""
        return self._firmware_config
