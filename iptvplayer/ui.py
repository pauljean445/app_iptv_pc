"""Pages graphiques : thème aux couleurs du logo, page d'accueil (mosaïques), fiche détaillée en grand."""
from dataclasses import dataclass

from PySide6.QtCore import QAbstractListModel, QModelIndex, QPoint, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QListView,
    QMenu,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

# Couleurs tirées du logo « Néon » : nuit profonde et violet lumineux
C = {
    "bg": "#100D22",        # fond des pages
    "panel": "#15122B",     # fond des fenêtres / listes
    "surface": "#1B1735",   # blocs de l'accueil
    "surface2": "#262046",  # emplacement des images, boutons secondaires
    "line": "#2F2959",
    "text": "#EEEBFF",
    "muted": "#A6A0CC",
    "accent": "#7B66FF",
    "accent_hi": "#9D8CFF",
    "live": "#FF5470",      # pastille « En direct »
}

QSS = f"""
#header {{ background: {C['panel']}; border-bottom: 1px solid {C['line']}; }}
#brand {{ font-size: 13pt; font-weight: 700; color: {C['text']}; }}
QTabBar#nav {{ background: transparent; }}
QTabBar#nav::tab {{ background: transparent; color: {C['muted']}; border: none; border-radius: 10px;
    padding: 7px 13px; margin: 9px 2px; font-size: 10.5pt; }}
QTabBar#nav::tab:hover {{ color: {C['text']}; background: rgba(255, 255, 255, 13); }}
QTabBar#nav::tab:selected {{ color: {C['text']}; background: rgba(123, 102, 255, 46); font-weight: 600; }}
QTabBar#nav::tab:disabled {{ color: {C['line']}; background: transparent; }}
QToolButton#burger {{ background: transparent; border: 1px solid transparent; border-radius: 10px; padding: 6px; }}
QToolButton#burger:hover, QToolButton#burger:checked {{ background: {C['surface2']}; border-color: {C['line']}; }}
QToolButton#menuTile {{ background: transparent; color: {C['text']}; border: 1.5px solid transparent;
    border-radius: 12px; padding: 10px 4px 8px 4px; font-size: 9.5pt; min-width: 76px; }}
QToolButton#menuTile:hover {{ background: rgba(255, 255, 255, 15); }}
QToolButton#menuTile[current="true"] {{ border-color: {C['accent_hi']}; background: rgba(123, 102, 255, 30); }}
#menuHead {{ color: #8C85B8; font-size: 8pt; font-weight: 700; letter-spacing: 1px; padding: 6px 10px 2px 10px; }}
#drawer {{ background: {C['panel']}; border: 1px solid {C['line']}; border-radius: 16px; }}
#drawerTitle {{ font-size: 12.5pt; font-weight: 700; color: {C['text']}; }}
QToolButton#drawerClose {{ background: transparent; border: none; border-radius: 8px; padding: 4px; }}
QToolButton#drawerClose:hover {{ background: {C['surface2']}; }}
QToolButton#quickTile {{ background: {C['surface']}; color: {C['text']}; border: 1px solid {C['line']};
    border-radius: 12px; padding: 12px 4px 10px 4px; font-size: 9pt; }}
QToolButton#quickTile:hover {{ border-color: {C['accent_hi']}; background: rgba(123, 102, 255, 30); }}
#drawerGroup {{ background: {C['surface']}; border: 1px solid {C['line']}; border-radius: 12px; }}
QPushButton#drawerRow {{ background: transparent; color: {C['text']}; border: none; border-radius: 9px;
    padding: 9px 10px; text-align: left; font-size: 10pt; }}
QPushButton#drawerRow:hover {{ background: rgba(255, 255, 255, 15); }}
#cardText {{ color: {C['text']}; font-size: 10pt; }}
#cardNote {{ color: {C['muted']}; font-size: 8.5pt; }}
#fieldLabel {{ color: #8C85B8; font-size: 8pt; font-weight: 700; letter-spacing: 1px; }}
QLineEdit#field {{ background: {C['bg']}; color: {C['text']}; border: 1px solid {C['line']}; border-radius: 9px;
    padding: 8px 11px; font-size: 10.5pt; selection-background-color: {C['accent']}; }}
QLineEdit#field:focus {{ border-color: {C['accent']}; }}
#notice {{ color: {C['muted']}; background: {C['surface']}; border: 1px solid {C['line']}; border-radius: 9px;
    padding: 8px 11px; font-size: 9.5pt; }}
#notice[error="true"] {{ color: #FFC2CD; background: rgba(255, 84, 112, 28); border-color: rgba(255, 84, 112, 120); }}
#kbd {{ color: {C['muted']}; border: 1px solid {C['line']}; background: {C['panel']}; border-radius: 6px;
    padding: 1px 7px; font-size: 8.5pt; }}
#shortcutGroup {{ color: {C['accent_hi']}; font-size: 8.5pt; font-weight: 700; letter-spacing: 1px; padding-top: 8px; }}
QPushButton#nowPlaying {{ background: {C['surface2']}; color: {C['text']}; border: 1px solid {C['line']};
    border-radius: 15px; padding: 5px 14px; }}
QPushButton#nowPlaying:hover {{ border-color: {C['accent']}; }}

#home, #detailsContent {{ background: {C['bg']}; }}
QScrollArea#homeScroll {{ background: {C['bg']}; border: none; }}
QPushButton#arrow {{ background: {C['surface2']}; color: {C['text']}; border: 1px solid {C['line']};
    border-radius: 14px; min-width: 28px; max-width: 28px; min-height: 28px; max-height: 28px;
    padding: 0; font-size: 14pt; }}
QPushButton#arrow:hover {{ border-color: {C['accent']}; }}
QPushButton#arrow:disabled {{ color: {C['line']}; }}
QToolButton#profileBtn {{ background: transparent; color: {C['text']}; border: 1px solid transparent;
    border-radius: 17px; padding: 3px 8px 3px 4px; font-size: 10pt; }}
QToolButton#profileBtn:hover {{ border-color: {C['line']}; background: {C['surface2']}; }}
QToolButton#profileBtn::menu-indicator {{ image: none; width: 0; }}
#pickerTitle {{ font-size: 22pt; font-weight: 700; color: {C['text']}; }}
QToolButton#profileTile {{ background: transparent; color: {C['text']}; border: 2px solid transparent;
    border-radius: 16px; padding: 12px; font-size: 12pt; }}
QToolButton#profileTile:hover, QToolButton#profileTile:focus {{ border-color: {C['accent_hi']};
    background: {C['surface']}; }}
QPushButton#colorChip {{ border: 2px solid transparent; border-radius: 15px; min-width: 26px; max-width: 26px;
    min-height: 26px; max-height: 26px; padding: 0; }}
QPushButton#colorChip:checked {{ border-color: white; }}
QPushButton#menuBtn {{ background: transparent; color: {C['text']}; border: none; font-size: 16pt;
    padding: 2px 10px; }}
QPushButton#menuBtn:hover {{ color: {C['accent_hi']}; }}
QPushButton#menuBtn::menu-indicator {{ image: none; width: 0; }}
#section {{ background: transparent; border: none; }}
QPushButton#sectionTitle {{ background: transparent; border: none; color: {C['text']};
    font-size: 17pt; font-weight: 700; padding: 0; text-align: left; }}
QPushButton#sectionTitle:hover {{ color: {C['accent_hi']}; }}
#sectionSub {{ color: {C['muted']}; font-size: 11.5pt; padding-top: 4px; }}
#groupTitle {{ color: {C['text']}; font-size: 19pt; font-weight: 700; padding-top: 6px; }}
QPushButton#subTitle {{ background: transparent; border: none; color: {C['muted']};
    font-size: 10.5pt; font-weight: 700; letter-spacing: 1.5px; padding: 0; text-align: left; }}
#groupLine, #groupSep {{ background: {C['line']}; }}
QPushButton#subTitle:hover {{ color: {C['accent_hi']}; }}
QPushButton#seeAll {{ background: transparent; border: none; color: {C['accent_hi']}; font-size: 10.5pt;
    font-weight: 600; padding: 0 4px; }}
QPushButton#seeAll:hover {{ color: {C['text']}; text-decoration: underline; }}
#empty {{ color: {C['muted']}; }}
#empty {{ font-size: 10.5pt; }}

QScrollArea#details {{ background: {C['bg']}; border: none; }}
#detTitle {{ font-size: 22pt; font-weight: 700; color: {C['text']}; }}
#detMeta {{ font-size: 11pt; color: {C['muted']}; }}
#detPlot {{ font-size: 12pt; color: {C['text']}; }}
#detCredits {{ font-size: 10pt; color: {C['muted']}; }}
#poster {{ background: {C['surface2']}; border-radius: 12px; color: {C['muted']}; }}
QPushButton#primary {{ background: {C['accent']}; color: white; border: none; border-radius: 9px;
    padding: 10px 20px; font-size: 11pt; font-weight: 600; }}
QPushButton#primary:hover {{ background: {C['accent_hi']}; }}
QPushButton#secondary {{ background: {C['surface2']}; color: {C['text']}; border: 1px solid {C['line']};
    border-radius: 9px; padding: 10px 18px; font-size: 11pt; }}
QPushButton#secondary:hover {{ border-color: {C['accent']}; }}
QPushButton#primary:disabled {{ background: {C['surface2']}; color: {C['muted']}; }}
QPushButton#danger {{ background: {C['live']}; color: white; border: none; border-radius: 9px;
    padding: 10px 20px; font-size: 11pt; font-weight: 600; }}
QPushButton#danger:hover {{ background: #FF7590; }}
QProgressBar#bar {{ background: {C['surface2']}; border: none; border-radius: 4px; max-height: 8px; min-height: 8px; }}
QProgressBar#bar::chunk {{ background: {C['accent_hi']}; border-radius: 4px; }}
#trackTitle {{ color: {C['muted']}; font-size: 10pt; font-weight: 600; padding-top: 7px; }}
QPushButton#langChip, QPushButton#subChip {{ background: {C['surface2']}; color: {C['text']};
    border: 1px solid {C['line']}; border-radius: 15px; padding: 6px 14px; font-size: 10pt; }}
QPushButton#langChip:hover, QPushButton#subChip:hover {{ border-color: {C['accent_hi']}; }}
QPushButton#langChip:checked {{ background: rgba(123, 102, 255, 60); border-color: {C['accent']}; }}
QPushButton#langChip:pressed {{ background: {C['accent']}; color: white; }}
QPushButton#subChip:checked {{ background: {C['accent']}; border-color: {C['accent_hi']}; color: white; }}

/* ---- Listes (chaînes, films, séries…) ---- */
#browseLeft {{ background: {C['panel']}; }}
QListView#itemList {{ background: {C['panel']}; border: none; outline: 0; }}
QLineEdit#bigSearch {{ background: {C['panel']}; color: {C['text']}; border: 1px solid {C['line']};
    border-radius: 12px; padding: 12px 16px; font-size: 13pt; selection-background-color: {C['accent']}; }}
QLineEdit#bigSearch:focus {{ border-color: {C['accent']}; }}
QLineEdit#search, QComboBox#groups {{ background: {C['bg']}; color: {C['text']}; border: 1px solid {C['line']};
    border-radius: 9px; padding: 7px 11px; font-size: 10.5pt; selection-background-color: {C['accent']}; }}
QLineEdit#search:focus, QComboBox#groups:focus, QComboBox#groups:on {{ border-color: {C['accent']}; }}
/* Catégories : liste déroulante sous le champ (et non sur toute la hauteur), chevron dessiné par GroupCombo */
QComboBox#groups {{ combobox-popup: 0; padding-right: 34px; }}
QComboBox#groups:hover {{ border-color: {C['accent']}; }}
QComboBox#groups::drop-down {{ border: none; width: 0; }}
QComboBox#groups::down-arrow {{ image: none; width: 0; }}
QFrame#groupsPopup {{ background: transparent; border: none; }}
QComboBox#groups QAbstractItemView {{ background: {C['surface']}; color: {C['text']}; border: 1px solid {C['accent']};
    border-radius: 10px; padding: 6px; outline: 0; font-size: 10.5pt; }}
QComboBox#groups QAbstractItemView::item {{ min-height: 32px; padding: 0 10px; border-radius: 7px; }}
QComboBox#groups QAbstractItemView::item:selected {{ background: {C['accent']}; color: white; }}
QComboBox#groups QScrollBar:vertical {{ width: 8px; margin: 4px 0; }}
QPushButton#backBtn {{ background: {C['surface2']}; color: {C['text']}; border: 1px solid {C['line']};
    border-radius: 9px; padding: 6px 12px; }}
QPushButton#backBtn:hover {{ border-color: {C['accent']}; }}
#navTitle {{ font-size: 11pt; font-weight: 700; color: {C['text']}; }}
#countLabel {{ color: {C['muted']}; font-size: 9pt; padding: 2px 4px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {C['line']}; border-radius: 3px; min-height: 36px; }}
QScrollBar::handle:vertical:hover {{ background: {C['accent']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QSplitter::handle {{ background: {C['line']}; width: 1px; }}
QStatusBar {{ background: {C['panel']}; color: {C['muted']}; border-top: 1px solid {C['line']}; }}
QToolTip {{ background: {C['surface2']}; color: {C['text']}; border: 1px solid {C['line']}; padding: 5px 8px; }}
QMenu {{ background: {C['surface']}; color: {C['text']}; border: 1px solid {C['line']}; padding: 6px; }}
QMenu::item {{ padding: 7px 26px 7px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {C['accent']}; color: white; }}
QMenu::item:disabled {{ color: {C['muted']}; }}
QMenu::separator {{ height: 1px; background: {C['line']}; margin: 5px 8px; }}

/* ---- Lecteur ---- */
#playerTop, #playerBar {{ background: #0B0918; }}
#playerTop {{ border-bottom: 1px solid {C['line']}; }}
#playerBar {{ border-top: 1px solid {C['line']}; }}
#playerTitle {{ font-size: 11.5pt; font-weight: 700; color: {C['text']}; }}
#playerSub {{ font-size: 9.5pt; color: {C['muted']}; }}
#time {{ font-size: 9.5pt; color: {C['text']}; }}
QToolButton#pbtn {{ background: transparent; border: none; border-radius: 19px; padding: 6px; color: {C['text']}; }}
QToolButton#pbtn:hover {{ background: rgba(255, 255, 255, 30); }}
QToolButton#pbtn:pressed {{ background: rgba(255, 255, 255, 55); }}
QToolButton#pbtn:checked {{ background: rgba(123, 102, 255, 90); }}
QToolButton#pbtn::menu-indicator {{ image: none; width: 0; }}
QToolButton#pbtnMain {{ background: {C['accent']}; border: none; border-radius: 23px; padding: 9px; }}
QToolButton#pbtnMain:hover {{ background: {C['accent_hi']}; }}
QToolButton#nextEp {{ background: rgba(123, 102, 255, 45); color: white; border: 1px solid {C['accent']};
    border-radius: 16px; padding: 6px 15px 6px 11px; font-size: 9.5pt; font-weight: 600; }}
QToolButton#nextEp:hover {{ background: {C['accent']}; border-color: {C['accent_hi']}; }}
QToolButton#nextEp:pressed {{ background: {C['accent_hi']}; }}
QToolButton#liveBadge {{ background: transparent; color: {C['muted']}; border: 1px solid {C['line']};
    border-radius: 13px; padding: 4px 11px 4px 8px; font-size: 9pt; font-weight: 600; }}
QToolButton#liveBadge[delayed="true"] {{ color: {C['text']}; border-color: {C['accent']};
    background: rgba(123, 102, 255, 45); }}
QToolButton#liveBadge[delayed="true"]:hover {{ background: {C['accent']}; color: white; }}
QToolButton#castBtn {{ background: rgba(255, 255, 255, 18); color: {C['text']}; border: 1px solid {C['line']};
    border-radius: 17px; padding: 5px 14px 5px 10px; font-size: 10pt; }}
QToolButton#castBtn:hover {{ border-color: {C['accent_hi']}; }}
QToolButton#castBtn[casting="true"] {{ background: {C['accent']}; border-color: {C['accent_hi']}; color: white; }}
QToolButton#castBtn::menu-indicator {{ image: none; width: 0; }}
QSlider#seek::groove:horizontal, QSlider#volume::groove:horizontal {{ height: 4px; border-radius: 2px;
    background: rgba(255, 255, 255, 45); }}
QSlider#seek::sub-page:horizontal, QSlider#volume::sub-page:horizontal {{ border-radius: 2px; background: {C['accent_hi']}; }}
QSlider#seek::handle:horizontal, QSlider#volume::handle:horizontal {{ background: white; width: 14px; height: 14px;
    margin: -5px 0; border-radius: 7px; }}
QSlider#seek::handle:horizontal:hover {{ background: {C['accent_hi']}; }}
"""


