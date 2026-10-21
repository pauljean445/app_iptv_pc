"""Petits composants de l'interface : modèle de liste, zone vidéo, barre de progression,
fenêtre de connexion et barres flottantes du plein écran."""
from PySide6.QtCore import (QAbstractListModel, QEasingCurve, QMimeData, QModelIndex, QPoint, QPropertyAnimation,
                            QRect, QSize, Qt, QTimer, Signal)
from PySide6.QtGui import QColor, QFont, QIcon, QPainter
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QMessageBox,
    QPushButton,
    QButtonGroup,
    QRadioButton,
    QSizePolicy,
    QSlider,
    QToolButton,
    QStyle,
    QStyledItemDelegate,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from . import config, ui
from .sources import playlist


# --------------------------------------------------------------------------- #
# Modèle de liste
# --------------------------------------------------------------------------- #
class ItemModel(QAbstractListModel):
    MIME = "application/x-iptvplayer-row"

    def __init__(self, label_fn, icon_fn):
        super().__init__()
        self.items: list[playlist.Item] = []
        self.label_fn = label_fn
        self.icon_fn = icon_fn
        self.reorderable = False  # lignes déplaçables à la souris (★ Favoris)

    def flags(self, index):
        f = super().flags(index)
        if self.reorderable:
            f |= Qt.ItemIsDragEnabled if index.isValid() else Qt.ItemIsDropEnabled  # dépôt entre les lignes
        return f

    def supportedDropActions(self):
        return Qt.MoveAction

    def mimeTypes(self):
        return [self.MIME]

    def mimeData(self, indexes):
        data = QMimeData()
        data.setData(self.MIME, str(indexes[0].row()).encode() if indexes else b"")
        return data

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.items)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        it = self.items[index.row()]
        if role == Qt.DisplayRole:
            return self.label_fn(it)
        if role == Qt.DecorationRole:
            return self.icon_fn(it)
        if role == Qt.ToolTipRole:
            return f"{it.name}\n{it.group}" if it.group else it.name
        return None

    def set_items(self, items):
        self.beginResetModel()
        self.items = items
        self.endResetModel()

    def item(self, row: int) -> playlist.Item:
        return self.items[row]

    def refresh(self):
        if self.items:
            self.dataChanged.emit(self.index(0), self.index(len(self.items) - 1))


class ItemList(QListView):
    """Liste des entrées. Quand le modèle est « reorderable », une ligne se déplace par glisser-déposer :
    moved(ligne, position d'insertion) ; c'est à l'appelant de changer l'ordre puis de recharger le modèle."""
    moved = Signal(int, int)

    def set_reorderable(self, on: bool):
        self.model().reorderable = on
        self.setDragDropMode(QListView.InternalMove if on else QListView.NoDragDrop)
        self.setDefaultDropAction(Qt.MoveAction)

    def dropEvent(self, event):
        model = self.model()
        if event.source() is not self or not model.reorderable or not event.mimeData().hasFormat(model.MIME):
            event.ignore()
            return
        row = int(bytes(event.mimeData().data(model.MIME)).decode() or -1)
        pos = event.position().toPoint()
        idx = self.indexAt(pos)
        dest = model.rowCount() if not idx.isValid() else \
            idx.row() + (pos.y() > self.visualRect(idx).center().y())
        # Accepté sans rien retirer du modèle (il ne sait pas supprimer de lignes) ; le déplacement se fait
        # une fois le glisser-déposer terminé, car l'appelant recharge la liste.
        event.setDropAction(Qt.MoveAction)
        event.accept()
        self.stopAutoScroll()
        self.setState(QListView.NoState)
        self.viewport().update()
        if row >= 0:
            QTimer.singleShot(0, lambda: self.moved.emit(row, dest))


