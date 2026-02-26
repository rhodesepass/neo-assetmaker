"""Material card widget for displaying a material asset preview.

A compact card with a preview image, title, operator name, category
badge, and a download button. Used in both the Market and Library pages.
"""

from __future__ import annotations

from typing import Any, Optional

from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    ImageLabel,
    PillPushButton,
    PrimaryToolButton,
    ToolTipFilter,
    ToolTipPosition,
)
from qtpy.QtCore import Qt, Signal
from qtpy.QtGui import QPixmap
from qtpy.QtWidgets import (
    QHBoxLayout,
    QVBoxLayout,
    QWidget,
)

from _mext.core.constants import MATERIAL_CARD_HEIGHT, MATERIAL_CARD_WIDTH
from _mext.models.material import Material


class MaterialCard(CardWidget):
    """Card widget showing a material's preview, metadata, and actions.

    Signals
    -------
    clicked(str)
        Emitted when the card body is clicked. Payload is the material ID.
    download_clicked(str)
        Emitted when the download button is clicked. Payload is the material ID.
    favorite_clicked(str)
        Emitted when the favorite toggle is clicked. Payload is the material ID.
    """

    clicked = Signal(str)
    download_clicked = Signal(str)
    favorite_clicked = Signal(str)

    def __init__(
        self,
        material: Material,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._material = material
        self.setFixedSize(MATERIAL_CARD_WIDTH, MATERIAL_CARD_HEIGHT)
        self._setup_ui()
        self._populate()

    def _setup_ui(self) -> None:
        """Build the card layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(4)

        # Preview image
        self._image_label = ImageLabel(self)
        self._image_label.setFixedSize(MATERIAL_CARD_WIDTH, 140)
        self._image_label.setBorderRadius(4, 4, 0, 0)
        layout.addWidget(self._image_label)

        # Text content area
        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(10, 4, 10, 0)
        text_layout.setSpacing(2)

        # Title
        self._title_label = BodyLabel("", self)
        self._title_label.setWordWrap(False)
        font = self._title_label.font()
        font.setBold(True)
        self._title_label.setFont(font)
        text_layout.addWidget(self._title_label)

        # Operator name
        self._operator_label = CaptionLabel("", self)
        text_layout.addWidget(self._operator_label)

        # Category + size row
        meta_layout = QHBoxLayout()
        meta_layout.setSpacing(6)

        self._category_pill = PillPushButton("", self)
        self._category_pill.setFixedHeight(20)
        self._category_pill.setCheckable(False)
        meta_layout.addWidget(self._category_pill)

        self._size_label = CaptionLabel("", self)
        meta_layout.addWidget(self._size_label)
        meta_layout.addStretch()

        text_layout.addLayout(meta_layout)
        layout.addLayout(text_layout)
        layout.addStretch()

        # Bottom row: rating + download button
        bottom_layout = QHBoxLayout()
        bottom_layout.setContentsMargins(10, 0, 10, 0)

        self._rating_label = CaptionLabel("", self)
        bottom_layout.addWidget(self._rating_label)
        bottom_layout.addStretch()

        self._download_btn = PrimaryToolButton(self)
        self._download_btn.setFixedSize(32, 32)
        self._download_btn.setText("下载")
        self._download_btn.installEventFilter(
            ToolTipFilter(self._download_btn, showDelay=300, position=ToolTipPosition.TOP)
        )
        self._download_btn.setToolTip("下载此素材")
        self._download_btn.clicked.connect(self._on_download_clicked)
        bottom_layout.addWidget(self._download_btn)

        layout.addLayout(bottom_layout)

    def _populate(self) -> None:
        """Fill card content from the material model."""
        self._title_label.setText(self._material.name)
        self._title_label.setToolTip(self._material.name)

        self._operator_label.setText(self._material.operator_name or "未知")
        self._category_pill.setText(self._material.category.display_name)
        self._size_label.setText(self._material.file_size_display)

        # Downloads count as rating proxy
        if self._material.download_count > 0:
            self._rating_label.setText(f"{self._material.download_count} 次下载")
        else:
            self._rating_label.setText("")

        # Load preview image (placeholder for now; async loading would be better)
        if self._material.preview_image_path:
            self._image_label.setToolTip("预览加载中...")
        else:
            # Set a placeholder color
            placeholder = QPixmap(MATERIAL_CARD_WIDTH, 140)
            placeholder.fill(Qt.GlobalColor.lightGray)
            self._image_label.setPixmap(placeholder)

    def mouseReleaseEvent(self, event: Any) -> None:  # noqa: N802
        """Emit clicked signal on card body click."""
        super().mouseReleaseEvent(event)
        self.clicked.emit(self._material.id)

    def _on_download_clicked(self) -> None:
        """Handle download button click without propagating to card click."""
        self.download_clicked.emit(self._material.id)

    @property
    def material(self) -> Material:
        """Return the material model associated with this card."""
        return self._material