def apply_theme(app) -> None:
    """Thème sombre aux couleurs du logo pour toute l'application (style Fusion + palette)."""
    app.setStyle("Fusion")
    p = QPalette()
    roles = {
        QPalette.Window: C["panel"], QPalette.WindowText: C["text"], QPalette.Base: C["bg"],
        QPalette.AlternateBase: C["surface"], QPalette.Text: C["text"], QPalette.Button: C["surface2"],
        QPalette.ButtonText: C["text"], QPalette.BrightText: "#FFFFFF", QPalette.Highlight: C["accent"],
        QPalette.HighlightedText: "#FFFFFF", QPalette.ToolTipBase: C["surface2"], QPalette.ToolTipText: C["text"],
        QPalette.PlaceholderText: C["muted"], QPalette.Link: C["accent_hi"], QPalette.Mid: C["line"],
        QPalette.Dark: "#0B0918", QPalette.Light: C["line"], QPalette.Midlight: C["surface2"],
        QPalette.Shadow: "#000000",
    }
    for role, color in roles.items():
        p.setColor(role, QColor(color))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, QColor("#6C6694"))
    app.setPalette(p)
    app.setStyleSheet(QSS)


# --------------------------------------------------------------------------- #
# Icônes vectorielles (nettes à toutes les tailles, contrastées sur fond sombre)
# --------------------------------------------------------------------------- #
_ICONS: dict = {}