# --------------------------------------------------------------------------- #
# Choix de la catégorie
# --------------------------------------------------------------------------- #
class GroupCombo(QComboBox):
    """Liste des catégories : s'ouvre juste sous le champ (14 lignes au plus), coins arrondis, chevron."""

    def __init__(self):
        super().__init__()
        self.setObjectName("groups")
        self.setCursor(Qt.PointingHandCursor)
        self.setMaxVisibleItems(14)
        # Délégué « stylé » : sans lui, la feuille de style ne s'applique pas aux lignes (hauteur, arrondi)
        self.setItemDelegate(QStyledItemDelegate(self))
        self.view().setTextElideMode(Qt.ElideRight)
        self.view().setVerticalScrollMode(QListView.ScrollPerPixel)
        popup = self.view().parentWidget()  # cadre de la liste ouverte : transparent autour des coins arrondis
        popup.setObjectName("groupsPopup")
        popup.setWindowFlags(popup.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        popup.setAttribute(Qt.WA_TranslucentBackground)

    def showPopup(self):
        super().showPopup()
        self.view().setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)  # Qt la masque dans ce mode
        popup = self.view().parentWidget()
        below = self.mapToGlobal(self.rect().bottomLeft()).y()
        if popup.y() >= below - 2:  # ouverte vers le bas : petit espace sous le champ
            popup.move(popup.x(), below + 5)
        self.update()

    def hidePopup(self):
        super().hidePopup()
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        open_ = self.view().isVisible()
        side = 16
        pm = ui.icon("chevron_down", ui.C["accent_hi"] if open_ else ui.C["muted"]).pixmap(
            QSize(side, side), self.devicePixelRatioF())
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        x, y = self.width() - side - 13, (self.height() - side) // 2
        if open_:  # chevron retourné quand la liste est ouverte
            p.translate(x + side / 2, y + side / 2)
            p.rotate(180)
            p.translate(-(x + side / 2), -(y + side / 2))
        p.drawPixmap(x, y, side, side, pm)
        p.end()


