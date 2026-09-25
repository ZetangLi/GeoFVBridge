# -*- coding: utf-8 -*-
"Shared application metadata, colors, fonts, dimensions, and Qt styles."

from . import __version__

APP_NAME = "GeoFVBridge"
APP_FULL_NAME = "Gmsh and Petrel to Reusable Finite-Volume Bridge"

APP_VERSION = __version__


class Colors:
    ACCENT = "#3498db"
    ACCENT_HOVER = "#2980b9"
    ACCENT_DARK = "#1a6fa5"
    SUCCESS = "#2ecc71"
    WARNING = "#f39c12"
    ERROR = "#e74c3c"
    INFO = "#9b59b6"

    BG_DARK = "#1e1e2e"
    BG_PANEL = "#252535"
    BG_CARD = "#2d2d40"
    BG_INPUT = "#363650"
    TEXT = "#e0e0e0"
    TEXT_DIM = "#8888a0"
    BORDER = "#404060"

    SIDEBAR_BG = "#1a1a2e"
    SIDEBAR_ITEM = "#2d2d45"
    SIDEBAR_SEL = "#3498db"


class Fonts:
    FAMILY = "Segoe UI"
    MONO = "Consolas"
    SIZE_S = 9
    SIZE_M = 10
    SIZE_L = 12
    SIZE_XL = 14
    SIZE_TITLE = 16


class Sizes:
    SIDEBAR_W = 200
    VISUALIZER_W = 460
    CONSOLE_H = 180
    TOOLBAR_H = 36
    ICON_SIZE = 20
    SPACING = 6
    RADIUS = 6


