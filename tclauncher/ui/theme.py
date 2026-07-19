"""Central dark theme for the launcher.

A single application-wide stylesheet keeps the main window and every dialog
visually consistent. The accent is The Cycle's cyan, matching the original
launcher.
"""

# Palette
ACCENT = "#00c2e2"
ACCENT_HOVER = "#3ad2f0"
ACCENT_PRESSED = "#00a0bd"
ACCENT_TEXT = "#04222a"  # dark text on the accent fill

BG = "#14171c"
SURFACE = "#1c2027"
SURFACE_HI = "#242a32"
BORDER = "#333a44"

TEXT = "#e7eaee"
TEXT_DIM = "#98a0ab"

OK = "#37c46b"
WARN = "#f1c40f"
BAD = "#e5533c"

STATUS_COLORS = {"online": OK, "waiting": WARN, "offline": BAD}


STYLESHEET = f"""
* {{
    font-family: "Inter", "Segoe UI", "Noto Sans", "DejaVu Sans", sans-serif;
    font-size: 13px;
}}

QWidget {{
    background-color: {BG};
    color: {TEXT};
}}

/* Text widgets must not paint the window background over their container
   (otherwise labels show an opaque box on top of cards). */
QLabel, QCheckBox {{
    background: transparent;
}}

QToolTip {{
    background-color: {SURFACE_HI};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 4px 6px;
}}

/* Cards / framed panels */
QFrame#card {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}

QLabel#title {{
    font-size: 26px;
    font-weight: 800;
    letter-spacing: 3px;
    color: {TEXT};
}}
QLabel#subtitle {{
    font-size: 12px;
    letter-spacing: 2px;
    color: {ACCENT};
    text-transform: uppercase;
}}
QLabel#dim {{ color: {TEXT_DIM}; }}
QLabel#sectionLabel {{ color: {TEXT_DIM}; font-size: 11px; letter-spacing: 1px; }}

/* Default (secondary) buttons */
QPushButton {{
    background-color: {SURFACE_HI};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 9px 14px;
}}
QPushButton:hover {{ background-color: #2b323b; border-color: #47505c; }}
QPushButton:pressed {{ background-color: #20262d; }}
QPushButton:disabled {{ color: #5c636d; background-color: #191d23; border-color: #262b32; }}

/* Primary call-to-action */
QPushButton#primary {{
    background-color: {ACCENT};
    color: {ACCENT_TEXT};
    border: none;
    border-radius: 10px;
    font-size: 16px;
    font-weight: 700;
    letter-spacing: 1px;
    padding: 14px;
}}
QPushButton#primary:hover {{ background-color: {ACCENT_HOVER}; }}
QPushButton#primary:pressed {{ background-color: {ACCENT_PRESSED}; }}
QPushButton#primary:disabled {{
    background-color: #233034;
    color: #5f7e86;
}}

/* Flat link-style button (e.g. Log out) */
QPushButton#link {{
    background: transparent;
    border: none;
    color: {TEXT_DIM};
    padding: 4px 6px;
    text-decoration: underline;
}}
QPushButton#link:hover {{ color: {ACCENT}; }}

/* Inputs */
QLineEdit, QComboBox, QAbstractSpinBox {{
    background-color: {SURFACE_HI};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 8px;
    selection-background-color: {ACCENT};
    selection-color: {ACCENT_TEXT};
}}
QLineEdit:focus, QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background-color: {SURFACE_HI};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT};
    selection-color: {ACCENT_TEXT};
    outline: none;
}}

/* Checkboxes */
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {BORDER};
    border-radius: 4px;
    background: {SURFACE_HI};
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

/* Tables (env vars) */
QTableWidget {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 6px;
    gridline-color: {BORDER};
}}
QHeaderView::section {{
    background-color: {SURFACE_HI};
    color: {TEXT_DIM};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 6px;
}}

/* Scroll areas / lists */
QScrollArea {{ border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: #4a525d; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}

/* Progress */
QProgressBar {{
    background-color: {SURFACE_HI};
    border: none;
    border-radius: 5px;
    height: 8px;
    text-align: center;
}}
QProgressBar::chunk {{ background-color: {ACCENT}; border-radius: 5px; }}

QDialog {{ background-color: {BG}; }}

/* Mod manager rows */
QLabel#dialogTitle {{ font-size: 16px; font-weight: 700; }}
QFrame#modRow {{
    background-color: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
}}
"""


def apply_theme(app):
    app.setStyleSheet(STYLESHEET)