# --------------------------------------------------------------------------- #
# Zone vidéo (VLC dessine dedans)
# --------------------------------------------------------------------------- #
class VideoFrame(QFrame):
    doubleClicked = Signal()

    def __init__(self):
        super().__init__()
        self.setStyleSheet("background-color: black;")
        self.setMinimumSize(320, 180)
        self.setAttribute(Qt.WA_NativeWindow, True)
        self.idle = True  # rien en lecture : on affiche le logo
        self.message = ""  # ex. « Diffusion sur Salle TV »
        self.logo = QIcon(config.asset_path("icon.ico"))

    def set_idle(self, idle: bool, message: str = ""):
        if idle != self.idle or message != self.message:
            self.idle = idle
            self.message = message
            self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self.idle or self.logo.isNull():
            return
        side = max(48, min(150, self.height() // 3))
        title_h, gap = 34, 14
        top = (self.height() - side - gap - title_h) // 2
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        pm = self.logo.pixmap(QSize(side, side), self.devicePixelRatioF())
        p.drawPixmap((self.width() - side) // 2, top, side, side, pm)
        f = QFont(self.font())
        f.setPointSizeF(f.pointSizeF() * 1.6)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#E9E6FF"))
        p.drawText(0, top + side + gap, self.width(), title_h, Qt.AlignHCenter | Qt.AlignTop, "IPTV Player")
        if self.message:
            f.setBold(False)
            f.setPointSizeF(f.pointSizeF() * 0.7)
            p.setFont(f)
            p.setPen(QColor(ui.C["accent_hi"]))
            p.drawText(0, top + side + gap + title_h + 6, self.width(), 30, Qt.AlignHCenter | Qt.AlignTop,
                       self.message)
        p.end()

    def mouseDoubleClickEvent(self, event):
        self.doubleClicked.emit()


class SeekSlider(QSlider):
    """Barre de progression : un clic saute directement à la position."""

    seekRequested = Signal(float)

    def __init__(self, orientation):
        super().__init__(orientation)
        self.dragging = False

    def _value_at(self, x):
        return QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), int(x), max(1, self.width()))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.dragging = True
            self.setValue(self._value_at(event.position().x()))
            event.accept()

    def mouseMoveEvent(self, event):
        if self.dragging:
            self.setValue(self._value_at(event.position().x()))
            event.accept()

    def mouseReleaseEvent(self, event):
        if self.dragging:
            self.dragging = False
            self.setValue(self._value_at(event.position().x()))
            self.seekRequested.emit(self.value() / max(1, self.maximum()))
            event.accept()


# --------------------------------------------------------------------------- #
# Fenêtre de connexion
# --------------------------------------------------------------------------- #
class ConnectionDialog(QDialog):
    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Connexion IPTV")
        self.setMinimumWidth(500)

        self.tabs = QTabWidget()

        # Onglet 1 : Xtream Codes
        xt = QWidget()
        form = QFormLayout(xt)
        self.server = QLineEdit(cfg.get("server", ""))
        self.server.setPlaceholderText("http://mon-fournisseur.tld:8080")
        self.username = QLineEdit(cfg.get("username", ""))
        self.password = QLineEdit(cfg.get("password", ""))
        self.password.setEchoMode(QLineEdit.Password)
        self.fmt = QComboBox()
        self.fmt.addItems(["ts", "m3u8"])
        self.fmt.setCurrentText(cfg.get("stream_format", "ts"))
        form.addRow("Serveur :", self.server)
        form.addRow("Utilisateur :", self.username)
        form.addRow("Mot de passe :", self.password)
        form.addRow("Format du flux :", self.fmt)
        self.tabs.addTab(xt, "Xtream Codes")

        # Onglet 2 : URL M3U
        ut = QWidget()
        uform = QFormLayout(ut)
        self.url = QLineEdit(cfg.get("url", ""))
        self.url.setPlaceholderText("http://.../get.php?username=...&password=...&type=m3u_plus")
        uform.addRow("URL de la playlist :", self.url)
        self.tabs.addTab(ut, "URL M3U")

        # Onglet 3 : fichier local
        ft = QWidget()
        fl = QHBoxLayout(ft)
        self.file = QLineEdit(cfg.get("file", ""))
        browse = QPushButton("Parcourir…")
        browse.clicked.connect(self._browse)
        fl.addWidget(QLabel("Fichier :"))
        fl.addWidget(self.file, 1)
        fl.addWidget(browse)
        self.tabs.addTab(ft, "Fichier M3U")

        self.tabs.setCurrentIndex({"xtream": 0, "url": 1, "file": 2}.get(cfg.get("mode"), 0))

        self.remember = QCheckBox("Mémoriser la connexion (stockée en clair sur ce PC)")
        self.remember.setChecked(bool(cfg.get("remember", True)))

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Se connecter")
        buttons.button(QDialogButtonBox.Cancel).setText("Annuler")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        layout.addWidget(self.remember)
        layout.addWidget(buttons)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choisir une playlist", "", "Playlists (*.m3u *.m3u8);;Tous les fichiers (*)"
        )
        if path:
            self.file.setText(path)

    def values(self) -> dict:
        return {
            "mode": ["xtream", "url", "file"][self.tabs.currentIndex()],
            "server": self.server.text().strip(),
            "username": self.username.text().strip(),
            "password": self.password.text(),
            "stream_format": self.fmt.currentText(),
            "url": self.url.text().strip(),
            "file": self.file.text().strip(),
            "remember": self.remember.isChecked(),
        }

    def _on_accept(self):
        v = self.values()
        mode = v["mode"]
        incomplete = (
            (mode == "xtream" and not (v["server"] and v["username"] and v["password"]))
            or (mode == "url" and not v["url"])
            or (mode == "file" and not v["file"])
        )
        if incomplete:
            QMessageBox.warning(self, "Champs manquants", "Merci de remplir tous les champs de l'onglet.")
            return
        self.accept()


