"""The application's look.

Deliberately restrained: it adjusts spacing, weight and the few colours the app
needs to say something with (an error, a warning, the primary action), and
leaves everything else to the platform style so the app looks like a Windows
program rather than a website.
"""

from __future__ import annotations

from PySide6.QtGui import QPalette

_LIGHT = {
    "text": "#1b1b1f",
    "muted": "#5b5b66",
    "border": "#d0d0d8",
    "field": "#ffffff",
    "surface": "#f5f5f7",
    "accent": "#2f6fd0",
    "accent_text": "#ffffff",
    "error_bg": "#fdeced",
    "error_border": "#e5a6ab",
    "error_text": "#8c1c24",
    "warning_bg": "#fdf4e3",
    "warning_border": "#e3c68a",
    "warning_text": "#7a5602",
    "info": "#4a5a72",
}

_DARK = {
    "text": "#e8e8ec",
    "muted": "#a0a0ad",
    "border": "#43434d",
    "field": "#232329",
    "surface": "#1c1c21",
    "accent": "#5a95e8",
    "accent_text": "#10131a",
    "error_bg": "#3a2124",
    "error_border": "#7d4348",
    "error_text": "#f3b6bb",
    "warning_bg": "#3a3120",
    "warning_border": "#7b6533",
    "warning_text": "#f0d59a",
    "info": "#9fb3d0",
}


def is_dark(palette: QPalette) -> bool:
    """Whether the system is running a dark colour scheme."""
    window = palette.color(QPalette.ColorRole.Window)
    return window.lightness() < 128


def stylesheet(palette: QPalette) -> str:
    colours = _DARK if is_dark(palette) else _LIGHT
    return _TEMPLATE.format(**colours)


_TEMPLATE = """
QWidget {{
    color: {text};
}}
QLabel#paneTitle {{
    font-weight: 600;
    padding-bottom: 2px;
}}
QLabel#caption, QLabel#pageCounter {{
    color: {muted};
    font-size: 11px;
}}
QLabel#pivotNote {{
    color: {info};
    font-size: 11px;
}}
QLabel#pivotNote[tone="warning"] {{
    color: {warning_text};
    font-weight: 600;
}}
QPlainTextEdit, QTextEdit {{
    background: {field};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 8px;
    selection-background-color: {accent};
    selection-color: {accent_text};
}}
QScrollArea#previewArea {{
    background: {surface};
    border: 1px solid {border};
    border-radius: 6px;
}}
QLabel#previewPage {{
    color: {muted};
    padding: 24px;
}}
/* The input preview grows a visible border while a file is over it. */
QWidget[dropTarget="true"] QScrollArea#previewArea {{
    border: 2px dashed {accent};
}}
QPushButton {{
    padding: 6px 14px;
    border: 1px solid {border};
    border-radius: 6px;
    background: {field};
    min-height: 20px;
}}
QPushButton:hover:enabled {{
    border-color: {accent};
}}
QPushButton:disabled {{
    color: {muted};
}}
QPushButton#primary {{
    background: {accent};
    color: {accent_text};
    border: 1px solid {accent};
    font-weight: 600;
}}
QPushButton#primary:disabled {{
    background: {surface};
    color: {muted};
    border-color: {border};
}}
QComboBox {{
    padding: 5px 8px;
    border: 1px solid {border};
    border-radius: 6px;
    background: {field};
}}
QProgressBar {{
    border: 1px solid {border};
    border-radius: 6px;
    background: {surface};
    height: 8px;
}}
QProgressBar::chunk {{
    background: {accent};
    border-radius: 5px;
}}
QFrame#errorNotice {{
    background: {error_bg};
    border: 1px solid {error_border};
    border-radius: 6px;
}}
QFrame#errorNotice QLabel {{
    color: {error_text};
}}
QFrame#errorNotice[tone="warning"] {{
    background: {warning_bg};
    border-color: {warning_border};
}}
QFrame#errorNotice[tone="warning"] QLabel {{
    color: {warning_text};
}}
QFrame#banner {{
    background: {warning_bg};
    border: 1px solid {warning_border};
    border-radius: 6px;
}}
QFrame#banner QLabel {{
    color: {warning_text};
}}
QTabWidget::pane {{
    border: 1px solid {border};
    border-radius: 6px;
    top: -1px;
}}
QTabBar::tab {{
    padding: 8px 20px;
    border: 1px solid transparent;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}}
QTabBar::tab:selected {{
    border-color: {border};
    border-bottom-color: {field};
    font-weight: 600;
}}
"""
