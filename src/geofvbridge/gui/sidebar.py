"""Seven-stage workflow navigation sidebar."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QButtonGroup, QFrame, QLabel, QPushButton, QVBoxLayout, QWidget

from ..i18n import get_language, tr
from ..styles import APP_VERSION, Colors, Fonts, Sizes


class SidebarButton(QPushButton):
    def __init__(self, label: str, parent=None):
        super().__init__(f"  {label}", parent)
        self.setObjectName("SidebarButton")
        self.setCheckable(True)
        self.setFixedHeight(42)


class Sidebar(QWidget):
    page_changed = Signal(int)

    PAGE_IMPORT = 0
    PAGE_DATASET = 1
    PAGE_SOLVER = 2
    PAGE_MESH = 3
    PAGE_INP = 4
    PAGE_INCON = 5
    PAGE_OUT = 6
    PAGE_BACKEND = PAGE_SOLVER

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SidebarFrame")
        self.setFixedWidth(Sizes.SIDEBAR_W)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(2)
        logo = QLabel("GeoFVBridge")
        logo.setStyleSheet(
            f"font-size:{Fonts.SIZE_TITLE}pt;font-weight:bold;color:{Colors.ACCENT};"
            "padding:12px 16px 4px 16px;"
        )
        layout.addWidget(logo)
        subtitle = QLabel("Gmsh → FV → Solver")
        subtitle.setStyleSheet(
            f"font-size:{Fonts.SIZE_S}pt;color:{Colors.TEXT_DIM};padding:0 16px 12px 16px;"
        )
        layout.addWidget(subtitle)
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"color:{Colors.BORDER};")
        layout.addWidget(line)
        workflow = QLabel("  " + tr("navigation.workflow"))
        workflow.setStyleSheet(
            f"font-size:{Fonts.SIZE_S}pt;color:{Colors.TEXT_DIM};"
            "padding:8px 0 4px 0;font-weight:bold;"
        )
        layout.addWidget(workflow)

        zh = get_language() == "zh_CN"
        nav_items = [
            "1  有限元网格" if zh else "1  FE mesh",
            "2  FV 数据集" if zh else "2  FV dataset",
            "3  选择求解器" if zh else "3  Select solver",
            "4  TOUGH MESH",
            "5  flow.inp",
            "6  INCON",
            "7  结果提取" if zh else "7  Results",
        ]
        self.btn_group = QButtonGroup(self)
        self.btn_group.setExclusive(True)
        self.buttons = []
        for index, text in enumerate(nav_items):
            button = SidebarButton(text)
            self.btn_group.addButton(button, index)
            layout.addWidget(button)
            self.buttons.append(button)
        self.btn_group.idClicked.connect(self._on_click)
        layout.addStretch()
        version = QLabel(f"v{APP_VERSION} · FV / ECO2M")
        version.setStyleSheet(
            f"font-size:{Fonts.SIZE_S - 1}pt;color:{Colors.TEXT_DIM};padding:8px 16px;"
        )
        layout.addWidget(version)

    def _on_click(self, index: int):
        self.page_changed.emit(index)

    def set_active(self, index: int):
        if 0 <= index < len(self.buttons):
            self.buttons[index].setChecked(True)

    def set_page_enabled(self, index: int, enabled: bool) -> None:
        if 0 <= index < len(self.buttons):
            self.buttons[index].setEnabled(enabled)