class CardDialog(QDialog):
    """Fenêtre au style du menu ☰ : panneau arrondi sans barre de titre, avec titre et croix de fermeture.
    Se déplace en la faisant glisser. Le contenu va dans self.body ; add_buttons() ajoute la rangée du bas."""

    def __init__(self, parent, title: str, width: int = 440):
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowTitle(title)
        self._drag = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        panel = QFrame()
        panel.setObjectName("drawer")
        outer.addWidget(panel)
        self.body = QVBoxLayout(panel)
        self.body.setContentsMargins(20, 14, 16, 20)
        self.body.setSpacing(14)
        head = QHBoxLayout()
        label = QLabel(title)
        label.setObjectName("drawerTitle")
        close = QToolButton()
        close.setObjectName("drawerClose")
        close.setIcon(ui.icon("close", ui.C["muted"]))
        close.setIconSize(QSize(18, 18))
        close.setCursor(Qt.PointingHandCursor)
        close.setFocusPolicy(Qt.NoFocus)
        close.clicked.connect(self.reject)
        head.addWidget(label)
        head.addStretch(1)
        head.addWidget(close)
        self.body.addLayout(head)
        self.setFixedWidth(width)

    def add_text(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("cardText")
        label.setWordWrap(True)
        label.setTextFormat(Qt.RichText)
        self.body.addWidget(label)
        return label

    def add_buttons(self, *specs) -> list:
        """specs : (texte, style, action) ; style = "primary", "secondary" ou "danger". Le dernier est
        le bouton par défaut (touche Entrée)."""
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addStretch(1)
        buttons = []
        for text, style, action in specs:
            b = QPushButton(text)
            b.setObjectName(style)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(action)
            row.addWidget(b)
            buttons.append(b)
        buttons[-1].setDefault(True)
        self.body.addSpacing(4)
        self.body.addLayout(row)
        return buttons

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._drag is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, event):
        self._drag = None


def confirm(parent, title: str, text: str, ok: str, danger: bool = False) -> bool:
    """Question oui / non au style du menu ☰ (à la place de QMessageBox.question)."""
    dlg = CardDialog(parent, title)
    dlg.add_text(text)
    dlg.add_buttons(("Annuler", "secondary", dlg.reject), (ok, "danger" if danger else "primary", dlg.accept))
    return dlg.exec() == QDialog.Accepted