CUSTOM_QSS = f"""
/* Global dark application palette */
QMainWindow, QDialog, QWidget {{
    background-color: {Colors.BG_PANEL};
    color: {Colors.TEXT};
}}
QLabel, QCheckBox, QRadioButton {{
    background-color: transparent;
    color: {Colors.TEXT};
}}
QMenuBar, QMenu, QToolBar, QStatusBar {{
    background-color: {Colors.BG_PANEL};
    color: {Colors.TEXT};
}}
QMenuBar::item:selected, QMenu::item:selected {{
    background-color: {Colors.ACCENT_DARK};
}}
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox,
QTableWidget, QListWidget, QTreeWidget {{
    background-color: {Colors.BG_INPUT};
    color: {Colors.TEXT};
    border: 1px solid {Colors.BORDER};
    border-radius: 3px;
    selection-background-color: {Colors.ACCENT_DARK};
    selection-color: white;
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus,
QSpinBox:focus, QDoubleSpinBox:focus,
QTableWidget:focus, QListWidget:focus, QTreeWidget:focus {{
    border-color: {Colors.ACCENT};
}}
QHeaderView::section {{
    background-color: {Colors.BG_CARD};
    color: {Colors.TEXT};
    border: none;
    border-right: 1px solid {Colors.BORDER};
    border-bottom: 1px solid {Colors.BORDER};
    padding: 5px;
}}
QTableCornerButton::section {{
    background-color: {Colors.BG_CARD};
    border: 1px solid {Colors.BORDER};
}}
QTabWidget::pane {{
    border: 1px solid {Colors.BORDER};
    background-color: {Colors.BG_PANEL};
}}
QTabBar::tab {{
    background-color: {Colors.BG_CARD};
    color: {Colors.TEXT_DIM};
    border: 1px solid {Colors.BORDER};
    padding: 6px 12px;
}}
QTabBar::tab:selected {{
    background-color: {Colors.BG_INPUT};
    color: {Colors.ACCENT};
}}
QScrollArea, QScrollArea > QWidget > QWidget {{
    background-color: {Colors.BG_PANEL};
}}
QToolTip {{
    background-color: {Colors.BG_INPUT};
    color: {Colors.TEXT};
    border: 1px solid {Colors.BORDER};
}}

/* ── Sidebar ── */
#SidebarFrame {{
    background-color: {Colors.SIDEBAR_BG};
    border-right: 1px solid {Colors.BORDER};
}}
#SidebarButton {{
    text-align: left;
    padding: 10px 16px;
    border: none;
    border-radius: 4px;
    margin: 2px 6px;
    font-size: {Fonts.SIZE_M}pt;
    color: {Colors.TEXT};
    background-color: transparent;
}}
#SidebarButton:hover {{
    background-color: {Colors.SIDEBAR_ITEM};
}}
#SidebarButton:checked {{
    background-color: {Colors.ACCENT};
    color: white;
    font-weight: bold;
}}

/* ── Information bar ── */
#InfoBar {{
    background-color: {Colors.BG_PANEL};
    border-bottom: 1px solid {Colors.BORDER};
    padding: 4px 12px;
}}

/* ── Log console ── */
#ConsoleFrame {{
    background-color: {Colors.BG_DARK};
    border-top: 1px solid {Colors.BORDER};
}}
#ConsoleOutput {{
    background-color: {Colors.BG_DARK};
    color: {Colors.TEXT};
    font-family: {Fonts.MONO};
    font-size: {Fonts.SIZE_S}pt;
    border: none;
    padding: 6px;
}}

/* ── Visualization panel ── */
#VisualizerFrame {{
    background-color: {Colors.BG_DARK};
    border-left: 1px solid {Colors.BORDER};
}}

/* ── Center-panel card ── */
#PageCard {{
    background-color: {Colors.BG_CARD};
    border-radius: {Sizes.RADIUS}px;
    padding: 12px;
    margin: 4px;
}}

/* ── Section heading ── */
#SectionTitle {{
    font-size: {Fonts.SIZE_L}pt;
    font-weight: bold;
    color: {Colors.ACCENT};
    padding: 4px 0px;
    margin-top: 8px;
}}

/* ── Primary action button ── */
QPushButton#AccentButton {{
    background-color: {Colors.ACCENT};
    color: white;
    border: none;
    border-radius: 4px;
    padding: 8px 20px;
    font-weight: bold;
    font-size: {Fonts.SIZE_M}pt;
}}
QPushButton#AccentButton:hover {{
    background-color: {Colors.ACCENT_HOVER};
}}
QPushButton#AccentButton:pressed {{
    background-color: {Colors.ACCENT_DARK};
}}
QPushButton#AccentButton:disabled {{
    background-color: {Colors.BG_CARD};
    color: {Colors.TEXT_DIM};
    border: 1px solid {Colors.BORDER};
}}
QPushButton#AccentButton[compact="true"] {{
    padding: 2px 10px;
    font-size: {Fonts.SIZE_S}pt;
}}

/* ── Success and warning actions ── */
QPushButton#SuccessButton {{
    background-color: {Colors.SUCCESS};
    color: white;
    border: none;
    border-radius: 4px;
    padding: 8px 16px;
    font-weight: bold;
}}
QPushButton#SuccessButton:hover {{
    background-color: #27ae60;
}}

QPushButton#DangerButton {{
    background-color: {Colors.ERROR};
    color: white;
    border: none;
    border-radius: 4px;
    padding: 8px 16px;
    font-weight: bold;
}}

/* ── Group box ── */
QGroupBox {{
    border: 1px solid {Colors.BORDER};
    border-radius: {Sizes.RADIUS}px;
    margin-top: 12px;
    padding-top: 16px;
    font-weight: bold;
    color: {Colors.ACCENT};
    background-color: transparent;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}}

/* ── Splitter handle ── */
QSplitter::handle {{
    background-color: transparent;
}}
QSplitter::handle:hover {{
    background-color: {Colors.BORDER};
}}
QSplitter::handle:horizontal {{
    width: 2px;
}}
QSplitter::handle:vertical {{
    height: 2px;
}}
"""