def _g24_pen(p, col, width=2.0):
    p.setPen(QPen(col, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(Qt.NoBrush)


def _g24_poly(p, col, *polylines, closed=False):
    _g24_pen(p, col)
    for pts in polylines:
        path = QPainterPath()
        path.moveTo(*pts[0])
        for pt in pts[1:]:
            path.lineTo(*pt)
        if closed:
            path.closeSubpath()
        p.drawPath(path)


def _g24_arc(p, col, cx, cy, r, start, sweep):
    _g24_pen(p, col)
    path = QPainterPath()
    rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
    path.arcMoveTo(rect, start)
    path.arcTo(rect, start, sweep)
    p.drawPath(path)


def _g24_fill(p, col, pts=None, circle=None):
    p.setPen(Qt.NoPen)
    p.setBrush(col)
    if circle:
        cx, cy, r = circle
        p.drawEllipse(QRectF(cx - r, cy - r, 2 * r, 2 * r))
    else:
        path = QPainterPath()
        path.moveTo(*pts[0])
        for pt in pts[1:]:
            path.lineTo(*pt)
        path.closeSubpath()
        p.drawPath(path)


def _g24_rrect(p, col, x, y, w, h, r=2.5):
    _g24_pen(p, col)
    p.drawRoundedRect(QRectF(x, y, w, h), r, r)


# Icônes du bandeau et du menu (même dessin que les maquettes validées), grille 24×24
_GRID24 = {
    "home": lambda p, c: _g24_poly(p, c, [(4, 11), (12, 4), (20, 11), (20, 20), (15, 20), (15, 14), (9, 14),
                                          (9, 20), (4, 20)], closed=True),
    "live": lambda p, c: (_g24_rrect(p, c, 3, 6, 18, 13), _g24_poly(p, c, [(8, 2), (12, 6), (16, 2)]),
                          _g24_fill(p, c, circle=(12, 12.5, 2.4))),
    "film": lambda p, c: (_g24_rrect(p, c, 3, 4, 18, 16), _g24_poly(
        p, c, [(8, 4), (8, 20)], [(16, 4), (16, 20)], [(3, 9), (8, 9)], [(3, 15), (8, 15)], [(16, 9), (21, 9)],
        [(16, 15), (21, 15)])),
    "series": lambda p, c: (_g24_rrect(p, c, 3, 8, 18, 12), _g24_poly(p, c, [(6, 5), (18, 5)], [(9, 2), (15, 2)]),
                            _g24_fill(p, c, [(10.5, 11), (14.5, 14), (10.5, 17)])),
    "replay": lambda p, c: (_g24_arc(p, c, 12, 12, 8, 180, 315), _g24_poly(p, c, [(4, 4), (4, 8.5), (8.5, 8.5)],
                                                                           [(12, 8), (12, 12.5), (15, 14.5)])),
    "plug": lambda p, c: (_g24_poly(p, c, [(9, 3), (9, 8)], [(15, 3), (15, 8)], [(6, 11), (6, 8), (18, 8), (18, 11)],
                                    [(12, 17), (12, 21)]), _g24_arc(p, c, 12, 11, 6, 0, -180)),
    "reload": lambda p, c: (_g24_arc(p, c, 12, 12, 8, 0, -315), _g24_poly(p, c, [(20, 4), (20, 8.5), (15.5, 8.5)])),
    "star": lambda p, c: _g24_poly(p, c, [(12, 3), (14.7, 8.6), (20.8, 9.5), (16.4, 13.8), (17.4, 19.9), (12, 17),
                                          (6.6, 19.9), (7.6, 13.8), (3.2, 9.5), (9.3, 8.6)], closed=True),
    "keyboard": lambda p, c: (_g24_rrect(p, c, 2, 6, 20, 12), _g24_poly(
        p, c, [(6, 10), (7, 10)], [(10, 10), (11, 10)], [(14, 10), (15, 10)], [(18, 10), (18.5, 10)], [(7, 14), (17, 14)])),
    "quit": lambda p, c: _g24_poly(p, c, [(14, 4), (19, 4), (19, 20), (14, 20)], [(10, 8), (6, 12), (10, 16)],
                                   [(6, 12), (16, 12)]),
    "edit": lambda p, c: _g24_poly(p, c, [(4, 20), (8, 20), (19, 9), (15, 5), (4, 16)], closed=True),
    "close": lambda p, c: _g24_poly(p, c, [(6, 6), (18, 18)], [(18, 6), (6, 18)]),
    "menu": lambda p, c: _g24_poly(p, c, [(4, 7), (20, 7)], [(4, 12), (20, 12)], [(4, 17), (20, 17)]),
    "download": lambda p, c: _g24_poly(p, c, [(12, 4), (12, 15)], [(7, 10), (12, 15), (17, 10)],
                                       [(4, 16), (4, 20), (20, 20), (20, 16)]),
    "trash": lambda p, c: _g24_poly(p, c, [(4, 7), (20, 7)], [(9, 7), (9, 4), (15, 4), (15, 7)],
                                    [(6, 7), (7, 20), (17, 20), (18, 7)]),
    "add_profile": lambda p, c: (_g24_dashed_circle(p, c), _g24_poly(p, c, [(12, 8), (12, 16)], [(8, 12), (16, 12)])),
    "account": lambda p, c: (_g24_arc(p, c, 12, 8, 4, 0, 360), _g24_arc(p, c, 12, 21, 7.5, 0, 180)),
    "search": lambda p, c: (_g24_arc(p, c, 10.5, 10.5, 6.5, 0, 360), _g24_poly(p, c, [(15.5, 15.5), (20, 20)])),
}


def _g24_dashed_circle(p, col):
    pen = QPen(col, 1.1, Qt.CustomDashLine, Qt.RoundCap)
    pen.setDashPattern([2.2, 2.2])
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QRectF(1.5, 1.5, 21, 21))


def icon(name: str, color: str | None = None, size: int = 96) -> QIcon:
    """Icône dessinée sur une grille 64×64 : play, pause, stop, prev, next, back10, back30, fwd10, fwd30,
    volume, mute, fullscreen, cast, cast_on, subtitles, audio, chevron_left."""
    key = (name, color, size)
    if key in _ICONS:
        return _ICONS[key]
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 64, size / 64)
    col = QColor(color or C["text"])
    stroke = QPen(col, 5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)

    def fill_poly(points, rounding=4):
        path = QPainterPath()
        path.moveTo(*points[0])
        for pt in points[1:]:
            path.lineTo(*pt)
        path.closeSubpath()
        p.setPen(QPen(col, rounding, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(col)
        p.drawPath(path)

    def lines(*segments):
        p.setPen(stroke)
        p.setBrush(Qt.NoBrush)
        for seg in segments:
            path = QPainterPath()
            path.moveTo(*seg[0])
            for pt in seg[1:]:
                path.lineTo(*pt)
            p.drawPath(path)

    def arc(cx, cy, r, start, sweep, pen=None):
        path = QPainterPath()
        rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
        path.arcMoveTo(rect, start)
        path.arcTo(rect, start, sweep)
        p.setPen(pen or stroke)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)

    if name == "play":
        fill_poly([(22, 14), (22, 50), (51, 32)])
    elif name == "pause":
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawRoundedRect(QRectF(17, 14, 11, 36), 3, 3)
        p.drawRoundedRect(QRectF(36, 14, 11, 36), 3, 3)
    elif name == "stop":
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawRoundedRect(QRectF(17, 17, 30, 30), 5, 5)
    elif name in ("prev", "next"):
        if name == "next":
            p.translate(64, 0)
            p.scale(-1, 1)
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawRoundedRect(QRectF(12, 16, 6, 32), 2, 2)
        fill_poly([(50, 16), (50, 48), (24, 32)])
    elif name.startswith(("back", "fwd")):  # back10, fwd30… ; back1m, fwd5m… (minutes, pour les replays)
        seconds = name[4:] if name.startswith("back") else name[3:]
        p.save()
        if name.startswith("back"):
            p.translate(64, 0)
            p.scale(-1, 1)
        # Flèche circulaire dans le sens horaire, pointe en haut
        arc(32, 34, 21, 35, -300, QPen(col, 4.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        fill_poly([(39, 13), (29, 6.5), (29, 19.5)], 2)
        p.restore()
        f = QFont()
        f.setPixelSize(17)
        f.setBold(True)
        p.setFont(f)
        p.setPen(col)
        p.drawText(QRectF(12, 23, 40, 24), Qt.AlignCenter, seconds)
    elif name in ("volume", "mute"):
        fill_poly([(9, 25), (19, 25), (31, 14), (31, 50), (19, 39), (9, 39)], 3)
        if name == "volume":
            arc(31, 32, 10, -50, 100)
            arc(31, 32, 19, -50, 100)
        else:
            lines([(41, 24), (55, 40)], [(55, 24), (41, 40)])
    elif name == "fullscreen":
        lines([(11, 24), (11, 11), (24, 11)], [(40, 11), (53, 11), (53, 24)],
              [(53, 40), (53, 53), (40, 53)], [(24, 53), (11, 53), (11, 40)])
    elif name in ("cast", "cast_on"):
        if name == "cast_on":
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(col.red(), col.green(), col.blue(), 110))
            p.drawRoundedRect(QRectF(22, 20, 26, 22), 3, 3)
        lines([(9, 22), (9, 13), (55, 13), (55, 51), (38, 51)])
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawEllipse(QRectF(5, 47, 9, 9))
        arc(9, 51, 15, 0, 90)
        arc(9, 51, 25, 0, 90)
    elif name == "subtitles":
        p.setPen(QPen(col, 4.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(7, 13, 50, 38), 7, 7)
        lines([(17, 32), (28, 32)], [(35, 32), (47, 32)], [(17, 41), (39, 41)])
    elif name == "audio":
        p.setPen(QPen(col, 4.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        path = QPainterPath()
        path.addRoundedRect(QRectF(7, 10, 50, 34), 9, 9)
        p.drawPath(path)
        fill_poly([(17, 42), (17, 55), (30, 43)], 3)
        lines([(18, 23), (46, 23)], [(18, 32), (38, 32)])
    elif name == "chevron_left":
        lines([(38, 13), (20, 32), (38, 51)])
    elif name == "chevron_down":
        lines([(18, 25), (32, 39), (46, 25)])
    elif name in _GRID24:
        p.scale(64 / 24, 64 / 24)  # icônes dessinées sur une grille de 24 (bandeau, menu)
        _GRID24[name](p, col)
    elif name == "dot":
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawEllipse(QRectF(12, 12, 40, 40))
    p.end()
    ic = QIcon(pm)
    _ICONS[key] = ic
    return ic


def avatar_stack(profiles: list[dict], height: int = 26, scale: int = 2):
    """Pastilles des profils empilées (profil en cours devant, 3 au plus) suivies d'un petit chevron."""
    shown = profiles[:3]
    d, step = height * scale, int(height * 0.62) * scale
    width = d + step * (len(shown) - 1) + 14 * scale
    pm = QPixmap(width, d)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    for i in reversed(range(len(shown))):  # le 1er (profil en cours) est dessiné en dernier, donc devant
        prof = shown[i]
        x = i * step
        p.setPen(QPen(QColor(C["panel"]), 2 * scale))
        p.setBrush(QColor(prof["color"]))
        p.drawEllipse(QRectF(x + scale, scale, d - 2 * scale, d - 2 * scale))
        f = QFont()
        f.setPixelSize(int(d * 0.46))
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("white"))
        p.drawText(QRectF(x, 0, d, d * 0.97), Qt.AlignCenter, (prof["name"].strip()[:1] or "?").upper())
    p.setPen(QPen(QColor(C["muted"]), 1.6 * scale, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    cx, cy = width - 6 * scale, d / 2
    path = QPainterPath()
    path.moveTo(cx - 3.5 * scale, cy - 1.8 * scale)
    path.lineTo(cx, cy + 1.8 * scale)
    path.lineTo(cx + 3.5 * scale, cy - 1.8 * scale)
    p.setBrush(Qt.NoBrush)
    p.drawPath(path)
    p.end()
    return QIcon(pm), QSize(width // scale, height)  # (icône, taille à l'écran)


def avatar(name: str, color: str, size: int = 128) -> QIcon:
    """Pastille de profil : initiale blanche sur un disque de la couleur du profil."""
    key = ("avatar", name, color, size)
    if key in _ICONS:
        return _ICONS[key]
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawEllipse(QRectF(0, 0, size, size))
    f = QFont()
    f.setPixelSize(int(size * 0.5))
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor("white"))
    p.drawText(QRectF(0, 0, size, size * 0.97), Qt.AlignCenter, (name.strip()[:1] or "?").upper())
    p.end()
    ic = QIcon(pm)
    _ICONS[key] = ic
    return ic


# --------------------------------------------------------------------------- #
# Lignes des listes (chaînes, films, séries, épisodes, programmes)
# --------------------------------------------------------------------------- #
@dataclass
class Row:
    title: str
    subtitle: str = ""
    progress: float = -1.0   # 0..1 : barre de progression (reprise), -1 : aucune
    fav: bool = False
    playing: bool = False
    watched: bool = False


class ListDelegate(QStyledItemDelegate):
    """Ligne moderne : vignette arrondie, titre en gras, ligne d'infos, progression, badges."""

    def __init__(self, images, describe, parent=None):
        super().__init__(parent)
        self.images = images
        self.describe = describe  # item -> Row
        self.set_mode(False)

    def set_mode(self, poster: bool):
        self.poster = poster
        self.thumb = QSize(40, 60) if poster else QSize(56, 38)
        self.row_h = 72 if poster else 54

    def sizeHint(self, option, index):
        return QSize(240, self.row_h)

    def paint(self, p: QPainter, option, index):
        it = index.model().items[index.row()]
        row = self.describe(it)
        r = QRectF(option.rect).adjusted(6, 2, -6, -2)
        selected = bool(option.state & QStyle.State_Selected)
        hover = bool(option.state & QStyle.State_MouseOver)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        if selected:
            bg = QPainterPath()
            bg.addRoundedRect(r, 9, 9)
            p.fillPath(bg, QColor(123, 102, 255, 75))
            p.fillRect(QRectF(r.x(), r.y() + 8, 3, r.height() - 16), QColor(C["accent_hi"]))
        elif hover:
            bg = QPainterPath()
            bg.addRoundedRect(r, 9, 9)
            p.fillPath(bg, QColor(C["surface"]))

        # Vignette
        tw, th = self.thumb.width(), self.thumb.height()
        box = QRectF(r.x() + 10, r.center().y() - th / 2, tw, th)
        clip = QPainterPath()
        clip.addRoundedRect(box, 6, 6)
        p.fillPath(clip, QColor(C["surface2"]))
        pad = 0 if self.poster else 4
        inner = box.adjusted(pad, pad, -pad, -pad)
        pm = self.images.pixmap(it.logo, int(inner.width()), int(inner.height())) if it.logo else None
        p.setClipPath(clip)
        if pm is not None:
            dpr = pm.devicePixelRatio()
            w, h = pm.width() / dpr, pm.height() / dpr
            p.drawPixmap(QRectF(inner.x() + (inner.width() - w) / 2, inner.y() + (inner.height() - h) / 2, w, h),
                         pm, QRectF(pm.rect()))
        else:
            f = QFont(option.font)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor(C["muted"]))
            initials = "".join(w[0] for w in row.title.replace("|", " ").split() if w[:1].isalnum())[:2].upper()
            p.drawText(box, Qt.AlignCenter, initials)
        p.setClipping(False)

        # Badges à droite
        right = r.right() - 10
        small = QFont(option.font)
        small.setPointSizeF(option.font.pointSizeF() * 0.8)
        small.setBold(True)
        if row.playing:
            p.setFont(small)
            fm = p.fontMetrics()
            text = "EN LECTURE"
            w = fm.horizontalAdvance(text) + 14
            pill = QRectF(right - w, r.center().y() - 10, w, 20)
            path = QPainterPath()
            path.addRoundedRect(pill, 10, 10)
            p.fillPath(path, QColor(C["accent"]))
            p.setPen(QColor("white"))
            p.drawText(pill, Qt.AlignCenter, text)
            right -= w + 8
        sym = QFont(option.font)
        sym.setPointSizeF(option.font.pointSizeF() * 1.25)
        p.setFont(sym)
        for flag, char, color in ((row.fav, "★", C["accent_hi"]), (row.watched, "✓", "#5FD39A")):
            if flag:
                p.setPen(QColor(color))
                p.drawText(QRectF(right - 20, r.y(), 20, r.height()), Qt.AlignCenter, char)
                right -= 24

        # Textes
        x = box.right() + 12
        w = max(20, right - x - 4)
        title_f = QFont(option.font)
        title_f.setPointSizeF(option.font.pointSizeF() * 1.06)
        title_f.setBold(True)
        sub_f = QFont(option.font)
        sub_f.setPointSizeF(option.font.pointSizeF() * 0.93)
        p.setFont(title_f)
        fm1 = p.fontMetrics()
        p.setFont(sub_f)
        fm2 = p.fontMetrics()
        bar_h = 7 if row.progress >= 0 else 0
        block = fm1.height() + (fm2.height() + 1 if row.subtitle else 0) + bar_h
        y = r.center().y() - block / 2
        p.setFont(title_f)
        p.setPen(QColor("white" if selected else C["text"]))
        p.drawText(QRectF(x, y, w, fm1.height()), Qt.AlignLeft | Qt.AlignVCenter,
                   fm1.elidedText(row.title, Qt.ElideRight, int(w)))
        y += fm1.height() + 1
        if row.subtitle:
            p.setFont(sub_f)
            p.setPen(QColor(C["muted"]))
            p.drawText(QRectF(x, y, w, fm2.height()), Qt.AlignLeft | Qt.AlignVCenter,
                       fm2.elidedText(row.subtitle, Qt.ElideRight, int(w)))
            y += fm2.height()
        if row.progress >= 0:
            bw = min(150.0, w)
            track = QPainterPath()
            track.addRoundedRect(QRectF(x, y + 3, bw, 4), 2, 2)
            p.fillPath(track, QColor(255, 255, 255, 40))
            done = QPainterPath()
            done.addRoundedRect(QRectF(x, y + 3, max(4.0, bw * min(1.0, row.progress)), 4), 2, 2)
            p.fillPath(done, QColor(C["accent_hi"]))
        p.restore()


# --------------------------------------------------------------------------- #
# Mosaïques de l'accueil
# --------------------------------------------------------------------------- #
@dataclass
class Tile:
    item: object
    title: str
    subtitle: str = ""
    progress: float = -1.0  # 0..1, ou -1 sans barre de progression


class TileModel(QAbstractListModel):
    def __init__(self):
        super().__init__()
        self.tiles: list[Tile] = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.tiles)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        t = self.tiles[index.row()]
        if role == Qt.DisplayRole:
            return t.title
        if role == Qt.ToolTipRole:
            return f"{t.title}\n{t.subtitle}" if t.subtitle else t.title
        return None

    def set_tiles(self, tiles):
        self.beginResetModel()
        self.tiles = tiles
        self.endResetModel()


class TileDelegate(QStyledItemDelegate):
    """Dessine une vignette : image (affiche ou logo), barre de progression, titre et sous-titre."""

    def __init__(self, images, width: int, poster: bool, parent=None, tile_fn=None):
        super().__init__(parent)
        self.images = images
        self.tile_fn = tile_fn  # index -> Tile (vue branchée sur un autre modèle que TileModel)
        self.set_size(width, poster)

    def set_size(self, width: int, poster: bool):
        self.width = width
        self.poster = poster
        self.img_h = int(width * 1.5) if poster else int(width * 0.62)

    def sizeHint(self, option, index):
        return QSize(self.width + 12, self.img_h + 58)

    @staticmethod
    def remove_rect(rect) -> QRectF:
        """Croix « retirer » en haut à droite de l'image (vignette survolée)."""
        r = QRectF(rect).adjusted(6, 6, -6, -6)
        return QRectF(r.right() - 31, r.y() + 7, 24, 24)

    def paint(self, p: QPainter, option, index):
        tile = self.tile_fn(index) if self.tile_fn else index.model().tiles[index.row()]
        r = QRectF(option.rect).adjusted(6, 6, -6, -6)
        hover = bool(option.state & QStyle.State_MouseOver) or bool(option.state & QStyle.State_HasFocus)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)

        box = QRectF(r.x(), r.y(), r.width(), self.img_h)
        path = QPainterPath()
        path.addRoundedRect(box, 10, 10)
        p.fillPath(path, QColor(C["surface2"]))
        pad = 0 if self.poster else 12
        inner = box.adjusted(pad, pad, -pad, -pad)
        pm = self.images.pixmap(getattr(tile.item, "logo", ""), int(inner.width()), int(inner.height()))
        p.setClipPath(path)
        if pm is not None:
            dpr = pm.devicePixelRatio()
            w, h = pm.width() / dpr, pm.height() / dpr
            target = QRectF(inner.x() + (inner.width() - w) / 2, inner.y() + (inner.height() - h) / 2, w, h)
            p.drawPixmap(target, pm, QRectF(pm.rect()))
        else:  # pas d'image : initiales du titre
            f = QFont(option.font)
            f.setPointSizeF(f.pointSizeF() * 1.8)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor(C["muted"]))
            initials = "".join(w[0] for w in tile.title.replace("|", " ").split() if w[:1].isalnum())[:2].upper()
            p.drawText(box, Qt.AlignCenter, initials or "▶")
        if tile.progress >= 0:
            bar = QRectF(box.x(), box.bottom() - 5, box.width(), 5)
            p.fillRect(bar, QColor(255, 255, 255, 60))
            p.fillRect(QRectF(bar.x(), bar.y(), bar.width() * min(1.0, tile.progress), bar.height()),
                       QColor(C["accent_hi"]))
        p.setClipping(False)
        if hover:
            p.setPen(QPen(QColor(C["accent_hi"]), 2))
            p.drawPath(path)
        view = self.parent()
        if option.state & QStyle.State_MouseOver and getattr(view, "removable", False):
            badge = self.remove_rect(option.rect)
            over = badge.contains(getattr(view, "hover_pos", QPointF(-1, -1)))
            p.setPen(QPen(QColor(C["live"] if over else C["line"]), 1))
            p.setBrush(QColor(C["live"]) if over else QColor(11, 9, 24, 215))
            p.drawEllipse(badge)
            pen = QPen(QColor("white"), 1.8)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            c, d = badge.center(), 4.2
            p.drawLine(QPointF(c.x() - d, c.y() - d), QPointF(c.x() + d, c.y() + d))
            p.drawLine(QPointF(c.x() + d, c.y() - d), QPointF(c.x() - d, c.y() + d))

        f = QFont(option.font)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(C["text"]))
        fm = p.fontMetrics()
        y = box.bottom() + 7
        p.drawText(QRectF(r.x(), y, r.width(), fm.height()), Qt.AlignLeft | Qt.AlignVCenter,
                   fm.elidedText(tile.title, Qt.ElideRight, int(r.width())))
        if tile.subtitle:
            f.setBold(False)
            f.setPointSizeF(f.pointSizeF() * 0.92)
            p.setFont(f)
            p.setPen(QColor(C["muted"]))
            fm2 = p.fontMetrics()
            p.drawText(QRectF(r.x(), y + fm.height() + 2, r.width(), fm2.height()), Qt.AlignLeft | Qt.AlignVCenter,
                       fm2.elidedText(tile.subtitle, Qt.ElideRight, int(r.width())))
        p.restore()


class Mosaic(QListView):
    """Bande horizontale de vignettes (une seule rangée, défilement latéral).
    remove_label : si donné, chaque vignette peut être retirée (croix au survol, clic droit, touche Suppr)."""

    tileClicked = Signal(object)
    tileRemoved = Signal(object)

    def __init__(self, images, poster: bool, remove_label: str = "", rows: int = 1):
        """rows = 2 : une seule ligne tant que les vignettes tiennent dans la largeur ; au-delà, deux lignes remplies
        dans l'ordre (la 1re moitié en haut, la suite en bas) et défilement vers la droite."""
        super().__init__()
        self.max_rows = rows
        self._raw: list = []
        self._shape = None
        self.remove_label = remove_label
        self.removable = bool(remove_label)
        self.hover_pos = QPointF(-1, -1)
        self.setViewMode(QListView.IconMode)
        self.setFlow(QListView.LeftToRight)
        self.setWrapping(False)
        self.setMovement(QListView.Static)
        self.setUniformItemSizes(True)
        self.setSpacing(2)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollMode(QListView.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # flèches ‹ › dans l'en-tête
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setEditTriggers(QListView.NoEditTriggers)
        self.setMouseTracking(True)
        self.viewport().setAttribute(Qt.WA_Hover)
        self.setStyleSheet("QListView { background: transparent; }")
        self.tiles = TileModel()
        self.setModel(self.tiles)
        delegate = TileDelegate(images, (136 if rows == 1 else 112) if poster else 164, poster, self)
        self.setItemDelegate(delegate)
        self.setFixedHeight(delegate.sizeHint(None, None).height() + 2 * self.spacing() + 8)
        self.clicked.connect(self._emit)

    def set_tiles(self, tiles):
        self._raw = list(tiles)
        self._shape = None
        self._layout_rows()

    def _layout_rows(self):
        """1 ligne si tout tient dans la largeur, sinon 2 lignes remplies dans l'ordre (mosaïques des groupes)."""
        tiles = self._raw
        if self.max_rows == 1:
            if self._shape is None:
                self.tiles.set_tiles(tiles)
                self._shape = 1
            return
        size = self.itemDelegate().sizeHint(None, None)
        cell = size.width() + 2 * self.spacing()
        cols = max(1, self.viewport().width() // cell)
        rows = 2 if len(tiles) > cols else 1
        shape = (rows, len(tiles), cols if rows == 2 else 0)
        if shape == self._shape:
            return
        self._shape = shape
        if rows == 2:
            # Le flux haut→bas range les vignettes colonne par colonne : ordre réarrangé pour que la ligne du haut
            # montre la 1re moitié et celle du bas la suite (lecture ligne par ligne)
            half = (len(tiles) + 1) // 2
            order = []
            for j in range(half):
                order.append(tiles[j])
                if half + j < len(tiles):
                    order.append(tiles[half + j])
            self.setFlow(QListView.TopToBottom)
            self.setWrapping(True)
        else:
            order = tiles
            self.setFlow(QListView.LeftToRight)
            self.setWrapping(False)
        self.setFixedHeight(rows * (size.height() + 2 * self.spacing()) + 8)
        self.tiles.set_tiles(order)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.max_rows > 1 and event.size().width() != event.oldSize().width():
            self._layout_rows()

    def _emit(self, index):
        if index.isValid():
            self.tileClicked.emit(self.tiles.tiles[index.row()].item)

    def _remove(self, index):
        if index.isValid() and self.removable:
            self.tileRemoved.emit(self.tiles.tiles[index.row()].item)

    def _on_badge(self, pos) -> QModelIndex | None:
        """Vignette dont la croix est sous pos (coordonnées de la zone d'affichage), sinon None."""
        index = self.indexAt(pos)
        if self.removable and index.isValid() and TileDelegate.remove_rect(self.visualRect(index)).contains(pos):
            return index
        return None

    def mouseMoveEvent(self, event):
        # Main uniquement au-dessus d'une vignette, pas sur le vide de la bande
        super().mouseMoveEvent(event)
        self.hover_pos = event.position()
        index = self.indexAt(event.position().toPoint())
        self.viewport().setCursor(Qt.PointingHandCursor if index.isValid() else Qt.ArrowCursor)
        badge = self._on_badge(event.position().toPoint())
        self.viewport().setToolTip(self.remove_label if badge is not None else "")
        if index.isValid():
            self.viewport().update(self.visualRect(index))  # croix en surbrillance

    def leaveEvent(self, event):
        self.hover_pos = QPointF(-1, -1)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        index = self._on_badge(event.position().toPoint()) if event.button() == Qt.LeftButton else None
        if index is not None:  # clic sur la croix : on retire, sans ouvrir la vignette
            event.accept()
            self._remove(index)
            return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        index = self.indexAt(event.pos())
        if not (self.removable and index.isValid()):
            return
        menu = QMenu(self)
        menu.addAction(self.remove_label + "\tSuppr", lambda: self._remove(index))
        menu.exec(event.globalPos())

    def scroll_page(self, direction: int):
        bar = self.horizontalScrollBar()
        bar.setValue(bar.value() + direction * int(self.viewport().width() * 0.85))

    def wheelEvent(self, event):
        # Molette verticale : c'est la page qui défile. Défilement latéral (pavé tactile) ou Maj+molette : la bande.
        dx, dy = event.angleDelta().x(), event.angleDelta().y()
        if dx or event.modifiers() & Qt.ShiftModifier:
            bar = self.horizontalScrollBar()
            bar.setValue(bar.value() - (dx or dy))
            event.accept()
        else:
            event.ignore()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._emit(self.currentIndex())
        elif event.key() == Qt.Key_Delete:
            self._remove(self.currentIndex())
        else:
            super().keyPressEvent(event)


class GridView(QListView):
    """Mosaïque d'un onglet (Direct, Films, Séries) : vignettes sur plusieurs rangées, défilement vertical.
    Branchée sur le modèle de la liste (mêmes filtres) ; tile_fn donne la vignette d'une ligne."""

    def __init__(self, images, tile_fn):
        super().__init__()
        self.setViewMode(QListView.IconMode)
        self.setFlow(QListView.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setUniformItemSizes(True)
        self.setLayoutMode(QListView.Batched)  # 13 000 films : la 1re page s'affiche tout de suite
        self.setBatchSize(400)
        self.setSpacing(4)
        self.setDragEnabled(False)
        self.setFrameShape(QFrame.NoFrame)
        self.setVerticalScrollMode(QListView.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(40)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)  # largeur stable (pas d'aller-retour de mise en page)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setEditTriggers(QListView.NoEditTriggers)
        self.setMouseTracking(True)
        self.viewport().setAttribute(Qt.WA_Hover)
        self.setStyleSheet("QListView { background: transparent; }")
        self.delegate = TileDelegate(images, 150, True, self, tile_fn=tile_fn)
        self.setItemDelegate(self.delegate)

    def set_mode(self, poster: bool):
        """Affiches (films, séries) ou logos (chaînes)."""
        self.poster = poster
        self._fit()

    def _fit(self):
        """Largeur des vignettes : au moins 150 px (affiches) / 176 px (logos), agrandies pour que les colonnes
        remplissent toute la largeur (pas de vide à droite)."""
        poster = getattr(self, "poster", True)
        base, s = (150 if poster else 176), self.spacing()
        # QListView (IconMode) : un espacement avant la 1re vignette puis un après chacune
        avail = self.viewport().width() - s
        cols = max(1, avail // (base + 12 + s))
        width = max(base, avail // cols - 12 - s - 1)
        if (self.delegate.width, self.delegate.poster) != (width, poster):
            self.delegate.set_size(width, poster)
            self.scheduleDelayedItemsLayout()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        index = self.indexAt(event.position().toPoint())
        self.viewport().setCursor(Qt.PointingHandCursor if index.isValid() else Qt.ArrowCursor)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and self.currentIndex().isValid():
            self.clicked.emit(self.currentIndex())
        else:
            super().keyPressEvent(event)


class HomeSection(QFrame):
    openTab = Signal(str)
    seeAll = Signal(str)  # « Tout voir » : la liste complète (onglet, catégorie ★ Favoris / ◷ Vu récemment)
    tileClicked = Signal(str, object)
    tileRemoved = Signal(str, object)

    def __init__(self, kind: str, title: str, subtitle: str, images, poster: bool, remove_label: str, tab: str = "",
                 sub_band: bool = False, rows: int = 1, icon_name: str = ""):
        """kind : identifiant de la bande (signaux tileClicked / tileRemoved) ; tab : onglet ouvert par le titre ;
        sub_band : sous-bande d'un groupe (« En cours de lecture » > Films) : titre plus petit."""
        super().__init__()
        self.kind = kind
        self.tab = tab or kind
        self.setObjectName("section")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 2)
        lay.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(12)
        self.title_btn = QPushButton(title.upper() if sub_band else title)
        self.title_btn.setObjectName("subTitle" if sub_band else "sectionTitle")
        if icon_name:  # icône de l'onglet : violette sur les grands titres, grise sur les sous-bandes
            self.title_btn.setIcon(icon(icon_name, C["muted"] if sub_band else C["accent_hi"]))
            self.title_btn.setIconSize(QSize(18, 18) if sub_band else QSize(26, 26))
        self.title_btn.setCursor(Qt.PointingHandCursor)
        self.title_btn.setToolTip(f"Ouvrir l'onglet {title}")
        self.title_btn.clicked.connect(lambda: self.openTab.emit(self.tab))
        self.sub = QLabel(subtitle)
        self.sub.setObjectName("sectionSub")
        head.addWidget(self.title_btn, 0, Qt.AlignBottom)
        head.addWidget(self.sub, 0, Qt.AlignBottom)
        self.see_all = QPushButton("Tout voir  ›")
        self.see_all.setObjectName("seeAll")
        self.see_all.setCursor(Qt.PointingHandCursor)
        self.see_all.setFocusPolicy(Qt.NoFocus)
        self.see_all.clicked.connect(lambda: self.seeAll.emit(self.kind))
        self.see_all.hide()
        head.addWidget(self.see_all, 0, Qt.AlignBottom)
        head.addStretch(1)
        self.mosaic = Mosaic(images, poster, remove_label, rows=rows)
        self.mosaic.tileClicked.connect(lambda item: self.tileClicked.emit(self.kind, item))
        self.mosaic.tileRemoved.connect(lambda item: self.tileRemoved.emit(self.kind, item))
        # Flèches de défilement de la bande (affichées seulement si elle dépasse la largeur)
        self.arrows = []
        for text, direction, tip in (("‹", -1, "Précédents"), ("›", 1, "Suivants")):
            b = QPushButton(text)
            b.setObjectName("arrow")
            b.setToolTip(tip)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _=False, d=direction: self.mosaic.scroll_page(d))
            policy = b.sizePolicy()
            policy.setRetainSizeWhenHidden(True)  # place gardée : titres alignés entre deux bandes côte à côte
            b.setSizePolicy(policy)
            head.addWidget(b)
            self.arrows.append(b)
        self.mosaic.horizontalScrollBar().rangeChanged.connect(self._update_arrows)
        self.mosaic.horizontalScrollBar().valueChanged.connect(self._update_arrows)
        lay.addLayout(head)
        self.empty = QLabel()
        self.empty.setObjectName("empty")
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.empty.setMinimumHeight(54)
        lay.addWidget(self.mosaic)
        lay.addWidget(self.empty)
        self.base_subtitle = subtitle

    def _update_arrows(self, *_):
        bar = self.mosaic.horizontalScrollBar()
        overflow = bar.maximum() > 0 and self.mosaic.isVisible()
        self.arrows[0].setVisible(overflow)
        self.arrows[1].setVisible(overflow)
        self.arrows[0].setEnabled(bar.value() > bar.minimum())
        self.arrows[1].setEnabled(bar.value() < bar.maximum())

    def set_tiles(self, tiles: list[Tile], empty_text: str, total: int | None = None, see_all: bool = False):
        """total : nombre réel (l'accueil n'en montre qu'une partie) ; see_all : lien « Tout voir » affiché."""
        self.mosaic.set_tiles(tiles)
        self.see_all.setVisible(see_all and bool(tiles))
        self.empty.setText(empty_text)
        self.mosaic.setVisible(bool(tiles))
        self.empty.setVisible(not tiles)
        n = len(tiles) if total is None else total
        if self.base_subtitle:
            self.sub.setText(f"{self.base_subtitle} · {n}" if tiles else self.base_subtitle)
        else:
            self.sub.setText(str(n) if tiles else "")
        self._update_arrows()

    def showEvent(self, event):
        super().showEvent(event)
        self._update_arrows()


class SearchPage(QScrollArea):
    """Recherche : un grand champ, puis une bande de films et une bande de séries (même style que l'accueil)."""

    tileClicked = Signal(str, object)
    openTab = Signal(str)

    def __init__(self, images):
        super().__init__()
        self.setObjectName("homeScroll")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.verticalScrollBar().setSingleStep(40)
        content = QWidget()
        content.setObjectName("home")
        content.setAttribute(Qt.WA_StyledBackground, True)
        self.setWidget(content)
        col = QVBoxLayout(content)
        col.setContentsMargins(16, 16, 16, 16)
        col.setSpacing(12)
        self.field = QLineEdit()
        self.field.setObjectName("bigSearch")
        self.field.setPlaceholderText("Rechercher un film ou une série…")
        self.field.setClearButtonEnabled(True)
        self.field.setMaximumWidth(720)
        self.hint = QLabel()
        self.hint.setObjectName("sectionSub")
        col.addWidget(self.field)
        col.addWidget(self.hint)
        self.sections: dict[str, HomeSection] = {}
        for kind, title in (("movie", "Films"), ("series", "Séries")):
            sec = HomeSection(kind, title, "Résultats", images, True, "")
            sec.tileClicked.connect(self.tileClicked)
            sec.openTab.connect(self.openTab)
            self.sections[kind] = sec
            col.addWidget(sec)
        col.addStretch(1)

    def set_results(self, films: list | None, series: list | None, hint: str):
        """films / series : tuiles (None = rien à chercher : bandes masquées)."""
        self.hint.setText(hint)
        for kind, tiles, empty in (("movie", films, "Aucun film trouvé."), ("series", series, "Aucune série trouvée.")):
            sec = self.sections[kind]
            sec.setVisible(tiles is not None)
            if tiles is not None:
                sec.set_tiles(tiles, empty)
                sec.mosaic.horizontalScrollBar().setValue(0)


class HomePage(QScrollArea):
    """Accueil : une bande horizontale par onglet, empilées ; la page défile si l'écran est trop petit."""

    openTab = Signal(str)
    seeAll = Signal(str)
    tileClicked = Signal(str, object)
    tileRemoved = Signal(str, object)

    # (bande, onglet, titre, sous-titre, affiches, libellé « retirer », sous-bande, icône) ;
    # ("@", titre, icône, (sous-bandes…)) = groupe : Films et Séries côte à côte
    SECTIONS = (
        ("live", "live", "Direct", "Chaînes favorites", False, "Retirer des favoris", False, "live"),
        ("@", "En cours de lecture", "play", (
            ("movie", "movie", "Films", "", True, "Retirer des lectures en cours", True, "film"),
            ("series", "series", "Séries", "", True, "Retirer des lectures en cours", True, "series"))),
        ("@", "Favoris", "star", (
            ("movie_fav", "movie", "Films", "", True, "Retirer des favoris", True, "film"),
            ("series_fav", "series", "Séries", "", True, "Retirer des favoris", True, "series"))),
        ("replay", "replay", "Replays", "Chaînes favorites", False, "Retirer des favoris", False, "replay"),
    )

    def __init__(self, images):
        super().__init__()
        self.setObjectName("homeScroll")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.verticalScrollBar().setSingleStep(40)
        content = QWidget()
        content.setObjectName("home")
        content.setAttribute(Qt.WA_StyledBackground, True)
        self.setWidget(content)
        col = QVBoxLayout(content)
        col.setContentsMargins(28, 16, 20, 20)
        col.setSpacing(22)
        self.sections: dict[str, HomeSection] = {}
        def add(entry, rows=1):
            kind, tab, title, sub, poster, remove_label, sub_band, icon_name = entry
            sec = HomeSection(kind, title, sub, images, poster, remove_label, tab=tab, sub_band=sub_band, rows=rows,
                              icon_name=icon_name)
            sec.openTab.connect(self.openTab)
            sec.seeAll.connect(self.seeAll)
            sec.tileClicked.connect(self.tileClicked)
            sec.tileRemoved.connect(self.tileRemoved)
            self.sections[kind] = sec
            return sec

        for entry in self.SECTIONS:
            if entry[0] == "@":  # groupe : icône + titre + trait, puis Films | Séries (mosaïques de 2 lignes)
                hrow = QHBoxLayout()
                hrow.setSpacing(4)
                ic = QLabel()
                ic.setPixmap(icon(entry[2], C["accent_hi"]).pixmap(QSize(28, 28)))
                head = QLabel(entry[1])
                head.setObjectName("groupTitle")
                line = QFrame()
                line.setObjectName("groupLine")
                line.setFixedHeight(1)
                hrow.addWidget(ic)
                hrow.addWidget(head)
                hrow.addWidget(line, 1, Qt.AlignVCenter)
                col.addLayout(hrow)
                row = QHBoxLayout()
                row.setSpacing(24)
                for i, sub in enumerate(entry[3]):
                    if i:
                        sep = QFrame()
                        sep.setObjectName("groupSep")
                        sep.setFixedWidth(1)
                        row.addWidget(sep)
                    row.addWidget(add(sub, rows=2), 1, Qt.AlignTop)  # Films et Séries alignés en haut
                col.addLayout(row)
                continue
            col.addWidget(add(entry))
        col.addStretch(1)

    def refresh_images(self):
        for sec in self.sections.values():
            sec.mosaic.viewport().update()


# --------------------------------------------------------------------------- #
# Fiche détaillée en grand (films, séries, épisodes, programmes de replay)
# --------------------------------------------------------------------------- #
class DetailsPage(QScrollArea):
    POSTER = QSize(260, 390)

    def __init__(self):
        super().__init__()
        self.setObjectName("details")
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)  # le texte se replie, jamais de défilement latéral
        content = QWidget()
        content.setObjectName("detailsContent")
        content.setAttribute(Qt.WA_StyledBackground, True)
        self.setWidget(content)

        row = QHBoxLayout(content)
        row.setContentsMargins(32, 28, 32, 28)
        row.setSpacing(30)
        self.poster = QLabel()
        self.poster.setObjectName("poster")
        self.poster.setFixedSize(self.POSTER)
        self.poster.setAlignment(Qt.AlignCenter)
        row.addWidget(self.poster, 0, Qt.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(14)
        self.title = QLabel()
        self.title.setObjectName("detTitle")
        self.title.setWordWrap(True)
        self.title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.meta = QLabel()
        self.meta.setObjectName("detMeta")
        self.meta.setWordWrap(True)
        self.meta.setTextFormat(Qt.RichText)

        btns = QHBoxLayout()
        btns.setSpacing(10)
        self.play_btn = QPushButton()
        self.play_btn.setObjectName("primary")
        self.alt_btn = QPushButton()
        self.alt_btn.setObjectName("secondary")
        self.fav_btn = QPushButton()
        self.fav_btn.setObjectName("secondary")
        self.dl_btn = QPushButton()  # téléchargement sur le disque (film, épisode, saison d'une série)
        self.dl_btn.setObjectName("secondary")
        self.dl_btn.setIcon(icon("download", C["text"]))
        self.dl_btn.setIconSize(QSize(20, 20))
        for b in (self.play_btn, self.alt_btn, self.fav_btn, self.dl_btn):
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            btns.addWidget(b)
        btns.addStretch(1)

        self.plot = QLabel()
        self.plot.setObjectName("detPlot")
        self.plot.setWordWrap(True)
        self.plot.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.plot.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.plot.setTextFormat(Qt.RichText)
        self.plot.setMaximumWidth(820)  # lignes de longueur confortable à lire
        self.credits = QLabel()
        self.credits.setObjectName("detCredits")
        self.credits.setWordWrap(True)
        self.credits.setTextFormat(Qt.RichText)
        self.credits.setMaximumWidth(820)

        # Langues et sous-titres du fichier : un bouton par langue lance la lecture dans cette langue
        self.tracks = TracksBox()
        self.tracks.setMaximumWidth(820)

        col.addWidget(self.title)
        col.addWidget(self.meta)
        col.addLayout(btns)
        col.addWidget(self.tracks)
        col.addSpacing(6)
        col.addWidget(self.plot)
        col.addWidget(self.credits)
        # Série : saisons et épisodes directement sur la fiche (comme sur la TV et le téléphone)
        self.episodes = EpisodesBox()
        col.addSpacing(6)
        col.addWidget(self.episodes)
        col.addStretch(1)
        row.addLayout(col, 1)
        for w in (self.title, self.meta, self.plot, self.credits):
            w.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            w.setMinimumWidth(200)

    # ---- Langues / sous-titres ---------------------------------------------- #
    def set_tracks_message(self, text: str):
        self.tracks.set_message(text)

    def set_tracks(self, audio: list, subs: list, note: str = ""):
        self.tracks.set_entries(audio, subs, note)


class EpisodesBox(QWidget):
    """Saisons (boutons) et épisodes d'une série, sur la fiche. Une ligne d'épisode : vignette, titre, état (vu,
    en cours, durée), progression, ▶ et ⬇ ; clic = lecture, clic droit = menu (vu / non vu, depuis le début…)."""

    seasonChosen = Signal(object)  # saison (int) ou journée des replays (texte)

    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        self.head = QLabel("Épisodes")
        self.head.setObjectName("trackTitle")
        v.addWidget(self.head)
        self.season_flow = FlowLayout()
        box = QWidget()
        box.setLayout(self.season_flow)
        box.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        v.addWidget(box)
        self.rows = QVBoxLayout()
        self.rows.setSpacing(6)
        v.addLayout(self.rows)
        self.msg = QLabel()
        self.msg.setObjectName("detCredits")
        v.addWidget(self.msg)
        self._thumbs: list = []
        self.hide()

    def set_message(self, text: str):
        self._clear_rows()
        self.season_flow.clear()
        self.msg.setText(text)
        self.msg.setVisible(bool(text))
        self.setVisible(bool(text))

    def _clear_rows(self):
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._thumbs = []

    def set_episodes(self, seasons: list, current, rows: list, images, head: str = "Épisodes", chip=None):
        """seasons : saisons (ou journées des replays), current : celle affichée ; chip(s) : libellé du bouton.
        rows : [dict(title, sub, desc, progress, accent, logo (None : pas de vignette), play, menu, download)]."""
        self.msg.hide()
        self.head.setText(head)
        self.season_flow.clear()
        for s in seasons:
            b = QPushButton(chip(s) if chip else f"Saison {s}")
            b.setObjectName("langChip")
            b.setCheckable(True)
            b.setChecked(s == current)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _=False, s=s: self.seasonChosen.emit(s))
            self.season_flow.addWidget(b)
        self._clear_rows()
        self.images = images
        self.rows.setSpacing(4 if rows and rows[0].get("kind") == "program" else 6)
        for r in rows:
            w = _ProgramRow(r) if r.get("kind") == "program" else _EpisodeRow(r)
            self.rows.addWidget(w)
            if w.thumb is not None:
                self._thumbs.append((w.thumb, r.get("logo") or ""))
        self.refresh_images()
        self.show()

    def refresh_images(self):
        for label, url in self._thumbs:
            if label.pixmap() is not None and not label.pixmap().isNull():
                continue
            pm = self.images.pixmap(url, _EpisodeRow.THUMB.width(), _EpisodeRow.THUMB.height()) if url else None
            if pm is not None:
                label.setPixmap(pm)


class _ProgramRow(QFrame):
    """Programme de replay : heure de début en grand à gauche, titre, durée / état, deux lignes de résumé, ▶."""

    def __init__(self, r: dict):
        super().__init__()
        self.r = r
        self.thumb = None
        self.setObjectName("progRow")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_Hover, True)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(
            f"#progRow {{ background: {C['surface']}; border: 1px solid transparent; border-radius: 10px; }}"
            f"#progRow:hover {{ border-color: {C['accent']}; }}"
            + (f"#progRow {{ border-color: {C['accent']}; background: rgba(123, 102, 255, 40); }}" if r.get("playing") else ""))
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 10, 10, 10)
        h.setSpacing(16)
        times = QVBoxLayout()
        times.setSpacing(0)
        start = QLabel(r["start"])
        f = QFont(start.font())
        f.setPointSizeF(14)
        f.setBold(True)
        start.setFont(f)
        start.setStyleSheet(f"color: {C['accent_hi']}; background: transparent;")
        end = QLabel(r["end"])
        end.setStyleSheet(f"color: {C['muted']}; font-size: 9pt; background: transparent;")
        times.addWidget(start)
        times.addWidget(end)
        times.addStretch(1)
        tbox = QWidget()
        tbox.setLayout(times)
        tbox.setMinimumWidth(start.fontMetrics().horizontalAdvance("00:00") + 18)  # heure jamais rognée
        tbox.setStyleSheet("background: transparent;")
        h.addWidget(tbox, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        top = QHBoxLayout()
        top.setSpacing(8)
        title = QLabel(r["title"])
        title.setStyleSheet(f"color: {C['text']}; font-size: 11pt; font-weight: 600; background: transparent;")
        title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        title.setToolTip(r["title"])
        top.addWidget(title, 1)
        col.addLayout(top)
        meta = QLabel()
        meta.setTextFormat(Qt.RichText)
        bits = [r.get("duration", "")]
        if r.get("playing"):
            bits.append(f"<span style='color:{C['accent_hi']}'>▶ en lecture</span>")
        elif r.get("live"):
            bits.append(f"<span style='color:{C['live']}'>● en cours</span>")
        meta.setText("  ·  ".join(b for b in bits if b))
        meta.setStyleSheet(f"color: {C['muted']}; font-size: 9pt; background: transparent;")
        col.addWidget(meta)
        if r.get("desc"):
            desc = QLabel(r["desc"])
            desc.setWordWrap(True)
            desc.setStyleSheet(f"color: {C['muted']}; font-size: 9.5pt; background: transparent;")
            desc.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            desc.setToolTip(r.get("full_desc", ""))
            col.addSpacing(3)
            col.addWidget(desc)
        h.addLayout(col, 1)
        b = QPushButton()
        b.setObjectName("secondary")
        b.setIcon(icon("play", C["text"]))
        b.setIconSize(QSize(16, 16))
        b.setToolTip("Lire")
        b.setCursor(Qt.PointingHandCursor)
        b.setFocusPolicy(Qt.NoFocus)
        b.clicked.connect(lambda _=False: r["play"]())
        h.addWidget(b, 0, Qt.AlignVCenter)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.r["play"]()
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        self.r["menu"](event.globalPos())


class _EpisodeRow(QFrame):
    THUMB = QSize(128, 72)

    def __init__(self, r: dict):
        super().__init__()
        self.r = r
        self.setObjectName("drawerGroup")
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Clic : lire  ·  clic droit : vu / non vu, depuis le début…")
        h = QHBoxLayout(self)
        h.setContentsMargins(8, 8, 8, 8)
        h.setSpacing(12)
        thumb_box = QVBoxLayout()
        thumb_box.setSpacing(0)
        self.thumb = None
        if r.get("logo", "") is not None:  # programmes de replay : pas de vignette
            self.thumb = QLabel()
            self.thumb.setFixedSize(self.THUMB)
            self.thumb.setAlignment(Qt.AlignCenter)
            self.thumb.setStyleSheet(f"background: {C['surface2']}; border-radius: 6px;")
            thumb_box.addWidget(self.thumb)
        if r.get("progress", -1) >= 0:
            bar = QProgressBar()
            bar.setObjectName("bar")
            bar.setRange(0, 1000)
            bar.setTextVisible(False)
            bar.setFixedWidth(self.THUMB.width())
            bar.setValue(int(min(1.0, r["progress"]) * 1000))
            thumb_box.addSpacing(4)
            thumb_box.addWidget(bar)
        thumb_box.addStretch(1)
        if thumb_box.count() > 1:
            h.addLayout(thumb_box)
        col = QVBoxLayout()
        col.setSpacing(3)
        title = QLabel(r["title"])
        title.setObjectName("cardText")
        title.setWordWrap(True)
        title.setStyleSheet("font-weight: 600;")
        title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        sub = QLabel(r.get("sub", ""))
        sub.setObjectName("cardNote")
        if r.get("accent"):
            sub.setStyleSheet(f"color: {C['accent_hi']};")
        col.addWidget(title)
        col.addWidget(sub)
        if r.get("desc"):
            desc = QLabel(r["desc"])
            desc.setObjectName("cardNote")
            desc.setWordWrap(True)
            desc.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            col.addWidget(desc)
        col.addStretch(1)
        h.addLayout(col, 1)
        for name, tip, key in (("play", "Lire", "play"), ("download", "Télécharger l'épisode", "download")):
            if r.get(key) is None:
                continue
            b = QPushButton()
            b.setObjectName("secondary")
            b.setIcon(icon(name, C["text"]))
            b.setIconSize(QSize(18, 18))
            b.setToolTip(tip)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            b.clicked.connect(lambda _=False, f=r[key]: f())
            h.addWidget(b, 0, Qt.AlignVCenter)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.r["play"]()
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        self.r["menu"](event.globalPos())


class TracksBox(QWidget):
    """Langues et sous-titres d'un fichier : un bouton par piste (fiche des onglets, fiche de la recherche).
    Les boutons de langue lancent la lecture, ceux des sous-titres règlent seulement le choix (mémorisé)."""

    def __init__(self):
        super().__init__()
        tg = QGridLayout(self)
        tg.setContentsMargins(0, 4, 0, 0)
        tg.setHorizontalSpacing(14)
        tg.setVerticalSpacing(10)
        self.tracks_msg = QLabel()
        self.tracks_msg.setObjectName("detCredits")
        self.tracks_msg.setWordWrap(True)
        self.audio_title, self.sub_title = QLabel("Langue"), QLabel("Sous-titres")
        self.audio_flow, self.sub_flow = FlowLayout(), FlowLayout()
        for r, (lbl, flow) in enumerate(((self.audio_title, self.audio_flow), (self.sub_title, self.sub_flow))):
            lbl.setObjectName("trackTitle")
            box = QWidget()
            box.setLayout(flow)
            box.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            tg.addWidget(lbl, r, 0, Qt.AlignLeft | Qt.AlignTop)
            tg.addWidget(box, r, 1)
        tg.addWidget(self.tracks_msg, 2, 0, 1, 2)
        tg.setColumnStretch(1, 1)
        self.hide()

    def set_message(self, text: str):
        """Message seul (recherche en cours, rien trouvé…) ; texte vide = section masquée."""
        for flow in (self.audio_flow, self.sub_flow):
            flow.clear()
        for w in (self.audio_title, self.sub_title):
            w.hide()
        self.tracks_msg.setText(text)
        self.tracks_msg.setVisible(bool(text))
        self.setVisible(bool(text))

    def set_entries(self, audio: list, subs: list, note: str = ""):
        """audio / subs : [(libellé, choisi, infobulle, action)]."""
        for flow, title, entries, launch in ((self.audio_flow, self.audio_title, audio, True),
                                             (self.sub_flow, self.sub_title, subs, False)):
            flow.clear()
            title.setVisible(bool(entries))
            for text, chosen, tip, action in entries:
                b = QPushButton(("▶  " if launch else "") + text)
                b.setObjectName("langChip" if launch else "subChip")
                b.setCheckable(True)
                b.setChecked(chosen)
                b.setToolTip(tip)
                b.setCursor(Qt.PointingHandCursor)
                b.setFocusPolicy(Qt.NoFocus)
                b.clicked.connect(lambda _=False, a=action: a())
                flow.addWidget(b)
        self.tracks_msg.setText(note)
        self.tracks_msg.setVisible(bool(note))
        self.setVisible(bool(audio or subs or note))


class FlowLayout(QLayout):
    """Boutons côte à côte, renvoyés à la ligne quand la place manque."""

    def __init__(self, spacing: int = 8):
        super().__init__()
        self._items = []
        self._gap = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def clear(self):
        while self._items:
            w = self._items.pop().widget()
            if w is not None:
                w.hide()
                w.deleteLater()
        self.invalidate()

    def expandingDirections(self):
        return Qt.Orientations()

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._place(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._place(rect, apply=True)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        return size

    def _place(self, rect, apply: bool) -> int:
        x, y, line_h = rect.x(), rect.y(), 0
        for it in self._items:
            hint = it.sizeHint()
            if x + hint.width() > rect.right() + 1 and line_h:
                x, y = rect.x(), y + line_h + self._gap
                line_h = 0
            if apply:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + self._gap
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y()


class NavBar(QTabBar):
    """Onglets du bandeau : icône + libellé ; l'icône de l'onglet actif prend la couleur d'accent."""

    def __init__(self, icon_names: list[str]):
        super().__init__()
        self.icon_names = icon_names
        self._painted = None

    def paintEvent(self, event):
        # L'onglet actif change aussi sans signal (accueil, retour…) : on recolore au dessin
        state = (self.currentIndex(), tuple(self.isTabEnabled(i) for i in range(self.count())))
        if state != self._painted:
            self._painted = state
            for i, name in enumerate(self.icon_names[:self.count()]):
                color = C["accent_hi"] if i == state[0] else (C["muted"] if state[1][i] else C["line"])
                self.setTabIcon(i, icon(name, color))
        super().paintEvent(event)