class AccountDialog(CardDialog):
    """Compte du foyer : connexion (email, mot de passe) ou, si ce PC est connecté, déconnexion.

    sign_in(email, password, on_ok, on_error) est fourni par la fenêtre principale (appel réseau en
    arrière-plan) ; sign_out() déconnecte ce PC. Le compte est obligatoire : sans connexion, on quitte.
    """

    def __init__(self, parent, email: str, signed_in: bool, sign_in, sign_out, notice: str = ""):
        super().__init__(parent, "Compte du foyer")
        self._sign_in, self._sign_out = sign_in, sign_out
        if signed_in:
            box = QFrame()
            box.setObjectName("drawerGroup")
            row = QHBoxLayout(box)
            row.setContentsMargins(12, 10, 12, 10)
            row.setSpacing(12)
            icon = QLabel()
            icon.setPixmap(ui.icon("account", ui.C["accent_hi"]).pixmap(QSize(22, 22), self.devicePixelRatioF()))
            who = QLabel(f"<span style='color:{ui.C['muted']}'>Connecté au compte</span><br><b>{email}</b>")
            who.setObjectName("cardText")
            row.addWidget(icon)
            row.addWidget(who, 1)
            self.body.addWidget(box)
            self.add_text("Les profils, favoris, reprises de lecture et choix de langue sont partagés avec les "
                          "autres appareils du foyer.")
            self.add_buttons(("Se déconnecter", "secondary", self._on_sign_out), ("Fermer", "primary", self.reject))
            return
        self.add_text("Connecte-toi au compte de ton foyer pour utiliser l'appli. Les profils, favoris, reprises "
                      "de lecture et choix de langue sont partagés avec la TV et les autres PC.")
        self.email = self._field("EMAIL", email, "adresse email du compte")
        self.password = self._field("MOT DE PASSE", "", "")
        self.password.setEchoMode(QLineEdit.Password)
        self.status = QLabel()
        self.status.setObjectName("notice")
        self.status.setWordWrap(True)
        self.status.setVisible(False)
        self.body.addWidget(self.status)
        note = QLabel("Le mot de passe n'est pas enregistré : ce PC garde seulement une session, chiffrée par "
                      "Windows.")
        note.setObjectName("cardNote")
        note.setWordWrap(True)
        self.body.addWidget(note)
        _, self.ok = self.add_buttons(("Quitter", "secondary", self.reject),
                                      ("Se connecter", "primary", self._on_sign_in))
        (self.password if email else self.email).setFocus()
        if notice:
            self._show(notice, error=True)

    def _field(self, label: str, value: str, placeholder: str) -> QLineEdit:
        box = QVBoxLayout()
        box.setSpacing(6)
        head = QLabel(label)
        head.setObjectName("fieldLabel")
        edit = QLineEdit(value)
        edit.setObjectName("field")
        edit.setPlaceholderText(placeholder)
        box.addWidget(head)
        box.addWidget(edit)
        self.body.addLayout(box)
        return edit

    def _on_sign_in(self):
        email, password = self.email.text().strip(), self.password.text()
        if not email or not password:
            self._show("Merci de saisir l'email et le mot de passe.", error=True)
            return
        self.ok.setEnabled(False)
        self.ok.setText("Connexion…")
        self.status.setVisible(False)

        def failed(msg):
            self.ok.setEnabled(True)
            self.ok.setText("Se connecter")
            self._show(f"Connexion impossible : {msg}.", error=True)
            self.password.selectAll()
            self.password.setFocus()

        self._sign_in(email, password, self.accept, failed)

    def _on_sign_out(self):
        if confirm(self, "Se déconnecter",
                   "Déconnecter ce PC du compte du foyer ? Il faudra se reconnecter pour continuer à utiliser "
                   "l'appli. Les données présentes sur ce PC sont conservées.", "Se déconnecter", danger=True):
            self._sign_out()
            self.accept()

    def _show(self, text: str, error: bool = False):
        self.status.setText(text)
        self.status.setProperty("error", error)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.status.setVisible(True)


