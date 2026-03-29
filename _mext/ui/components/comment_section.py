"""Comment section component for material detail pages.

Provides a scrollable list of comments with input area for
authenticated users.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from qfluentwidgets import (
    AvatarWidget,
    BodyLabel,
    CaptionLabel,
    FluentIcon,
    HorizontalSeparator,
    MessageBox,
    PrimaryPushButton,
    PushButton,
    StrongBodyLabel,
    SubtitleLabel,
    TextEdit,
    ToolButton,
)
from PyQt6.QtCore import Qt, pyqtSignal as Signal, pyqtSlot as Slot
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from _mext.core.service_manager import ServiceManager
from _mext.models.comment import Comment
from _mext.services.api_worker import CommentDeleteWorker, CommentPostWorker, CommentsLoadWorker
from _mext.ui.components.thumbnail_loader import ThumbnailLoader
from _mext.ui.styles import (
    AVATAR_MD,
    COMMENT_BUBBLE_PADDING,
    COMMENT_INPUT_MAX_HEIGHT,
    COMMENT_INPUT_MIN_HEIGHT,
    SPACING_MD,
    SPACING_SM,
    SPACING_XS,
)

logger = logging.getLogger(__name__)


class _CommentBubble(QWidget):
    """Single comment display widget."""

    delete_requested = Signal(str)  # comment_id

    def __init__(self, comment: Comment, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._comment = comment
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, COMMENT_BUBBLE_PADDING, 0, COMMENT_BUBBLE_PADDING)
        layout.setSpacing(SPACING_SM)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Avatar
        self._avatar = AvatarWidget(self)
        self._avatar.setRadius(AVATAR_MD // 2)
        layout.addWidget(self._avatar, alignment=Qt.AlignmentFlag.AlignTop)

        # Content column
        content_col = QVBoxLayout()
        content_col.setSpacing(SPACING_XS)

        # Header row: username + time + [delete btn]
        header_row = QHBoxLayout()
        header_row.setSpacing(SPACING_SM)

        name_label = StrongBodyLabel(self._comment.username, self)
        header_row.addWidget(name_label)

        time_str = self._format_time(self._comment.created_at)
        time_label = CaptionLabel(time_str, self)
        header_row.addWidget(time_label)

        header_row.addStretch()

        if self._comment.is_own:
            delete_btn = ToolButton(FluentIcon.DELETE, self)
            delete_btn.setFixedSize(20, 20)
            delete_btn.clicked.connect(
                lambda: self.delete_requested.emit(self._comment.id)
            )
            header_row.addWidget(delete_btn)

        content_col.addLayout(header_row)

        # Comment text
        body = BodyLabel(self._comment.content, self)
        body.setWordWrap(True)
        content_col.addWidget(body)

        layout.addLayout(content_col, stretch=1)

    @staticmethod
    def _format_time(dt: datetime) -> str:
        now = datetime.now(tz=dt.tzinfo)
        diff = now - dt
        if diff.days > 365:
            return dt.strftime("%Y-%m-%d")
        elif diff.days > 30:
            return f"{diff.days // 30} 月前"
        elif diff.days > 0:
            return f"{diff.days} 天前"
        elif diff.seconds > 3600:
            return f"{diff.seconds // 3600} 小时前"
        elif diff.seconds > 60:
            return f"{diff.seconds // 60} 分钟前"
        else:
            return "刚刚"

    @property
    def comment(self) -> Comment:
        return self._comment

    def set_avatar(self, pixmap: QPixmap) -> None:
        if not pixmap.isNull():
            self._avatar.setImage(pixmap)


class CommentSection(QWidget):
    """Comment section with input area and scrollable comment list.

    Signals
    -------
    comment_count_changed(str, int)
        (material_id, new_count)
    """

    comment_count_changed = Signal(str, int)

    def __init__(
        self,
        service_manager: ServiceManager,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._services = service_manager
        self._material_id: Optional[str] = None
        self._comments: list[Comment] = []
        self._bubbles: list[_CommentBubble] = []
        self._total_comments = 0
        self._current_page = 1
        self._per_page = 20

        self._thumb_loader = ThumbnailLoader(max_concurrent=3, parent=self)
        self._thumb_loader.thumbnail_ready.connect(self._on_avatar_ready)

        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, SPACING_MD, 0, 0)
        layout.setSpacing(SPACING_SM)

        # Header
        header_row = QHBoxLayout()
        self._title = SubtitleLabel("评论", self)
        header_row.addWidget(self._title)
        self._count_label = CaptionLabel("", self)
        header_row.addWidget(self._count_label)
        header_row.addStretch()
        layout.addLayout(header_row)

        # Input area
        self._input_area = QWidget(self)
        input_layout = QHBoxLayout(self._input_area)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(SPACING_SM)
        input_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._input_avatar = AvatarWidget(self._input_area)
        self._input_avatar.setRadius(AVATAR_MD // 2)
        input_layout.addWidget(self._input_avatar, alignment=Qt.AlignmentFlag.AlignTop)

        self._text_edit = TextEdit(self._input_area)
        self._text_edit.setPlaceholderText("写下你的评论...")
        self._text_edit.setMinimumHeight(COMMENT_INPUT_MIN_HEIGHT)
        self._text_edit.setMaximumHeight(COMMENT_INPUT_MAX_HEIGHT)
        input_layout.addWidget(self._text_edit, stretch=1)

        self._send_btn = PrimaryPushButton(self._input_area)
        self._send_btn.setIcon(FluentIcon.SEND_FILL)
        self._send_btn.setText("发送")
        self._send_btn.setFixedHeight(34)
        self._send_btn.clicked.connect(self._on_send_clicked)
        input_layout.addWidget(self._send_btn, alignment=Qt.AlignmentFlag.AlignBottom)

        layout.addWidget(self._input_area)
        layout.addWidget(HorizontalSeparator(self))

        # Comments list container
        self._comments_scroll = QScrollArea(self)
        self._comments_scroll.setWidgetResizable(True)
        self._comments_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._comments_scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        self._comments_container = QWidget()
        self._comments_layout = QVBoxLayout(self._comments_container)
        self._comments_layout.setContentsMargins(0, 0, 0, 0)
        self._comments_layout.setSpacing(0)
        self._comments_layout.addStretch()

        self._comments_scroll.setWidget(self._comments_container)
        layout.addWidget(self._comments_scroll, stretch=1)

        # Load more button
        self._load_more_btn = PushButton("加载更多", self)
        self._load_more_btn.setVisible(False)
        self._load_more_btn.clicked.connect(self._load_more)
        layout.addWidget(self._load_more_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        # Empty state
        self._empty_label = CaptionLabel("暂无评论", self)
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setVisible(True)
        layout.addWidget(self._empty_label)

    # ── Public API ────────────────────────────────────────────

    def load_comments(self, material_id: str) -> None:
        """Load comments for the given material."""
        self._material_id = material_id
        self._current_page = 1
        self._clear_bubbles()
        self._comments.clear()
        self._fetch_comments()

    def clear(self) -> None:
        """Reset to empty state."""
        self._material_id = None
        self._clear_bubbles()
        self._comments.clear()
        self._total_comments = 0
        self._count_label.setText("")
        self._empty_label.setVisible(True)
        self._load_more_btn.setVisible(False)

    # ── Private ───────────────────────────────────────────────

    def _clear_bubbles(self) -> None:
        for bubble in self._bubbles:
            bubble.deleteLater()
        self._bubbles.clear()
        # Remove all items except the trailing stretch
        while self._comments_layout.count() > 1:
            item = self._comments_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _fetch_comments(self) -> None:
        if not self._material_id:
            return
        self._load_worker = CommentsLoadWorker(
            self._services.api_client,
            self._material_id,
            page=self._current_page,
            per_page=self._per_page,
            parent=self,
        )
        self._load_worker.completed.connect(self._on_comments_loaded)
        self._load_worker.error.connect(self._on_comments_error)
        self._load_worker.start()

    def _load_more(self) -> None:
        self._current_page += 1
        self._fetch_comments()

    @Slot(list, int)
    def _on_comments_loaded(self, items: list, total: int) -> None:
        self._total_comments = total
        self._count_label.setText(f"({total})")

        for item_data in items:
            comment = Comment.from_dict(item_data)
            self._comments.append(comment)
            self._add_bubble(comment)

        has_more = len(self._comments) < total
        self._load_more_btn.setVisible(has_more)
        self._empty_label.setVisible(len(self._comments) == 0)

    @Slot(str)
    def _on_comments_error(self, detail: str) -> None:
        logger.warning("Failed to load comments: %s", detail)
        self._empty_label.setText("评论加载失败")
        self._empty_label.setVisible(True)

    def _add_bubble(self, comment: Comment) -> None:
        bubble = _CommentBubble(comment, parent=self._comments_container)
        bubble.delete_requested.connect(self._on_delete_requested)
        # Insert before the trailing stretch
        idx = self._comments_layout.count() - 1
        self._comments_layout.insertWidget(idx, bubble)
        self._bubbles.append(bubble)

        # Load avatar
        if comment.user_avatar_url:
            cache_key = f"comment_avatar_{comment.user_id}"
            cached = self._thumb_loader.load(comment.user_avatar_url, cache_key)
            if cached:
                bubble.set_avatar(cached)

    @Slot(str, QPixmap)
    def _on_avatar_ready(self, cache_key: str, pixmap: QPixmap) -> None:
        if not cache_key.startswith("comment_avatar_"):
            return
        user_id = cache_key[len("comment_avatar_"):]
        for bubble in self._bubbles:
            if bubble.comment.user_id == user_id:
                bubble.set_avatar(pixmap)

    # ── Send comment ──────────────────────────────────────────

    def _on_send_clicked(self) -> None:
        if not self._material_id:
            return

        content = self._text_edit.toPlainText().strip()
        if not content:
            return

        if not self._services.auth_service.is_authenticated:
            # Try to request auth via parent chain
            forum_widget = self.parent()
            while forum_widget and not hasattr(forum_widget, "require_auth"):
                forum_widget = forum_widget.parent()
            if forum_widget:
                forum_widget.require_auth(on_success=self._on_send_clicked)
            return

        self._send_btn.setEnabled(False)
        self._post_worker = CommentPostWorker(
            self._services.api_client,
            self._material_id,
            content,
            parent=self,
        )
        self._post_worker.completed.connect(self._on_comment_posted)
        self._post_worker.error.connect(self._on_post_error)
        self._post_worker.start()

    @Slot(dict)
    def _on_comment_posted(self, data: dict) -> None:
        self._send_btn.setEnabled(True)
        self._text_edit.clear()

        comment = Comment.from_dict(data)
        self._comments.insert(0, comment)
        self._total_comments += 1
        self._count_label.setText(f"({self._total_comments})")
        self._empty_label.setVisible(False)

        # Insert at top
        bubble = _CommentBubble(comment, parent=self._comments_container)
        bubble.delete_requested.connect(self._on_delete_requested)
        self._comments_layout.insertWidget(0, bubble)
        self._bubbles.insert(0, bubble)

        if comment.user_avatar_url:
            cache_key = f"comment_avatar_{comment.user_id}"
            cached = self._thumb_loader.load(comment.user_avatar_url, cache_key)
            if cached:
                bubble.set_avatar(cached)

        if self._material_id:
            self.comment_count_changed.emit(self._material_id, self._total_comments)

    @Slot(str)
    def _on_post_error(self, detail: str) -> None:
        self._send_btn.setEnabled(True)
        logger.warning("Failed to post comment: %s", detail)

    # ── Delete comment ────────────────────────────────────────

    @Slot(str)
    def _on_delete_requested(self, comment_id: str) -> None:
        dialog = MessageBox("确认删除", "确定要删除这条评论吗？", self)
        if dialog.exec():
            self._delete_worker = CommentDeleteWorker(
                self._services.api_client, comment_id, parent=self
            )
            self._delete_worker.completed.connect(self._on_comment_deleted)
            self._delete_worker.error.connect(self._on_delete_error)
            self._delete_worker.start()

    @Slot(str)
    def _on_comment_deleted(self, comment_id: str) -> None:
        self._comments = [c for c in self._comments if c.id != comment_id]
        self._total_comments = max(0, self._total_comments - 1)
        self._count_label.setText(f"({self._total_comments})")

        target = next((b for b in self._bubbles if b.comment.id == comment_id), None)
        if target is not None:
            self._bubbles.remove(target)
            target.deleteLater()

        self._empty_label.setVisible(len(self._comments) == 0)
        if self._material_id:
            self.comment_count_changed.emit(self._material_id, self._total_comments)

    @Slot(str)
    def _on_delete_error(self, detail: str) -> None:
        logger.warning("Failed to delete comment: %s", detail)