# --------------------------------------------------------------------------- #
# Barre de contrôle flottante (plein écran)
# --------------------------------------------------------------------------- #
class ProfileDialog(QDialog):
    """Création ou modification d'un profil : nom, couleur et, à la création, la source IPTV."""

    def __init__(self, parent=None, name: str = "", color: str = "", copy_from: str | None = None):
        super().__init__(parent)
        creating = copy_from is not None
        self.setWindowTitle("Nouveau profil" if creating else "Modifier le profil")
        self.setMinimumWidth(420)
        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        form = QFormLayout()
        self.name = QLineEdit(name)
        self.name.setMaxLength(20)
        self.name.setPlaceholderText("Prénom, « Enfants »…")
        form.addRow("Nom :", self.name)
        colors = QHBoxLayout()
        colors.setSpacing(8)
        self.colors = QButtonGroup(self)
        for c in config.PROFILE_COLORS:
            b = QPushButton()
            b.setObjectName("colorChip")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(f"QPushButton#colorChip {{ background: {c}; }}")
            b.setProperty("color", c)
            b.setChecked(c == (color or config.PROFILE_COLORS[0]))
            self.colors.addButton(b)
            colors.addWidget(b)
        colors.addStretch(1)
        form.addRow("Couleur :", colors)
        lay.addLayout(form)
        self.same = None
        if creating:
            self.same = QRadioButton(f"Même IPTV que le profil « {copy_from} »")
            other = QRadioButton("Une autre IPTV (identifiants demandés à l'ouverture du profil)")
            self.same.setChecked(True)
            lay.addWidget(QLabel("Source IPTV :"))
            lay.addWidget(self.same)
            lay.addWidget(other)
            note = QLabel("Favoris, lectures en cours et « Vu récemment » sont propres à chaque profil.")
            note.setObjectName("countLabel")
            note.setWordWrap(True)
            lay.addWidget(note)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.button(QDialogButtonBox.Ok).setText("Créer" if creating else "Enregistrer")
        box.button(QDialogButtonBox.Cancel).setText("Annuler")
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        ok = box.button(QDialogButtonBox.Ok)
        self.name.textChanged.connect(lambda t: ok.setEnabled(bool(t.strip())))
        ok.setEnabled(bool(name.strip()))
        lay.addWidget(box)

    def values(self) -> tuple[str, str, bool]:
        """(nom, couleur, même source IPTV que le profil en cours)."""
        b = self.colors.checkedButton()
        color = b.property("color") if b is not None else config.PROFILE_COLORS[0]
        return self.name.text().strip(), color, bool(self.same is None or self.same.isChecked())


class ProfilePicker(QDialog):
    """« Qui regarde ? » : choix du profil au démarrage."""

    def __init__(self, profiles: list[dict], current: str):
        super().__init__()
        self.setWindowTitle("IPTV Player")
        self.chosen = current
        lay = QVBoxLayout(self)
        lay.setContentsMargins(40, 32, 40, 32)
        lay.setSpacing(24)
        title = QLabel("Qui regarde ?")
        title.setObjectName("pickerTitle")
        title.setAlignment(Qt.AlignCenter)
        lay.addWidget(title)
        row = QHBoxLayout()
        row.setSpacing(16)
        row.addStretch(1)
        for prof in profiles:
            b = QToolButton()
            b.setObjectName("profileTile")
            b.setIcon(ui.avatar(prof["name"], prof["color"], 192))
            b.setIconSize(QSize(96, 96))
            b.setText(prof["name"])
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, pid=prof["id"]: self._choose(pid))
            row.addWidget(b)
            if prof["id"] == current:
                b.setFocus()
        row.addStretch(1)
        lay.addLayout(row)

    def _choose(self, pid: str):
        self.chosen = pid
        self.accept()


class SideMenu(QWidget):
    """Menu ☰ : panneau qui glisse depuis la droite, sous le bandeau.

    quick : [(icône, texte, action)] en tuiles ; groups : [[(icône, texte, touches, action)]] en listes.
    Fenêtre « popup » : elle passe au-dessus de la vidéo (fenêtre native de VLC) et se ferme d'un clic
    à côté ou avec Échap.
    """

    WIDTH = 340

    def __init__(self, parent, quick, groups):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.closed_at = 0.0
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        panel = QFrame()
        panel.setObjectName("drawer")
        outer.addWidget(panel)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(14, 12, 14, 14)
        lay.setSpacing(12)
        head = QHBoxLayout()
        title = QLabel("Menu")
        title.setObjectName("drawerTitle")
        close = QToolButton()
        close.setObjectName("drawerClose")
        close.setIcon(ui.icon("close", ui.C["muted"]))
        close.setIconSize(QSize(18, 18))
        close.setCursor(Qt.PointingHandCursor)
        close.clicked.connect(self.close)
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(close)
        lay.addLayout(head)
        tiles = QGridLayout()
        tiles.setSpacing(8)
        for i, (icon, text, action) in enumerate(quick):
            b = QToolButton()
            b.setObjectName("quickTile")
            b.setIcon(ui.icon(icon, ui.C["accent_hi"]))
            b.setIconSize(QSize(22, 22))
            b.setText(text)
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, a=action: self._run(a))
            tiles.addWidget(b, 0, i)
        lay.addLayout(tiles)
        for rows in groups:
            box = QFrame()
            box.setObjectName("drawerGroup")
            gl = QVBoxLayout(box)
            gl.setContentsMargins(4, 4, 4, 4)
            gl.setSpacing(0)
            for icon, text, keys, action in rows:
                b = QPushButton(text)
                b.setObjectName("drawerRow")
                b.setIcon(ui.icon(icon, ui.C["muted"]))
                b.setIconSize(QSize(18, 18))
                b.setCursor(Qt.PointingHandCursor)
                b.clicked.connect(lambda _=False, a=action: self._run(a))
                if keys:
                    rl = QHBoxLayout(b)
                    rl.setContentsMargins(0, 0, 10, 0)
                    rl.addStretch(1)
                    k = QLabel(keys)
                    k.setObjectName("kbd")
                    k.setAttribute(Qt.WA_TransparentForMouseEvents)
                    k.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
                    rl.addWidget(k, 0, Qt.AlignVCenter)
                gl.addWidget(b)
            lay.addWidget(box)
        self.setFixedWidth(self.WIDTH)

    def _run(self, action):
        self.close()
        QTimer.singleShot(0, action)  # après la fermeture du panneau (une fenêtre peut s'ouvrir)

    def open_beside(self, window, top_widget):
        """Ouvre le panneau contre le bord droit de la fenêtre, sous top_widget (le bandeau)."""
        self.adjustSize()
        right = window.mapToGlobal(QPoint(window.width(), 0)).x()
        y = top_widget.mapToGlobal(QPoint(0, top_widget.height())).y() + 8
        end = QPoint(right - self.width() - 10, y)
        self.move(end + QPoint(40, 0))
        self.setWindowOpacity(0.0)
        self.show()
        self._anims = []
        for prop, a, b in ((b"pos", end + QPoint(40, 0), end), (b"windowOpacity", 0.0, 1.0)):
            anim = QPropertyAnimation(self, prop, self)
            anim.setDuration(170)
            anim.setStartValue(a)
            anim.setEndValue(b)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.start()
            self._anims.append(anim)

    def closeEvent(self, event):
        import time
        self.closed_at = time.time()  # le clic sur ☰ qui a fermé le panneau ne doit pas le rouvrir
        super().closeEvent(event)


class ShortcutsDialog(QDialog):
    """Liste des raccourcis clavier, par groupe : [(titre, [(action, touches)])]."""

    def __init__(self, parent, groups):
        super().__init__(parent)
        self.setWindowTitle("Raccourcis clavier")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 22)
        lay.setSpacing(36)
        half = (len(groups) + 1) // 2
        for col_groups in (groups[:half], groups[half:]):
            col = QGridLayout()
            col.setHorizontalSpacing(18)
            col.setVerticalSpacing(7)
            r = 0
            for title, rows in col_groups:
                t = QLabel(title.upper())
                t.setObjectName("shortcutGroup")
                col.addWidget(t, r, 0, 1, 2)
                r += 1
                for text, keys in rows:
                    col.addWidget(QLabel(text), r, 0)
                    k = QLabel(keys)
                    k.setObjectName("kbd")
                    col.addWidget(k, r, 1, Qt.AlignLeft)
                    r += 1
            col.setRowStretch(r, 1)
            lay.addLayout(col)


class ManageProfilesDialog(QDialog):
    """Gérer les profils : modifier, changer la source IPTV, réinitialiser, supprimer ; « Qui regarde ? ».

    Les actions sont fournies par la fenêtre principale : on_edit(pid), on_source(pid), on_reset(pid),
    on_delete(pid) (qui retournent True si la liste doit être redessinée), on_ask(bool).
    """

    def __init__(self, parent, cfg, current, on_edit, on_source, on_reset, on_delete, on_ask):
        super().__init__(parent)
        self.setWindowTitle("Gérer les profils")
        self.setMinimumWidth(640)
        self.cfg, self.current = cfg, current
        self.actions = on_edit, on_source, on_reset, on_delete
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(14)
        self.rows = QVBoxLayout()
        self.rows.setSpacing(6)
        lay.addLayout(self.rows)
        self.ask = QCheckBox("Demander « Qui regarde ? » au démarrage (avec plusieurs profils)")
        self.ask.setChecked(bool(cfg.get("ask_profile", True)))
        self.ask.toggled.connect(on_ask)
        lay.addWidget(self.ask)
        box = QDialogButtonBox(QDialogButtonBox.Close)
        box.button(QDialogButtonBox.Close).setText("Fermer")
        box.rejected.connect(self.reject)
        lay.addWidget(box)
        self.refresh()

    def refresh(self):
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        single = len(self.cfg["profiles"]) < 2
        for prof in self.cfg["profiles"]:
            row = QFrame()
            row.setObjectName("drawerGroup")
            h = QHBoxLayout(row)
            h.setContentsMargins(10, 8, 8, 8)
            h.setSpacing(10)
            av = QLabel()
            av.setPixmap(ui.avatar(prof["name"], prof["color"]).pixmap(QSize(36, 36), self.devicePixelRatioF()))
            name = QLabel(prof["name"] + ("  ·  en cours" if prof["id"] == self.current else ""))
            h.addWidget(av)
            h.addWidget(name, 1)
            for (label, icon), action in zip((("Modifier", "edit"), ("Source IPTV", "plug"),
                                              ("Réinitialiser", "reload"), ("Supprimer", "trash")), self.actions):
                if label == "Supprimer" and single:
                    continue
                b = QPushButton(label)
                b.setObjectName("drawerRow")
                b.setIcon(ui.icon(icon, ui.C["muted"]))
                b.setCursor(Qt.PointingHandCursor)
                b.clicked.connect(lambda _=False, a=action, pid=prof["id"]: self._do(a, pid))
                h.addWidget(b)
            self.rows.addWidget(row)

    def _do(self, action, pid):
        if action(pid):
            self.refresh()


class ControlsOverlay(QWidget):
    """Fenêtre sans bordure posée sur le bas de la vidéo. VLC dessine dans une fenêtre native
    sur laquelle un widget ordinaire ne peut pas s'afficher : il faut une fenêtre à part.
    Elle ne prend jamais le focus, pour que les raccourcis clavier restent actifs."""

    STYLE = """
        #panel { background: rgba(11, 9, 24, 228); border: 1px solid rgba(157, 140, 255, 70);
                 border-radius: 16px; }
        #playerBar, #playerTop { background: transparent; border: none; }
    """

    def __init__(self, parent):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setStyleSheet(self.STYLE)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.panel = QFrame()
        self.panel.setObjectName("panel")
        lay.addWidget(self.panel)
        self.inner = QVBoxLayout(self.panel)
        self.inner.setContentsMargins(14, 8, 14, 8)

    def place_over(self, video: QWidget, where: str = "bottom"):
        """Centre la barre en haut ou en bas de la zone vidéo."""
        top_left = video.mapToGlobal(video.rect().topLeft())
        width = max(320, min(video.width() - 48, 1400))
        height = self.sizeHint().height()
        screen = video.screen()
        if where == "top":
            y = top_left.y() + 24
            if screen is not None:
                y = max(y, screen.geometry().top() + 24)
        else:
            y = top_left.y() + video.height() - height - 28
            if screen is not None:  # toujours entièrement dans l'écran
                y = min(y, screen.geometry().bottom() - height - 28)
        geo = QRect(top_left.x() + (video.width() - width) // 2, y, width, height)
        if geo != self.geometry():
            self.setGeometry(geo)
