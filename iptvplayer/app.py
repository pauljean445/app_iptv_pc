"""Fenêtre principale et démarrage d'IPTV Player (interface PySide6, lecture libVLC). Lancé par main.py."""
import os
from pathlib import Path
import sys
import threading
import time
import traceback
import unicodedata
from datetime import datetime

from . import __version__, config

# --- Journal et affichage des erreurs ---------------------------------------
# Dans l'exécutable (mode --windowed) il n'y a pas de console : sans ceci, une erreur
# au démarrage fait disparaître l'appli silencieusement. On écrit un journal et on affiche l'erreur.
LOG_FILE = config.config_dir() / "iptvplayer.log"


def _setup_logging():
    if getattr(sys, "frozen", False) or sys.stdout is None or sys.stderr is None:
        try:
            config.config_dir().mkdir(parents=True, exist_ok=True)
            log = open(LOG_FILE, "w", encoding="utf-8", buffering=1)
        except OSError:
            log = open(os.devnull, "w")
        sys.stdout = log
        sys.stderr = log


def _fatal(text: str) -> None:
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, text, "IPTV Player - erreur", 0x10)
            return
        except Exception:
            pass
    print(text, file=sys.stderr)


def _excepthook(exc_type, exc, tb):
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    print(text, file=sys.stderr)
    _fatal(f"Erreur inattendue :\n\n{text[-1500:]}\n\nJournal : {LOG_FILE}")


_setup_logging()
sys.excepthook = _excepthook

# libVLC ne sait pas s'intégrer dans une fenêtre Wayland : on force X11 (XWayland) sous Linux.
if sys.platform.startswith("linux"):
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

from PySide6.QtCore import QEvent, QObject, QPersistentModelIndex, QSize, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QAction, QActionGroup, QColor, QCursor, QFont, QIcon, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListView,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSplitter,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from . import cast, cloud, downloads, library, power, sync, ui, update, vlc_loader
from . import tracks as tracklib
from .images import ImageLoader
from .sources import catalog, omdb, playlist, xtream
from .widgets import (AccountDialog, ConnectionDialog, ControlsOverlay, GroupCombo, ItemList, ItemModel, ManageProfilesDialog,
                      ProfileDialog, ProfilePicker, SeekSlider, ShortcutsDialog, SideMenu, VideoFrame, confirm,
                      DownloadsDialog, ItemCardDialog, ProgressDialog, UpdateDialog, inform)


vlc, VLC_ERROR = vlc_loader.load()

MAX_RETRIES = 5
SYNC_MS = 30_000        # synchro avec le compte du foyer : toutes les 30 s…
SYNC_ROOT_EVERY = 4     # … et la liste des profils un passage sur 4 (2 min)
TABS = [("live", "Direct"), ("movie", "Films"), ("series", "Séries"), ("replay", "Replays")]
TAB_ICONS = {"live": "live", "movie": "film", "series": "series", "replay": "replay"}
TAB_COUNT = {"live": "chaînes", "movie": "films", "series": "séries", "replay": "chaînes en replay"}
SEARCH_TAB = len(TABS) + 1  # onglet « Recherche » (page à part), après Accueil et les onglets de contenu
SEARCH_MIN = 2              # nombre de lettres minimum pour chercher
SEARCH_MAX = 300            # résultats affichés au plus par bande
SEEKABLE = {"movie", "episode", "program"}  # contenus avec barre de progression
RESUMABLE = {"movie", "episode"}            # contenus dont on mémorise la position
AUTO_NEXT_MS = 0                            # délai avant l'épisode / le programme suivant (aucun)
ALL, FAV, RECENT = "", "\x00fav", "\x00recent"  # valeurs spéciales du filtre de groupe
OTHERS = "\x00others"  # « Autres » : en-tête (dépliable) des catégories masquées
POSTER_ICON = QSize(32, 48)
LOGO_ICON = QSize(40, 30)
PROGRAMS_TTL = 300  # secondes avant de redemander la liste des replays d'une chaîne


def _norm(text: str) -> str:
    """Minuscules sans accents (recherche « serie » = « Série »)."""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def _esc(text: str) -> str:
    """Échappe le texte inséré dans un libellé HTML (plus léger que le module html)."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def fmt_time(ms: int) -> str:
    s = max(0, int(ms // 1000))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


_KEY_NAMES = {"Space": "Espace", "Left": "←", "Right": "→", "Up": "↑", "Down": "↓", "PgUp": "Page préc.",
              "PgDown": "Page suiv.", "Backspace": "Retour arrière", "Esc": "Échap", "Home": "Début", "Shift": "Maj"}


def _key_label(key: str) -> str:
    """Touche affichée en français : « Ctrl+Right » -> « Ctrl+→ »."""
    return "+".join(_KEY_NAMES.get(part, part) for part in key.split("+"))


def fmt_delay(seconds: float) -> str:
    """Retard sur le direct : « 8 s », « 2 min 05 s », « 1 h 03 min »."""
    s = int(seconds)
    if s < 60:
        return f"{s} s"
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h} h {m:02d} min" if h else f"{m} min {s:02d} s"


# --------------------------------------------------------------------------- #
# Tâches de fond (réseau) : threads « démons » qui ne bloquent pas la fermeture
# --------------------------------------------------------------------------- #
class _Bridge(QObject):
    result = Signal(object, object)

    def __init__(self):
        super().__init__()
        self.result.connect(self._dispatch)

    @Slot(object, object)
    def _dispatch(self, callback, value):
        callback(value)


_bridge: _Bridge | None = None


def _emit(callback, value):
    try:
        _bridge.result.emit(callback, value)
    except RuntimeError:  # fenêtre fermée pendant la tâche : résultat ignoré
        pass


def ask_account(parent=None, notice: str = "") -> bool:
    """Connexion au compte du foyer, obligatoire pour utiliser l'appli ; False si l'utilisateur quitte."""
    session = cloud.session()

    def sign_in(email, password, on_ok, on_error):
        run_async(lambda: session.sign_in(email, password), lambda _=None: on_ok(), on_error)

    dlg = AccountDialog(parent, session.email, False, sign_in, session.sign_out, notice)
    return dlg.exec() == QDialog.Accepted and session.signed_in


VAULT_INTRO = ("Nouveauté : l'abonnement IPTV peut servir à configurer tes nouveaux appareils (nouvelle TV, "
               "nouveau PC) sans retaper les identifiants. Il est stocké <b>chiffré</b> dans le compte : ni Google ni "
               "Firebase ne peuvent le lire. Saisis une fois le mot de passe du compte (il n'est pas enregistré : il "
               "sert seulement à calculer la clé). Chaque appareil garde son propre abonnement.")


def ask_vault(parent=None) -> bool:
    """Mot de passe du compte, une fois, pour le partage chiffré de la source IPTV (clé dérivée du mot de passe)."""
    session = cloud.session()

    def sign_in(email, password, on_ok, on_error):
        run_async(lambda: session.sign_in(email, password), lambda _=None: on_ok(), on_error)

    dlg = AccountDialog(parent, session.email, False, sign_in, session.sign_out, intro=VAULT_INTRO,
                        cancel_label="Plus tard")
    return dlg.exec() == QDialog.Accepted and session.vault_key is not None


def cloud_task(fn):
    """fn pour run_async : une erreur du serveur est retournée (et non levée) pour garder son type."""
    def run():
        try:
            return fn()
        except cloud.CloudError as e:
            print(f"Synchro : {e.__class__.__name__} : {e}")
            return e
    return run


def run_async(fn, on_done, on_error=None):
    """Exécute fn() dans un thread et appelle on_done(résultat) / on_error(message) dans l'interface."""
    def work():
        try:
            value = fn()
        except Exception as exc:
            traceback.print_exc()
            if on_error is not None:
                _emit(on_error, str(exc) or exc.__class__.__name__)
            return
        _emit(on_done, value)

    threading.Thread(target=work, daemon=True).start()


def fetch_catalog(src: dict, rules: dict, cached_sig: str | None = None, allow_m3u: bool = True, folder=None):
    """Télécharge le catalogue. Retourne (client Xtream ou None, entrées, signature).

    entrées = None si le catalogue est identique à celui du cache (signature inchangée).
    allow_m3u : si l'API Xtream ne répond pas, se rabattre sur la playlist M3U (moins complète :
    pas de replays ni de descriptifs). Interdit quand un catalogue est déjà affiché, pour ne pas
    remplacer un bon catalogue par une version dégradée lors d'une panne passagère du serveur.
    """
    if src["type"] == "xtream":
        client = xtream.XtreamClient(src["server"], src["username"], src["password"], src["format"])
        try:
            raw = client.fetch_catalog()
        except Exception as exc:
            if not allow_m3u:
                raise
            api_error = exc
            print("API Xtream indisponible, repli sur la playlist M3U :", exc)
        else:
            sig = client.signature(raw)
            if sig == cached_sig:
                return client, None, sig
            items = client.build_catalog(raw)
            del raw
            catalog.save(src, sig, items, folder)
            return client, items, sig
        url = src.get("m3u_url") or playlist.build_xtream_url(
            src["server"], src["username"], src["password"], src["format"])
        try:
            return None, playlist.classify_all(playlist.load_from_url(url), rules), None
        except Exception as exc:
            raise RuntimeError(f"{api_error}\n\n(Playlist M3U : {exc})") from exc
    if src["type"] == "file":
        return None, playlist.classify_all(playlist.load_from_file(src["value"]), rules), None
    return None, playlist.classify_all(playlist.load_from_url(src["value"]), rules), None


# --------------------------------------------------------------------------- #
# Fenêtre principale
# --------------------------------------------------------------------------- #
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("IPTV Player")
        self.resize(1280, 760)

        self.cfg = config.load()
        self.profile_id = config.current_profile()  # fixé pour cette fenêtre (changer de profil = nouvelle fenêtre)
        self.profile_folder = config.profile_dir(self.profile_id)
        self._switched = False  # fenêtre fermée pour passer à un autre profil
        self.library = library.Library(self.profile_folder)
        self.cloud = cloud.session()  # compte du foyer (commun à tous les profils de ce PC)
        self.images = ImageLoader(self)
        self.client: xtream.XtreamClient | None = None
        self.by_tab: dict[str, list[playlist.Item]] = {k: [] for k, _ in TABS}
        self.by_key: dict[str, playlist.Item] = {}
        self.tab_groups: dict[str, list[str]] = {}  # catégories de chaque onglet (ordre du fournisseur)
        self.catalog_sig: str | None = None
        self.tab = "live"
        self.view = "list"                 # "list" | "episodes" | "programs"
        self.view_parent: playlist.Item | None = None
        self.view_items: list[playlist.Item] = []
        self.back_state: dict = {}
        self.tab_group: dict[str, str] = {}  # filtre de groupe mémorisé par onglet
        self.details_item: playlist.Item | None = None
        self._open_token = None

        self.current: playlist.Item | None = None
        self.play_list: list[playlist.Item] = []  # liste dans laquelle on zappe
        self.want_playing = False
        self.retries = 0
        self.last_play_ts = 0.0
        self.last_pos = 0
        self.last_len = 0
        self.last_progress_save = 0.0
        self.loading = False
        self._busy_cursor = False
        self.instance = self.player = None  # VLC est initialisé juste après l'affichage de la fenêtre
        self._fullscreen = False
        self._was_maximized = False       # état de la fenêtre avant le plein écran
        self.cast_target = None           # appareil Google Cast utilisé (None = cet ordinateur)
        self.track_pref: dict = {}        # pistes choisies pour le flux en cours : {"audio": id, "spu": id}
        self.cast_compat = set(self.cfg.get("cast_compat", []))  # chaînes diffusées en « mode compatible »
        self._pending_seek = None         # position à rejoindre si la reprise demandée est ignorée
        self._offset_ms = 0               # replay : le flux ouvert commence à cette position du programme
        self._seek_target = None          # position demandée, appliquée après une courte pause (clics groupés)
        self._seek_hold = None            # (position, échéance) affichée le temps que la lecture la rejoigne
        self._stream_start_pos = 0        # position de départ du flux en cours (ms)
        self._live_delay = 0.0            # direct : retard accumulé par les pauses (secondes)
        self._paused_at = None            # direct : début de la pause en cours (time.monotonic)
        self._auto_next = None            # épisode / programme lancé automatiquement à la fin du précédent
        # Langue / sous-titres choisis par film ou par série : {clé: {"audio": {lang, desc}, "spu": … | "off"}}
        self.track_prefs: dict = self.library.prefs  # lecture seule : on les change par library.set_pref
        self._track_cache: dict = {}      # pistes lues dans chaque fichier (url -> [tracks.Track])
        self._probe_waiters: dict = {}    # lectures de pistes en cours (url -> fonctions à rappeler)
        self._play_token = None           # lecture en attente de la lecture des pistes
        self.cast_devices: list = []
        self._cast_scanning = False
        self._cast_scan_t = 0.0
        self._left_was_visible = True
        self._last_cursor = None
        self._last_move = 0.0

        self._build_ui()
        self._build_menu()

        self.filter_timer = QTimer(self)
        self.filter_timer.setSingleShot(True)
        self.filter_timer.setInterval(200)
        self.filter_timer.timeout.connect(self._apply_filter)

        # Rafraîchit la liste quand des images arrivent (regroupé pour éviter de redessiner 50 fois)
        self.image_timer = QTimer(self)
        self.image_timer.setSingleShot(True)
        self.image_timer.setInterval(120)
        self.image_timer.timeout.connect(self._on_images_ready)
        self.images.loaded.connect(lambda _url: self.image_timer.start())

        # Surveillance du flux : reconnexion automatique en cas de coupure
        self.watchdog = QTimer(self)
        self.watchdog.setInterval(2000)
        self.watchdog.timeout.connect(self._check_player)
        self.watchdog.start()

        # Barre de progression + mémorisation de la position (films, épisodes)
        self.ui_timer = QTimer(self)
        self.ui_timer.setInterval(500)
        self.ui_timer.timeout.connect(self._update_power)  # en premier : il agit avant _update_seek au réveil
        self.ui_timer.timeout.connect(self._update_seek)
        self.ui_timer.timeout.connect(self._sync_play_icon)
        self.ui_timer.timeout.connect(self._update_live_badge)
        self._play_icon_playing = None
        self._last_tick = time.time()
        self.ui_timer.start()

        # Fin d'un épisode / d'un replay : la suite démarre après quelques secondes
        self.next_timer = QTimer(self)
        self.next_timer.setSingleShot(True)
        self.next_timer.setInterval(AUTO_NEXT_MS)
        self.next_timer.timeout.connect(self._play_auto_next)

        # Diffusion : chaque déplacement fait recharger la vidéo à la télé (plusieurs secondes). Les clics
        # rapprochés (± 10 s, barre de progression) sont regroupés en un seul déplacement.
        self.seek_timer = QTimer(self)
        self.seek_timer.setSingleShot(True)
        self.seek_timer.setInterval(900)
        self.seek_timer.timeout.connect(self._apply_seek)

        # Langues de la fiche : lues après une courte pause (pas pour chaque ligne parcourue au clavier)
        self.tracks_timer = QTimer(self)
        self.tracks_timer.setSingleShot(True)
        self.tracks_timer.setInterval(450)
        self.tracks_timer.timeout.connect(self._probe_details)

        # Synchro avec le compte du foyer (profils, favoris, reprises, langues)
        self.sync_timer = QTimer(self)
        self.sync_timer.setInterval(SYNC_MS)
        self.sync_timer.timeout.connect(self._sync)
        self._sync_busy = False
        self._sync_round = 0              # passage n° 0, 4, 8… : liste des profils comprise
        self._sync_error_shown = False

        # Plein écran : la barre de contrôle apparaît quand la souris bouge, disparaît après 3 s
        self.fs_timer = QTimer(self)
        self.fs_timer.setInterval(250)
        self.fs_timer.timeout.connect(self._fs_poll)

        # Taille « restaurée » : la dernière utilisée, sinon 85 % de l'écran (la fenêtre s'ouvre agrandie)
        geometry = self.cfg.get("window_geometry", "")
        restored = False
        if geometry:
            try:
                restored = self.restoreGeometry(bytes.fromhex(geometry))
            except ValueError:
                pass
        screen = QApplication.primaryScreen()
        if not restored and screen is not None:
            area = screen.availableGeometry()
            self.resize(int(area.width() * 0.85), int(area.height() * 0.85))
            self.move(area.center() - self.rect().center())

        self._refresh_home()
        QTimer.singleShot(0, self._startup)

    # ---- VLC ------------------------------------------------------------- #
    def _vlc_args(self):
        log = config.config_dir() / "vlc.log"  # erreurs de VLC uniquement (utile si une diffusion échoue)
        try:
            log.unlink(missing_ok=True)
        except OSError:
            pass
        return [
            f"--network-caching={int(self.cfg.get('network_cache_ms', 1500))}",
            "--no-video-title-show",
            "--http-reconnect",
            "--quiet",
            "--file-logging",
            f"--logfile={log}",
            "--log-verbose=0",
        ]

    @staticmethod
    def _new_vlc(args):
        lib = os.environ.get("PYTHON_VLC_LIB_PATH")
        if lib and not cast.vod_ready:  # diffusion des films sans « Différé » sur la télé (voir cast.py)
            cast.prepare_vod_module(os.path.dirname(lib), config.config_dir())
        instance = vlc.Instance(*args)
        if instance is None:
            raise RuntimeError("Impossible d'initialiser libVLC.")
        return instance, instance.media_player_new()

    def _build_vlc_async(self):
        """Initialise libVLC dans un thread : l'interface et le catalogue s'affichent sans l'attendre."""
        args = self._vlc_args()

        def ready(pair):
            if self.player is None:
                self._setup_vlc(*pair)
            else:  # déjà créé entre-temps (lecture lancée très tôt)
                pair[1].release()
                pair[0].release()

        def failed(msg):
            if self.player is None:
                QMessageBox.critical(self, "VLC", f"Impossible d'initialiser libVLC : {msg}")

        run_async(lambda: self._new_vlc(args), ready, failed)

    def _build_vlc(self):
        self._setup_vlc(*self._new_vlc(self._vlc_args()))

    def _setup_vlc(self, instance, player):
        self.instance, self.player = instance, player
        # Les événements souris/clavier restent à Qt (raccourcis, double-clic...)
        self.player.video_set_mouse_input(False)
        self.player.video_set_key_input(False)
        self.player.audio_set_volume(int(self.cfg.get("volume", 80)))
        self._embed()

    def _embed(self):
        if self.player is None:
            return
        wid = int(self.video.winId())
        if sys.platform.startswith("linux"):
            self.player.set_xwindow(wid)
        elif sys.platform == "win32":
            self.player.set_hwnd(wid)
        elif sys.platform == "darwin":
            self.player.set_nsobject(wid)

    def showEvent(self, event):
        super().showEvent(event)
        self._embed()

    # ---- Interface ------------------------------------------------------- #
    def _build_ui(self):
        splitter = QSplitter(Qt.Horizontal)
        self.browse = splitter

        # Panneau gauche : navigation, recherche, groupes, liste
        self.left = QWidget()
        self.left.setObjectName("browseLeft")
        self.left.setAttribute(Qt.WA_StyledBackground, True)
        lv = QVBoxLayout(self.left)
        lv.setContentsMargins(8, 8, 6, 6)

        self.nav_row = QWidget()
        nl = QHBoxLayout(self.nav_row)
        nl.setContentsMargins(0, 0, 0, 0)
        self.back_btn = QPushButton(ui.icon("chevron_left"), "Retour")
        self.back_btn.setObjectName("backBtn")
        self.back_btn.setFocusPolicy(Qt.NoFocus)
        self.back_btn.clicked.connect(self.go_back)
        self.nav_title = QLabel()
        self.nav_title.setObjectName("navTitle")
        self.nav_title.setMinimumWidth(1)
        self.nav_title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        f = QFont(self.nav_title.font())
        f.setBold(True)
        self.nav_title.setFont(f)
        nl.addWidget(self.back_btn)
        nl.addWidget(self.nav_title, 1)
        self.nav_row.hide()

        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("Rechercher…  (Ctrl+F)")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda _: self.filter_timer.start())

        self.group_combo = GroupCombo()
        # Sans ceci, la liste s'élargit à la plus longue catégorie du fournisseur… et la fenêtre avec
        self.group_combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.group_combo.setMinimumContentsLength(12)
        self.group_combo.currentIndexChanged.connect(self._on_group_changed)
        # Clic droit sur une catégorie (liste ouverte ou fermée) : la masquer / la réafficher. Dans la liste ouverte,
        # les clics sont filtrés (eventFilter) : un clic droit ne choisit pas la catégorie, un clic sur « Autres »
        # le déplie sur place sans refermer la liste
        self._others_open = False
        self._group_viewport = self.group_combo.view().viewport()
        self._group_viewport.installEventFilter(self)
        self.group_combo.setContextMenuPolicy(Qt.CustomContextMenu)
        self.group_combo.customContextMenuRequested.connect(
            lambda pos: self._group_menu(self.group_combo.currentData(), self.group_combo.mapToGlobal(pos)))

        self.model = ItemModel(lambda it: it.name, lambda it: None)
        self.list = ItemList()
        self.list.setObjectName("itemList")
        # Lignes dessinées sur mesure : vignette, titre, infos, progression, badges
        self.list_delegate = ui.ListDelegate(self.images, self._row, self.list)
        self.list.setItemDelegate(self.list_delegate)
        self.list.setMouseTracking(True)
        self.list.viewport().setAttribute(Qt.WA_Hover)
        self.list.setModel(self.model)
        self.list.setUniformItemSizes(True)
        # Mise en page par lots : la 1re page s'affiche en quelques ms même avec 13 000 films
        self.list.setLayoutMode(QListView.Batched)
        self.list.setBatchSize(500)
        self.list.setIconSize(LOGO_ICON)
        self.list.setEditTriggers(QListView.NoEditTriggers)
        self.list.activated.connect(self._on_activated)  # Entrée ou double-clic
        self.list.selectionModel().currentChanged.connect(self._on_current_changed)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._context_menu)
        self.list.moved.connect(self._move_favorite)

        # Fiche en grand : elle occupe la partie droite (à la place de la vidéo) hors lecture
        self.details = ui.DetailsPage()
        self.details.play_btn.clicked.connect(lambda: self._details_action("play"))
        self.details.alt_btn.clicked.connect(lambda: self._details_action("alt"))
        self.details.fav_btn.clicked.connect(lambda: self._details_action("fav"))
        self.details.dl_btn.clicked.connect(self._details_download)
        self.downloads = downloads.manager()  # commun à toute l'appli (continue pendant un changement de profil)
        self.downloads.changed.connect(self._update_dl_btn)

        self.count_label = QLabel("Aucune playlist chargée")
        self.count_label.setObjectName("countLabel")
        self.count_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

        lv.addWidget(self.nav_row)
        lv.addWidget(self.search)
        lv.addWidget(self.group_combo)
        lv.addWidget(self.list, 1)
        lv.addWidget(self.count_label)

        # Panneau droit : en-tête (titre, diffusion), vidéo, barre de contrôle
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)

        self.player_top = QWidget()
        self.player_top.setObjectName("playerTop")
        self.player_top.setAttribute(Qt.WA_StyledBackground, True)
        tl = QHBoxLayout(self.player_top)
        tl.setContentsMargins(16, 7, 10, 7)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        self.player_title = QLabel("Aucune lecture en cours")
        self.player_title.setObjectName("playerTitle")
        self.player_sub = QLabel("Choisis une chaîne, un film ou une série")
        self.player_sub.setObjectName("playerSub")
        for lbl in (self.player_title, self.player_sub):
            lbl.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            titles.addWidget(lbl)
        tl.addLayout(titles, 1)
        self.cast_btn = QToolButton()
        self.cast_btn.setObjectName("castBtn")
        self.cast_btn.setText("Diffuser")
        self.cast_btn.setIcon(ui.icon("cast"))
        self.cast_btn.setIconSize(QSize(20, 20))
        self.cast_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.cast_btn.setToolTip("Diffuser sur une télé (Chromecast, Google TV)")
        self.cast_btn.setCursor(Qt.PointingHandCursor)
        self.cast_btn.setFocusPolicy(Qt.NoFocus)
        self.cast_menu = QMenu(self.cast_btn)
        self.cast_menu.aboutToShow.connect(self._on_cast_menu)
        self.cast_btn.setMenu(self.cast_menu)
        self.cast_btn.setPopupMode(QToolButton.InstantPopup)
        tl.addWidget(self.cast_btn)

        self.video = VideoFrame()
        self.video.doubleClicked.connect(self.toggle_fullscreen)

        self.controls = QWidget()
        self.controls.setObjectName("playerBar")
        self.controls.setAttribute(Qt.WA_StyledBackground, True)
        outer = QVBoxLayout(self.controls)
        outer.setContentsMargins(14, 8, 14, 8)
        outer.setSpacing(4)

        # Progression (films, épisodes, replays) : temps écoulé | barre | durée
        self.seek_row = QWidget()
        sl = QHBoxLayout(self.seek_row)
        sl.setContentsMargins(4, 0, 4, 0)
        sl.setSpacing(12)
        self.time_cur = QLabel("00:00")
        self.time_total = QLabel("00:00")
        self.seek = SeekSlider(Qt.Horizontal)
        self.seek.setObjectName("seek")
        self.seek.setRange(0, 1000)
        self.seek.setFocusPolicy(Qt.NoFocus)
        self.seek.setCursor(Qt.PointingHandCursor)
        self.seek.seekRequested.connect(self._on_seek)
        for lbl in (self.time_cur, self.time_total):
            lbl.setObjectName("time")
        sl.addWidget(self.time_cur)
        sl.addWidget(self.seek, 1)
        sl.addWidget(self.time_total)
        self.seek_row.hide()
        outer.addWidget(self.seek_row)

        buttons_row = QWidget()
        cl = QHBoxLayout(buttons_row)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(4)
        outer.addWidget(buttons_row)

        def button(name, tip, slot, main=False, size=22):
            b = QToolButton()
            b.setObjectName("pbtnMain" if main else "pbtn")
            b.setIcon(ui.icon(name, "white" if main else None))
            b.setIconSize(QSize(26, 26) if main else QSize(size, size))
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.NoFocus)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(slot)
            cl.addWidget(b)
            return b

        button("prev", "Précédent  (Page préc.)", lambda: self.zap(-1))
        self.play_btn = button("play", "Pause / lecture  (Espace)", self.toggle_pause, main=True)
        button("next", "Suivant  (Page suiv.)", lambda: self.zap(+1))
        button("stop", "Stop", self.stop)

        # Navigation dans les films / épisodes / replays (masquée pour le direct)
        self.seek_buttons = QWidget()
        sk = QHBoxLayout(self.seek_buttons)
        sk.setContentsMargins(12, 0, 0, 0)
        sk.setSpacing(2)
        self._seek_btns = []
        for delta in (-30000, -10000, 10000, 30000):
            b = QToolButton()
            b.setObjectName("pbtn")
            b.setIconSize(QSize(26, 26))
            b.setFocusPolicy(Qt.NoFocus)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, d=delta: self.seek_by(d))
            sk.addWidget(b)
            self._seek_btns.append(b)
        self._set_seek_buttons(minutes=False)
        self.seek_buttons.hide()
        cl.addWidget(self.seek_buttons)

        # Direct : « En direct », ou le retard pris après une pause (clic = retour au direct)
        self.live_badge = QToolButton()
        self.live_badge.setObjectName("liveBadge")
        self.live_badge.setIconSize(QSize(10, 10))
        self.live_badge.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.live_badge.setFocusPolicy(Qt.NoFocus)
        self.live_badge.clicked.connect(self.back_to_live)
        self.live_badge.hide()
        self._live_badge_text = None
        cl.addSpacing(12)
        cl.addWidget(self.live_badge)

        # Séries et replays : épisode / programme suivant (visible seulement s'il y a une suite)
        self.next_ep_btn = QToolButton()
        self.next_ep_btn.setObjectName("nextEp")
        self.next_ep_btn.setIcon(ui.icon("next", "white"))
        self.next_ep_btn.setIconSize(QSize(16, 16))
        self.next_ep_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.next_ep_btn.setFocusPolicy(Qt.NoFocus)
        self.next_ep_btn.setCursor(Qt.PointingHandCursor)
        self.next_ep_btn.clicked.connect(self.play_next_episode)
        self.next_ep_btn.hide()
        cl.addSpacing(10)
        cl.addWidget(self.next_ep_btn)
        cl.addStretch(1)

        # Langue (pistes audio) et sous-titres : menus remplis à l'ouverture
        self.audio_btn = QToolButton()
        self.audio_btn.setToolTip("Langue / piste audio  (B : suivante)")
        self.audio_btn.setIcon(ui.icon("audio"))
        self.sub_btn = QToolButton()
        self.sub_btn.setToolTip("Sous-titres  (V : suivants)")
        self.sub_btn.setIcon(ui.icon("subtitles"))
        for btn, kind in ((self.audio_btn, "audio"), (self.sub_btn, "spu")):
            btn.setObjectName("pbtn")
            btn.setIconSize(QSize(22, 22))
            btn.setCursor(Qt.PointingHandCursor)
            menu = QMenu(btn)
            menu.aboutToShow.connect(lambda m=menu, k=kind: self._fill_tracks_menu(m, k))
            btn.setMenu(menu)
            btn.setPopupMode(QToolButton.InstantPopup)
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setEnabled(False)
            cl.addWidget(btn)

        self.mute_btn = button("volume", "Couper / remettre le son  (M)", self.toggle_mute)
        self.volume = QSlider(Qt.Horizontal)
        self.volume.setObjectName("volume")
        self.volume.setToolTip("Volume")
        self.volume.setRange(0, 120)
        self.volume.setValue(int(self.cfg.get("volume", 80)))
        self.volume.setFixedWidth(100)
        self.volume.setFocusPolicy(Qt.NoFocus)
        self.volume.setCursor(Qt.PointingHandCursor)
        self.volume.valueChanged.connect(self._on_volume)
        cl.addWidget(self.volume)
        cl.addSpacing(8)
        button("fullscreen", "Plein écran  (F11, Échap pour quitter)", self.toggle_fullscreen)

        rv.addWidget(self.player_top)
        rv.addWidget(self.video, 1)
        rv.addWidget(self.controls)
        self.right_layout = rv
        self.player_panel = right
        self.overlay = ControlsOverlay(self)       # barre de contrôle en plein écran (bas)
        self.top_overlay = ControlsOverlay(self)   # titre + diffusion en plein écran (haut)

        # Partie droite : fiche en grand OU lecteur vidéo
        self.right_stack = QStackedWidget()
        self.right_stack.addWidget(self.details)
        self.right_stack.addWidget(self.player_panel)
        self.right_stack.setCurrentWidget(self.player_panel)

        splitter.addWidget(self.left)
        splitter.addWidget(self.right_stack)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([420, 860])

        # Page d'accueil (mosaïques) et pages de navigation, sous un bandeau commun
        self.home = ui.HomePage(self.images)
        self.home.openTab.connect(self.show_browse)
        self.search_page = ui.SearchPage(self.images)
        self.search_page.tileClicked.connect(self._open_from_search)
        self.search_page.openTab.connect(self.show_browse)
        self.search_timer = QTimer(self)  # recherche après une courte pause dans la frappe
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(250)
        self.search_timer.timeout.connect(self._run_search)
        self.search_page.field.textChanged.connect(lambda _: self.search_timer.start())
        self.home.tileClicked.connect(self._on_tile)
        self.home.tileRemoved.connect(self._on_tile_removed)
        self.pages = QStackedWidget()
        self.pages.addWidget(self.home)
        self.pages.addWidget(self.browse)
        self.pages.addWidget(self.search_page)

        central = QWidget()
        cv = QVBoxLayout(central)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        cv.addWidget(self._build_header())
        cv.addWidget(self.pages, 1)
        self.setCentralWidget(central)

        self.statusBar().showMessage("Prêt")

    def _build_header(self) -> QWidget:
        self.header = QWidget()
        self.header.setObjectName("header")
        self.header.setAttribute(Qt.WA_StyledBackground, True)
        h = QHBoxLayout(self.header)
        h.setContentsMargins(14, 0, 14, 0)
        h.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(QIcon(config.asset_path("icon.ico")).pixmap(QSize(28, 28), self.devicePixelRatioF()))
        brand = QLabel("IPTV Player")
        brand.setObjectName("brand")
        h.addWidget(logo)
        h.addWidget(brand)
        h.addSpacing(18)
        self.tabs = ui.NavBar(["home"] + [TAB_ICONS[k] for k, _ in TABS] + ["search"])
        self.tabs.setObjectName("nav")
        self.tabs.setIconSize(QSize(18, 18))
        self.tabs.setExpanding(False)
        self.tabs.setDrawBase(False)
        self.tabs.setUsesScrollButtons(False)  # tous les onglets toujours visibles
        self.tabs.setElideMode(Qt.ElideNone)
        self.tabs.addTab("Accueil")
        for _, label in TABS:
            self.tabs.addTab(label)
        self.tabs.addTab("Recherche")
        self.tabs.setTabToolTip(SEARCH_TAB, "Rechercher un film ou une série")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        h.addWidget(self.tabs)
        h.addStretch(1)
        self.now_btn = QPushButton()
        self.now_btn.setObjectName("nowPlaying")
        self.now_btn.setCursor(Qt.PointingHandCursor)
        self.now_btn.setFocusPolicy(Qt.NoFocus)
        self.now_btn.setMaximumWidth(360)
        self.now_btn.clicked.connect(self.show_player)
        self.now_btn.hide()
        h.addWidget(self.now_btn)
        # Téléchargements en cours : bouton visible seulement quand il y en a (nombre et progression)
        self.dl_btn = QToolButton()
        self.dl_btn.setObjectName("burger")
        self.dl_btn.setIcon(ui.icon("download", ui.C["accent_hi"]))
        self.dl_btn.setIconSize(QSize(18, 18))
        self.dl_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.dl_btn.setCursor(Qt.PointingHandCursor)
        self.dl_btn.setFocusPolicy(Qt.NoFocus)
        self.dl_btn.setToolTip("Téléchargements")
        self.dl_btn.clicked.connect(self.open_downloads)
        self.dl_btn.hide()
        h.addWidget(self.dl_btn)
        # Profil en cours : pastille + nom ; menu pour changer de profil ou en créer un
        self.profile_btn = QToolButton()
        self.profile_btn.setObjectName("profileBtn")
        self.profile_btn.setToolButtonStyle(Qt.ToolButtonIconOnly)
        self.profile_btn.setCursor(Qt.PointingHandCursor)
        self.profile_btn.setFocusPolicy(Qt.NoFocus)
        self.profile_menu = QMenu(self.profile_btn)
        self.profile_menu.aboutToShow.connect(self._fill_profile_menu)
        self.profile_btn.setMenu(self.profile_menu)
        self.profile_btn.setPopupMode(QToolButton.InstantPopup)
        self._update_profile_btn()
        h.addWidget(self.profile_btn)
        self.menu_btn = QToolButton()
        self.menu_btn.setObjectName("burger")
        self.menu_btn.setIcon(ui.icon("menu"))
        self.menu_btn.setIconSize(QSize(20, 20))
        self.menu_btn.setToolTip("Menu : connexion IPTV, plein écran, raccourcis clavier")
        self.menu_btn.setCursor(Qt.PointingHandCursor)
        self.menu_btn.setFocusPolicy(Qt.NoFocus)
        self.menu_btn.clicked.connect(self.open_side_menu)
        h.addWidget(self.menu_btn)
        return self.header

    # ---- Profils ----------------------------------------------------------- #
    def _profile(self) -> dict:
        return next(p for p in self.cfg["profiles"] if p["id"] == self.profile_id)

    def _update_profile_btn(self):
        cur = self._profile()
        others = [p for p in self.cfg["profiles"] if p["id"] != self.profile_id]
        icon, size = ui.avatar_stack([cur] + others)
        self.profile_btn.setIcon(icon)
        self.profile_btn.setIconSize(size)
        self.profile_btn.setToolTip(f"Profil : {cur['name']}. Changer de profil, en créer un")

    def _fill_profile_menu(self):
        """Menu du profil : mini « Qui regarde ? » (une tuile par profil, + Ajouter), puis « Gérer »."""
        m = self.profile_menu
        m.clear()
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(4, 2, 4, 2)
        v.setSpacing(2)
        head = QLabel("QUI REGARDE ?")
        head.setObjectName("menuHead")
        v.addWidget(head)
        grid = QGridLayout()
        grid.setSpacing(4)
        tiles = [(p["name"], ui.avatar(p["name"], p["color"]), p["id"] == self.profile_id,
                  lambda pid=p["id"]: self.switch_profile(pid)) for p in self.cfg["profiles"]]
        tiles.append(("Ajouter", ui.icon("add_profile", ui.C["muted"]), False, self.new_profile))
        for i, (text, icon, current, action) in enumerate(tiles):
            b = QToolButton()
            b.setObjectName("menuTile")
            b.setIcon(icon)
            b.setIconSize(QSize(40, 40))
            b.setText(text)
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setProperty("current", current)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, a=action: (m.close(), QTimer.singleShot(0, a)))
            grid.addWidget(b, i // 3, i % 3)
        v.addLayout(grid)
        wa = QWidgetAction(m)
        wa.setDefaultWidget(box)
        m.addAction(wa)
        m.addSeparator()
        m.addAction(ui.icon("edit", ui.C["muted"]), "Gérer les profils…").triggered.connect(self.manage_profiles)

    def manage_profiles(self):
        """Fenêtre « Gérer les profils » : modifier, source IPTV, supprimer, « Qui regarde ? »."""
        def edit(pid):
            prof = next(p for p in self.cfg["profiles"] if p["id"] == pid)
            d = ProfileDialog(dlg, prof["name"], prof["color"])
            if d.exec() != QDialog.Accepted:
                return False
            prof["name"], prof["color"], _ = d.values()
            prof["t"] = time.time()
            config.save(self.cfg, self.profile_id)
            self._update_profile_btn()
            self._sync_soon()
            return True

        def source(pid):
            if pid == self.profile_id:
                self.open_connection()
                return False
            data = dict(config.DEFAULTS)
            data.update(config.read_profile(pid))
            d = ConnectionDialog(data, dlg)
            if d.exec() == QDialog.Accepted:
                data.update(d.values())
                data["source_t"] = time.time()
                config.write_profile(pid, data)
            return False

        def delete(pid):
            prof = next(p for p in self.cfg["profiles"] if p["id"] == pid)
            answer = QMessageBox.question(
                dlg, "Supprimer le profil",
                f"Supprimer le profil « {prof['name']} » ? Ses favoris, lectures en cours, « Vu récemment » et "
                "sa source IPTV seront effacés. Les autres profils ne sont pas touchés.")
            if answer != QMessageBox.Yes:
                return False
            if pid == self.profile_id:
                dlg.accept()
                other = next(p["id"] for p in self.cfg["profiles"] if p["id"] != pid)
                self.switch_profile(other, delete_current=True)
                return False
            config.delete_profile(self.cfg, pid)
            config.save(self.cfg, self.profile_id)
            self._update_profile_btn()
            self._sync_soon()
            return True

        def reset(pid):
            prof = next(p for p in self.cfg["profiles"] if p["id"] == pid)
            if not confirm(
                    dlg, "Réinitialiser le profil",
                    f"Effacer les favoris, lectures en cours, « Vu récemment », épisodes vus et choix de langue du "
                    f"profil <b>{prof['name']}</b> ? À faire après un changement de fournisseur IPTV, quand ces "
                    "données ne correspondent plus au catalogue. Le profil et sa source IPTV sont conservés.",
                    "Réinitialiser", danger=True):
                return False
            if pid != self.profile_id:
                lib = library.Library(config.profile_dir(pid))
                lib.reset()
                session = self.cloud
                run_async(cloud_task(lambda: sync.sync_library_now(session, lib, pid)), lambda _: None)
                return False
            self.library.reset()
            self._library_changed()
            self._sync_soon()
            return False

        def ask(on):
            self.cfg["ask_profile"] = on
            config.save(self.cfg, self.profile_id)

        dlg = ManageProfilesDialog(self, self.cfg, self.profile_id, edit, source, reset, delete, ask)
        dlg.exec()

    def new_profile(self):
        cur = self._profile()
        used = {p["color"] for p in self.cfg["profiles"]}
        color = next((c for c in config.PROFILE_COLORS if c not in used), config.PROFILE_COLORS[0])
        dlg = ProfileDialog(self, "", color, copy_from=cur["name"])
        if dlg.exec() != QDialog.Accepted:
            return
        name, color, same = dlg.values()
        pid = config.create_profile(self.cfg, name, color, self.cfg if same else None)
        self.switch_profile(pid)

    def switch_profile(self, pid: str, delete_current: bool = False, save: bool = True, message: str = ""):
        """Change de profil : tout est enregistré, puis la fenêtre est rouverte sur l'autre profil.
        save=False : rien n'est enregistré (réglages déjà à jour sur le disque, ou profil supprimé ailleurs) ;
        la fenêtre est rouverte même sur le même profil."""
        global _main_window
        if pid == self.profile_id and not delete_current and save:
            return
        self.stop()
        if save:
            self._save_progress()
            self.cfg["window_geometry"] = bytes(self.saveGeometry().toHex()).decode()
        if delete_current:
            config.delete_profile(self.cfg, self.profile_id)
            config.save_common(self.cfg, pid)
        elif save:
            self.library.save()
            config.save(self.cfg, self.profile_id)
            self._sync_now()
        self._switched = True  # la fermeture n'enregistre plus rien (déjà fait)
        self.sync_timer.stop()
        config.set_profile(pid)
        win = MainWindow()
        win.showMaximized()
        if message:
            win.statusBar().showMessage(message, 10000)
        _main_window = win
        self.close()

    # ---- Accueil ------------------------------------------------------------ #
    def show_home(self):
        self._refresh_home()
        self.pages.setCurrentWidget(self.home)
        self.tabs.blockSignals(True)
        self.tabs.setCurrentIndex(0)
        self.tabs.blockSignals(False)
        self._update_now_playing()

    def show_browse(self, tab: str):
        self.pages.setCurrentWidget(self.browse)
        if tab != self.tab or self.tabs.currentIndex() == 0:
            self._set_tab(tab)
        self._update_now_playing()

    def show_player(self):
        """Revient à la lecture en cours (onglet où elle a été lancée, vidéo affichée)."""
        tab = getattr(self, "play_tab", self.tab)
        if tab != self.tab:
            self._set_tab(tab)
        else:
            self.pages.setCurrentWidget(self.browse)
            self.tabs.blockSignals(True)
            self.tabs.setCurrentIndex([k for k, _ in TABS].index(self.tab) + 1)
            self.tabs.blockSignals(False)
        self.right_stack.setCurrentWidget(self.player_panel)
        self._update_now_playing()

    def _is_playing(self) -> bool:
        return self.current is not None and (self.want_playing or (
            self.player is not None and self.player.get_state() in (vlc.State.Playing, vlc.State.Paused)))

    def _update_now_playing(self):
        show = self._is_playing() and self.pages.currentWidget() is self.home
        if show:
            name = self.current.name if self.current.parent is None else f"{self.current.parent.name} · {self.current.name}"
            self.now_btn.setText("▶  En lecture : " + self.now_btn.fontMetrics().elidedText(name, Qt.ElideRight, 240))
        self.now_btn.setVisible(show)

    def _refresh_home(self):
        lib, by_key = self.library, self.by_key
        loading = not by_key  # catalogue pas encore chargé
        secs = self.home.sections

        def channels(tab):
            return [ui.Tile(it, it.name, it.group) for it in
                    (by_key[k] for k in lib.favorite_keys(tab) if k in by_key)]

        movies = []
        for k in lib.recent_keys("movie"):
            it = by_key.get(k)
            if it is None:
                continue
            prog = lib.progress.get(k, {})
            pos, length = prog.get("pos", 0), prog.get("len", 0)
            sub = f"Reprendre à {fmt_time(pos)}" if pos else "Commencé"
            movies.append(ui.Tile(it, it.name, sub, pos / length if length else -1))
        series = []
        for k in lib.recent_keys("series"):
            it = by_key.get(k)
            if it is None:
                continue
            entry = lib.recent[k]
            prog = lib.progress.get(entry.get("last_ep", ""), {})
            pos, length = prog.get("pos", 0), prog.get("len", 0)
            label = entry.get("last_label", "")
            done = entry.get("last_ep") in lib.watched
            sub = ((f"{label} · reprendre à {fmt_time(pos)}" if pos else f"Après {label}" if done else f"{label} · commencé")
                   if label else "En cours")
            series.append(ui.Tile(it, it.name, sub, pos / length if length else -1))

        wait = "Chargement du catalogue…"
        secs["live"].set_tiles(channels("live"), wait if loading else
                               "Aucune chaîne favorite.\nDans l'onglet Direct, ajoute-en avec ★ (Ctrl+D).")
        secs["replay"].set_tiles(channels("replay"), wait if loading else
                                 "Aucune chaîne favorite.\nDans l'onglet Replays, ajoute-en avec ★ (Ctrl+D).")
        secs["movie"].set_tiles(movies, wait if loading else
                                "Aucun film en cours.\nLes films commencés apparaîtront ici.")
        secs["series"].set_tiles(series, wait if loading else
                                 "Aucune série en cours.\nLes séries commencées apparaîtront ici.")

    def _on_tile(self, kind: str, it):
        """Clic sur une vignette de l'accueil : on lance directement."""
        self.show_browse(kind)
        self._select_key(it.key, center=True)
        if kind == "live":
            self.play_item(it)
        elif kind == "replay":
            self.open_programs(it)
        elif kind == "movie":
            self.play_item(it, resume=True)
        elif kind == "series":
            self.open_series(it, play_resume=self._series_resume_target(it) is not None or it.episodes is None)

    def _on_tile_removed(self, kind: str, it):
        """Croix d'une vignette de l'accueil : la chaîne quitte les favoris, le film / la série les lectures
        en cours (position de reprise comprise, comme « Retirer de « Vu récemment » »)."""
        if kind in ("live", "replay"):
            if self.library.is_favorite(kind, it.key):
                self.library.toggle_favorite(kind, it.key)
            msg = f"{it.name} : retiré des favoris"
        else:
            self.library.remove_recent(it.key, [e.key for e in (it.episodes or [])])
            msg = f"{it.name} : retiré des lectures en cours"
        self._library_changed()
        self.statusBar().showMessage(msg, 4000)

    def _update_right(self):
        """Partie droite : la vidéo pendant une lecture, sinon la fiche de l'élément sélectionné."""
        it = self.details_item
        if self._is_playing() or self._auto_next is not None or it is None or it.kind == "live":
            self.right_stack.setCurrentWidget(self.player_panel)
        else:
            self.right_stack.setCurrentWidget(self.details)

    def _action(self, group, text, shortcut, slot):
        """Raccourci clavier de la fenêtre, listé dans « Raccourcis clavier » sous le titre group."""
        act = QAction(text, self)
        keys = shortcut if isinstance(shortcut, (list, tuple)) else [shortcut] if shortcut else []
        act.setShortcuts([QKeySequence(k) for k in keys])
        act.triggered.connect(slot)
        self.addAction(act)  # actif partout, même en plein écran
        if keys:
            shown = " ou ".join(_key_label(k) for k in keys[:2])
            self._shortcuts.setdefault(group, []).append((text, shown))
        return act

    def _build_menu(self):
        # Pas de barre de menus : le bouton ☰ ouvre un panneau latéral ; les raccourcis restent actifs.
        self.menuBar().hide()
        self._shortcuts = {}
        a = self._action
        a("Général", "Connexion IPTV", "Ctrl+K", self.open_connection)
        a("Général", "Recharger la playlist", "F5", self.reload_playlist)
        a("Général", "Raccourcis clavier", ["?", "F1"], self.show_shortcuts)
        a("Général", "Quitter", "Ctrl+Q", self.close)
        a("Lecture", "Pause / lecture", "Space", self.toggle_pause)
        a("Lecture", "Chaîne / élément précédent", "PgUp", lambda: self.zap(-1))
        a("Lecture", "Chaîne / élément suivant", "PgDown", lambda: self.zap(+1))
        a("Lecture", "Muet", "M", self.toggle_mute)
        a("Lecture", "Avancer de 10 s", ["Right", "Shift+Right"], lambda: self.seek_by(10000))
        a("Lecture", "Reculer de 10 s", ["Left", "Shift+Left"], lambda: self.seek_by(-10000))
        a("Lecture", "Avancer de 1 min", "Ctrl+Right", lambda: self.seek_by(60000))
        a("Lecture", "Reculer de 1 min", "Ctrl+Left", lambda: self.seek_by(-60000))
        a("Lecture", "Piste audio suivante", "B", lambda: self._cycle_track("audio"))
        a("Lecture", "Sous-titres suivants", "V", lambda: self._cycle_track("spu"))
        a("Lecture", "Épisode / programme suivant", "N", self.play_next_episode)
        a("Affichage", "Plein écran", "F11", self.toggle_fullscreen)
        a("Affichage", "Quitter le plein écran", "Esc", self._exit_fullscreen)
        a("Affichage", "Afficher / masquer la liste", "Ctrl+L", self.toggle_list)
        a("Affichage", "Rechercher", "Ctrl+F", self._focus_search)
        a("Affichage", "Retour", ["Backspace", "Alt+Left"], self.go_back)
        a("Affichage", "Ajouter / retirer des favoris", "Ctrl+D", self.toggle_favorite_selected)
        a("Affichage", "Monter le favori (★ Favoris)", "Ctrl+Up", lambda: self.move_favorite_selected(-1))
        a("Affichage", "Descendre le favori (★ Favoris)", "Ctrl+Down", lambda: self.move_favorite_selected(+1))
        a("Affichage", "Accueil", ["Ctrl+H", "Alt+Home"], self.show_home)
        self.side_menu = None

    def open_side_menu(self):
        """Bouton ☰ : panneau latéral (actions fréquentes en tuiles, le reste en liste)."""
        if self.side_menu is not None and time.time() - self.side_menu.closed_at < 0.3:
            return  # ce clic vient de fermer le panneau
        self.side_menu = SideMenu(
            self,
            [("plug", "Connexion IPTV", self.open_connection), ("reload", "Recharger", self.reload_playlist),
             ("fullscreen", "Plein écran", self.toggle_fullscreen)],
            [[("account", "Compte du foyer", "", self.open_account),
              ("download", "Téléchargements", "", self.open_downloads),
              ("star", "Notes IMDb (clé OMDb)", "", self.set_omdb_key),
              ("keyboard", "Raccourcis clavier", "?", self.show_shortcuts),
              ("download", "Mise à jour", f"v{__version__}", lambda: self.check_update(silent=False))],
             [("quit", "Quitter", "Ctrl+Q", self.close)]])
        self.side_menu.open_beside(self, self.header)

    # ---- Mise à jour de l'application ---------------------------------- #
    def check_update(self, silent: bool):
        """Cherche une version plus récente ; silent : au démarrage, rien n'est affiché s'il n'y en a pas."""
        if not update.supported():
            if not silent:
                inform(self, "Mise à jour", "La mise à jour depuis l'appli concerne la version installée "
                                            "(installeur), pas le lancement depuis les sources.")
            return

        def done(info):
            if info is None:
                if not silent:
                    inform(self, "Mise à jour", f"Tu as la dernière version ({__version__}).")
                return
            if UpdateDialog(self, info["version"], __version__, info["notes"][:3000]).exec() == QDialog.Accepted:
                self._download_update(info)

        def failed(msg):
            if not silent:
                inform(self, "Mise à jour", f"Impossible de vérifier les mises à jour : {msg}.", error=True)

        run_async(update.check, done, failed)

    def _download_update(self, info: dict):
        cancel = threading.Event()
        dlg = ProgressDialog(self, "Mise à jour", f"Téléchargement de la version <b>{info['version']}</b>…", cancel.set)
        dlg.setWindowModality(Qt.WindowModal)
        dlg.show()

        def progress(value):
            got, total = value
            if not cancel.is_set():
                dlg.set_progress(got, total)

        def done(path):
            dlg.accept()
            try:
                update.install(path)
            except OSError as exc:
                inform(self, "Mise à jour", f"Impossible de lancer l'installeur : {exc}", error=True)
                return
            self.close()  # sauvegarde la position de lecture et les réglages
            QApplication.instance().quit()

        def failed(msg):
            dlg.accept()
            if not cancel.is_set():
                inform(self, "Mise à jour", f"Le téléchargement a échoué : {msg}.", error=True)

        run_async(lambda: update.download(info, lambda got, total: _emit(progress, (got, total)), cancel.is_set),
                  done, failed)

    def show_shortcuts(self):
        order = ("Lecture", "Affichage", "Général")
        ShortcutsDialog(self, [(g, self._shortcuts[g]) for g in order if g in self._shortcuts]).exec()

    # ---- Connexion / chargement ------------------------------------------ #
    def _startup(self):
        src = playlist.source_from_config(self.cfg)
        if src:
            self._load(src, use_cache=True)  # lecture du cache et…
        self._build_vlc_async()              # … initialisation de VLC, chacune dans un thread
        QTimer.singleShot(2500, self._scan_cast)  # appareils de diffusion prêts avant le 1er clic
        QTimer.singleShot(1500, self._sync)       # ce que les autres appareils ont changé depuis
        self.sync_timer.start()
        if update.supported():
            QTimer.singleShot(8000, lambda: self.check_update(silent=True))
        if not src:
            self.open_connection()

    def open_connection(self):
        dlg = ConnectionDialog(self.cfg, self)
        if dlg.exec() == QDialog.Accepted:
            self.cfg.update(dlg.values())
            self.cfg["source_t"] = time.time()  # changement fait ici : envoyé (chiffré) au compte du foyer
            config.save(self.cfg, self.profile_id)
            self._sync_soon()
            src = playlist.source_from_config(self.cfg)
            if src:
                self.catalog_sig = None
                self._load(src, use_cache=True, initial=True)

    def reload_playlist(self):
        src = playlist.source_from_config(self.cfg)
        if src:
            self._load(src)
        else:
            self.open_connection()

    def _set_busy(self, busy: bool):
        if busy and not self._busy_cursor:
            QApplication.setOverrideCursor(Qt.WaitCursor)
        elif not busy and self._busy_cursor:
            QApplication.restoreOverrideCursor()
        self._busy_cursor = busy

    def _load(self, src, use_cache=False, initial=None):
        """Charge le catalogue : d'abord le cache disque (instantané), puis le serveur en arrière-plan."""
        if self.loading:
            return
        if initial is None:
            initial = not self.by_key
        self.loading = True
        if use_cache and src["type"] == "xtream":
            self.statusBar().showMessage("Chargement du catalogue…")
            client = xtream.XtreamClient(src["server"], src["username"], src["password"], src["format"])
            folder = self.profile_folder
            run_async(lambda: catalog.load(src, client, folder),
                      lambda res: self._on_cache(src, client, res, initial),
                      lambda _msg: self._fetch(src, initial, quiet=False))
        else:
            self._fetch(src, initial, quiet=False)

    def _on_cache(self, src, client, res, initial):
        if res is None:  # pas de cache (premier lancement, autre fournisseur…)
            self._fetch(src, initial, quiet=False)
            return
        self.catalog_sig, items = res
        self._apply_catalog(client, items, initial)
        self._fetch(src, False, quiet=True)  # actualisation silencieuse

    def _fetch(self, src, initial, quiet):
        self.loading = True
        if not quiet:
            self.statusBar().showMessage("Chargement du catalogue…")
            self._set_busy(True)
        rules = {"series": self.cfg.get("series_keywords", [])}
        sig = self.catalog_sig
        allow_m3u = not self.by_key  # repli M3U seulement si rien n'est affiché
        folder = self.profile_folder
        run_async(lambda: fetch_catalog(src, rules, sig, allow_m3u, folder),
                  lambda result: self._on_fetched(result, initial, quiet),
                  lambda msg: self._on_failed(msg, quiet))

    def _on_fetched(self, result, initial, quiet):
        self.loading = False
        self._set_busy(False)
        client, items, sig = result
        if items is None:
            if not quiet:
                self.statusBar().showMessage("Catalogue à jour", 4000)
            return
        self.catalog_sig = sig
        self._apply_catalog(client, items, initial)
        if quiet:
            self.statusBar().showMessage(self.statusBar().currentMessage() + " — catalogue actualisé", 6000)

    def _apply_catalog(self, client, items, initial: bool):
        """Installe un catalogue. Si initial=False (actualisation), conserve la vue de l'utilisateur."""
        if self._switched:  # chargement terminé après un changement de profil : plus utile
            return
        self.client = client
        by_tab = {k: [] for k, _ in TABS}
        by_key = {}
        for it in items:
            by_tab.setdefault(it.kind, []).append(it)
            by_key[it.key] = it
            if it.kind == "live" and it.archive_days > 0:
                by_tab["replay"].append(it)
        self.by_tab, self.by_key = by_tab, by_key
        self.tab_groups = {k: list(dict.fromkeys(i.group_label for i in v)) for k, v in by_tab.items()}

        self.tabs.blockSignals(True)
        for i, (k, label) in enumerate(TABS):
            n = len(self.by_tab[k])
            self.tabs.setTabText(i + 1, label)
            self.tabs.setTabToolTip(i + 1, f"{n:,} {TAB_COUNT[k]}".replace(",", " "))
            self.tabs.setTabEnabled(i + 1, n > 0)
        self.tabs.blockSignals(False)
        self.tabs.updateGeometry()  # les compteurs élargissent les onglets

        if initial:
            # Onglet de départ : celui de la dernière entrée regardée, sinon le premier non vide
            last = self.by_key.get(self.cfg.get("last_key", ""))
            start = self.cfg.get("last_tab") if last is not None else None
            if start not in self.by_tab or not self.by_tab[start]:
                start = next((k for k, _ in TABS if self.by_tab[k]), "live")
            self.view = "list"
            self.nav_row.hide()
            self._set_tab(start)
            if last is not None:
                self._select_key(last.key, center=True)
            self.show_home()  # l'appli s'ouvre sur l'accueil
        elif self.view == "list":
            # Actualisation : même onglet, même filtre, même sélection, même position de défilement
            scroll = self.list.verticalScrollBar().value()
            selected = self.tab_group.get(self.tab, ALL)
            if self.group_combo.view().isVisible():  # liste des catégories ouverte : mise à jour sur place
                self._update_groups_in_place(selected)
            else:
                self._populate_groups(selected)
            self._apply_filter()
            self.list.verticalScrollBar().setValue(scroll)
        # (dans une sous-vue épisodes / replays, la liste sera reconstruite au retour)

        if self.pages.currentWidget() is self.home:
            self._refresh_home()
        source = "API Xtream" if self.client else "playlist M3U"
        self.statusBar().showMessage(
            f"{len(self.by_tab['live'])} chaînes, {len(self.by_tab['movie'])} films, "
            f"{len(self.by_tab['series'])} séries, {len(self.by_tab['replay'])} chaînes en replay ({source})")

    def _on_failed(self, message, quiet=False):
        self.loading = False
        self._set_busy(False)
        if quiet or self.by_key:  # le catalogue déjà affiché reste en place
            self.statusBar().showMessage(
                f"Actualisation du catalogue impossible, catalogue précédent conservé. {message}", 10000)
            return
        self.statusBar().showMessage("Échec du chargement")
        QMessageBox.critical(self, "Erreur de chargement", message)
        self.open_connection()

    def open_account(self):
        """Compte du foyer : après une déconnexion, l'appli ne continue qu'avec une nouvelle connexion."""
        def sign_out():
            self._sync_now()  # dernières modifications envoyées au compte que l'on quitte
            self.cloud.sign_out()

        dlg = AccountDialog(self, self.cloud.email, True, None, sign_out,
                            vault_active=self.cloud.vault_key is not None, on_vault=lambda: self._activate_vault())
        if dlg.exec() != QDialog.Accepted or self.cloud.signed_in:
            return
        self.stop()
        if ask_account(self):
            self._after_login()
        else:
            self.close()

    def _activate_vault(self):
        if ask_vault(self):
            self.statusBar().showMessage("Abonnement IPTV partagé (chiffré) avec tes autres appareils", 6000)
            self._sync_soon()

    def _after_login(self):
        """Nouvelle connexion (peut-être à un autre compte) : profils du foyer, puis fenêtre rouverte."""
        self._save_progress()
        self.library.save()
        config.save(self.cfg, self.profile_id)
        try:
            sync.startup(self.cloud)
        except cloud.AuthError as e:
            self._session_lost(str(e))
            return
        self.switch_profile(config.current_profile(), save=False,
                            message=f"Connecté au compte {self.cloud.email}")

    def _session_lost(self, reason: str):
        """Session refusée par le serveur (mot de passe changé, compte désactivé ou retiré) : reconnexion."""
        self.sync_timer.stop()
        self.cloud.sign_out()
        self.stop()
        if ask_account(self, f"Reconnexion nécessaire : {reason}."):
            self._after_login()
        else:
            self.close()

    # ---- Synchro avec le compte du foyer ----------------------------------- #
    def _sync(self):
        """Un passage : lecture du serveur (thread), fusion ici, puis envoi de ce qui est plus récent ici."""
        if self._sync_busy or self._switched or not self.cloud.signed_in:
            return
        self._sync_busy = True
        with_root = self._sync_round % SYNC_ROOT_EVERY == 0
        self._sync_round += 1
        session, pid = self.cloud, self.profile_id

        def fetch():
            root = session.get_doc("") if with_root else None
            return with_root, root, session.get_doc(f"profiles/{pid}")

        run_async(cloud_task(fetch), self._sync_merge)

    def _sync_soon(self):
        """Synchro complète (liste des profils comprise) dans un instant : après un changement de profils."""
        self._sync_round -= self._sync_round % SYNC_ROOT_EVERY
        QTimer.singleShot(500, self._sync)

    def _sync_merge(self, result):
        if isinstance(result, cloud.CloudError):
            self._sync_failed(result)
            return
        if self._switched:
            self._sync_busy = False
            return
        with_root, root, doc = result
        writes = self._merge_profiles(root) if with_root else []
        if self._switched:  # profil en cours supprimé depuis un autre appareil : fenêtre rouverte
            return
        changed, lib_writes = sync.library_writes(self.library, doc, self.profile_id)
        if changed:
            self._library_changed()
        writes += lib_writes
        adopted, modified, fields = sync.source_writes(self.profile_id, self.cfg, doc, self.cloud.vault_key)
        writes = sync.with_fields(writes, self.profile_id, fields)
        if modified:
            config.save(self.cfg, self.profile_id)
        if adopted:  # ce profil n'avait pas d'abonnement sur ce PC : celui du compte (déchiffré)
            self.statusBar().showMessage("Abonnement IPTV récupéré depuis le compte du foyer", 6000)
            src = playlist.source_from_config(self.cfg)
            if src:
                self.catalog_sig = None
                self._load(src, use_cache=True, initial=True)
        if not writes:
            self._sync_done(None)
            return
        session = self.cloud
        run_async(cloud_task(lambda: session.commit(writes)), self._sync_done)

    def _merge_profiles(self, root) -> list:
        """Liste des profils du foyer : profils ajoutés, renommés ou supprimés sur un autre appareil."""
        name = self._profile()["name"]
        changed, writes, removed, added = sync.profiles_writes(self.cfg, root, self.cloud.uid)
        if not changed:
            return writes
        current_gone = self.profile_id in removed
        sync.apply_profiles(self.cfg, removed, added, None if current_gone else self.profile_id)
        if current_gone:
            session = self.cloud
            run_async(cloud_task(lambda: session.commit(writes)), lambda _: None)
            other = self.cfg["profiles"][0]["id"]
            config.save_common(self.cfg, other)
            self._sync_busy = False
            self.switch_profile(other, save=False,
                                message=f"Le profil « {name} » a été supprimé depuis un autre appareil.")
            return []
        config.save(self.cfg, self.profile_id)
        self._update_profile_btn()
        return writes

    def _sync_done(self, result):
        if isinstance(result, cloud.CloudError):
            self._sync_failed(result)
            return
        self._sync_busy = False
        self._sync_error_shown = False

    def _sync_failed(self, err: cloud.CloudError):
        self._sync_busy = False
        if self._switched:
            return
        if isinstance(err, (cloud.AuthError, cloud.Forbidden)):
            self._session_lost("l'accès de ce compte a été retiré" if isinstance(err, cloud.Forbidden) else str(err))
        elif not self._sync_error_shown:  # serveur injoignable : on réessaie au passage suivant, sans insister
            self._sync_error_shown = True
            self.statusBar().showMessage(f"Synchronisation impossible pour le moment ({err}). Nouvel essai dans "
                                         "30 s ; tes données sont gardées sur ce PC.", 8000)

    def _sync_now(self):
        """Envoie tout de suite les dernières positions (fermeture, changement de profil) : quelques s au plus."""
        if not self.cloud.signed_in:
            return
        try:
            if sync.sync_profile_now(self.cloud, self.library, self.profile_id, self.cfg, timeout=4)[2]:
                config.save(self.cfg, self.profile_id)
        except cloud.CloudError:
            pass  # envoyé au prochain lancement

    def _library_changed(self):
        """Favoris, reprises… modifiés (réinitialisation, synchro) : listes, accueil et fiche redessinés."""
        if self.view == "list":  # catégories masquées depuis un autre appareil
            self._populate_groups(self.tab_group.get(self.tab, ALL))
        if self.view == "list" and self.group_combo.currentData() in (FAV, RECENT):
            self._apply_filter()
        else:
            self.model.refresh()
        self._refresh_home()
        if self.details_item is not None:
            self._show_details(self.details_item)

    def set_omdb_key(self):
        key, ok = QInputDialog.getText(
            self, "Notes IMDb",
            "Clé API OMDb (gratuite sur https://www.omdbapi.com/apikey.aspx).\n"
            "Laisser vide pour n'afficher que la note du fournisseur.",
            QLineEdit.Normal, self.cfg.get("omdb_api_key", ""))
        if ok:
            self.cfg["omdb_api_key"] = key.strip()
            config.save(self.cfg, self.profile_id)
            for it in self.by_key.values():
                it.extra.pop("omdb", None)
            if self.details_item is not None:
                self._show_details(self.details_item)

    # ---- Onglets, vues et filtres ----------------------------------------- #
    def _set_tab(self, tab: str):
        if self.view != "list":
            self._leave_sub_view(restore=False)
        self.tab = tab
        idx = [k for k, _ in TABS].index(tab) + 1  # 0 = Accueil
        self.tabs.blockSignals(True)
        self.tabs.setCurrentIndex(idx)
        self.tabs.blockSignals(False)
        self.pages.setCurrentWidget(self.browse)
        self._populate_groups(self.tab_group.get(tab, ALL))
        self._apply_filter()


    def _on_tab_changed(self, index: int):
        if index == 0:
            self.show_home()
        elif 1 <= index <= len(TABS):
            self.show_browse(TABS[index - 1][0])
        elif index == SEARCH_TAB:
            self.show_search()

    def _on_group_changed(self, _index):
        if self.group_combo.currentData() == OTHERS:
            # « Autres » se déplie / se replie : la liste reste ouverte, la catégorie choisie ne change pas
            self._others_open = not self._others_open
            self._populate_groups(self.tab_group.get(self.tab, ALL))
            QTimer.singleShot(0, self._reopen_at_others)
            return
        if self.view == "list":
            self.tab_group[self.tab] = self.group_combo.currentData()
        self._apply_filter()
        if self.model.reorderable:
            self.statusBar().showMessage("Glisse un favori pour changer l'ordre (ou Ctrl+↑ / Ctrl+↓)", 6000)

    def _reopen_at_others(self):
        """Choix de « Autres » au clavier : la liste se rouvre positionnée sur « Autres »."""
        combo = self.group_combo
        combo.showPopup()
        i = combo.findData(OTHERS)
        if i >= 0:
            combo.view().scrollTo(combo.view().model().index(i, 0))
            combo.view().setCurrentIndex(combo.view().model().index(i, 0))

    def _hidden_groups(self) -> list[str]:
        """Catégories masquées de l'onglet (par profil, synchronisées), dans l'ordre du fournisseur."""
        return [g for g in self.tab_groups.get(self.tab, []) if self.library.is_hidden(self.tab, g)]

    def eventFilter(self, obj, event):
        if obj is not getattr(self, "_group_viewport", None):  # (aussi pendant la fermeture : liste détruite)
            return super().eventFilter(obj, event)
        view = self.group_combo.view()
        if obj is view.viewport() and event.type() == QEvent.ContextMenu:
            return True  # le menu est ouvert au relâchement du clic droit (ci-dessous)
        if obj is view.viewport() and event.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonRelease,
                                                        QEvent.MouseButtonDblClick):
            pos = event.position().toPoint()
            idx = view.indexAt(pos)
            if event.button() == Qt.RightButton:  # jamais un choix : seulement le menu masquer / réafficher
                if event.type() == QEvent.MouseButtonRelease and idx.isValid():
                    self._group_menu(idx.data(Qt.UserRole), view.viewport().mapToGlobal(pos), keep_open=True)
                return True
            if event.button() == Qt.LeftButton and idx.isValid() and idx.data(Qt.UserRole) == OTHERS:
                if event.type() == QEvent.MouseButtonRelease:
                    self._toggle_others()
                return True
        return super().eventFilter(obj, event)

    def _toggle_others(self):
        """Déplie / replie « Autres » sur place (liste ouverte, même position de défilement)."""
        combo = self.group_combo
        i = combo.findData(OTHERS)
        if i < 0:
            return
        hidden = self._hidden_groups()
        selected = self.tab_group.get(self.tab, ALL)
        if self._others_open and selected in hidden:
            return  # la catégorie affichée est dans « Autres » : il reste ouvert
        self._others_open = not self._others_open
        combo.blockSignals(True)
        combo.setItemText(i, ("▾  " if self._others_open else "▸  ") + f"Autres · {len(hidden)}")
        if self._others_open:
            for k, g in enumerate(hidden):
                combo.insertItem(i + 1 + k, "      " + g, g)
                combo.setItemData(i + 1 + k, QColor(ui.C["muted"]), Qt.ForegroundRole)
        else:
            for _ in hidden:
                combo.removeItem(i + 1)
        combo.blockSignals(False)
        # Pas de retour en haut de la liste : on défile juste ce qu'il faut pour montrer les catégories dépliées
        view = combo.view()
        last = i + (len(hidden) if self._others_open else 0)
        view.scrollTo(view.model().index(last, 0))
        view.scrollTo(view.model().index(i, 0))  # « Autres » reste visible

    def _group_menu(self, group, global_pos, keep_open: bool = False):
        """Clic droit sur une catégorie du fournisseur : la masquer (rangée dans « Autres ») ou la réafficher.
        keep_open : depuis la liste ouverte, qui reste ouverte (pour en masquer plusieurs à la suite)."""
        if self.view != "list" or group in (None, ALL, FAV, RECENT, OTHERS):
            return
        hidden = self.library.is_hidden(self.tab, group)
        menu = QMenu(self)
        menu.addAction("Réafficher la catégorie" if hidden else "Masquer la catégorie (rangée dans « Autres »)",
                       lambda: self._set_group_hidden(group, not hidden, keep_open))
        menu.exec(global_pos)

    def _set_group_hidden(self, group: str, hide: bool, keep_open: bool = False):
        """Masque / réaffiche une catégorie. keep_open : depuis la liste ouverte, qui reste ouverte au même endroit
        (pour en masquer plusieurs à la suite) : les lignes sont modifiées sur place, sans reconstruire la liste."""
        if not keep_open:
            self.group_combo.hidePopup()
        self.library.set_hidden(self.tab, group, hide)
        current = self.tab_group.get(self.tab, ALL)
        if hide and current == group:
            current = ALL
        self.tab_group[self.tab] = current
        if keep_open and self.group_combo.view().isVisible():
            self._update_groups_in_place(current)
        else:
            self._populate_groups(current)
        self._apply_filter()
        self.statusBar().showMessage(f"« {group} » " + ("rangée dans « Autres »" if hide else "réaffichée"), 5000)

    def _update_groups_in_place(self, selected):
        """Met la liste ouverte en accord avec les catégories masquées, ligne par ligne (défilement conservé)."""
        combo = self.group_combo
        bar = combo.view().verticalScrollBar()
        scroll = bar.value()
        hidden = self._hidden_groups()
        visible = [g for g in self.tab_groups.get(self.tab, []) if g not in hidden]
        open_ = bool(hidden) and (self._others_open or selected in hidden)
        rows = [(g, g, False) for g in visible]  # (texte, donnée, grisé) attendus après les entrées fixes
        if hidden:
            rows.append((("▾  " if open_ else "▸  ") + f"Autres · {len(hidden)}", OTHERS, False))
            if open_:
                rows += [("      " + g, g, True) for g in hidden]
        first = next(k for k in range(combo.count()) if combo.itemData(k) not in (ALL, FAV, RECENT))
        combo.blockSignals(True)
        k = first
        for text, data, muted in rows:
            if k < combo.count() and combo.itemData(k) == data and combo.itemText(k) == text:
                k += 1
                continue
            # ligne différente : on retire les lignes en trop jusqu'à retrouver la bonne, sinon on l'insère
            match = next((j for j in range(k, combo.count()) if combo.itemData(j) == data and combo.itemText(j) == text), None)
            if match is not None:
                for _ in range(match - k):
                    combo.removeItem(k)
            else:
                combo.insertItem(k, text, data)
                if muted:
                    combo.setItemData(k, QColor(ui.C["muted"]), Qt.ForegroundRole)
            k += 1
        while combo.count() > k:
            combo.removeItem(k)
        i = combo.findData(selected)
        if combo.currentIndex() != (i if i >= 0 else 0):  # sinon la liste défilerait jusqu'à la sélection
            combo.setCurrentIndex(i if i >= 0 else 0)
        combo.blockSignals(False)
        bar.setValue(scroll)
        QTimer.singleShot(0, lambda: bar.setValue(scroll))

    def _populate_groups(self, selected=ALL):
        combo = self.group_combo
        combo.blockSignals(True)
        combo.clear()
        if self.view == "list":
            combo.addItem("Toutes les catégories", ALL)
            combo.addItem("★ Favoris", FAV)
            if self.tab in ("movie", "series"):
                combo.addItem("🕘 Vu récemment", RECENT)
            hidden = self._hidden_groups()
            groups = [g for g in self.tab_groups.get(self.tab, []) if g not in hidden]
        else:
            combo.addItem("Toutes les saisons" if self.view == "episodes" else "Tous les jours", ALL)
            groups = dict.fromkeys(i.group_label for i in self.view_items)
            hidden = []
        for g in groups:
            combo.addItem(g, g)
        if hidden:  # catégories masquées : sous « Autres », en grisé, quand il est déplié
            open_ = self._others_open or selected in hidden
            combo.addItem(("▾  " if open_ else "▸  ") + f"Autres · {len(hidden)}", OTHERS)
            if open_:
                for g in hidden:
                    combo.addItem("      " + g, g)
                    combo.setItemData(combo.count() - 1, QColor(ui.C["muted"]), Qt.ForegroundRole)
        i = combo.findData(selected)
        combo.setCurrentIndex(i if i >= 0 else 0)
        combo.blockSignals(False)

    def _base_items(self) -> list[playlist.Item]:
        return self.by_tab.get(self.tab, []) if self.view == "list" else self.view_items

    def _apply_filter(self):
        text = _norm(self.search.text().strip())
        group = self.group_combo.currentData()
        base = self._base_items()
        if self.view == "list" and group == FAV:
            items = [self.by_key[k] for k in self.library.favorite_keys(self.tab) if k in self.by_key]
        elif self.view == "list" and group == RECENT:
            items = [self.by_key[k] for k in self.library.recent_keys(self.tab) if k in self.by_key]
        elif group:
            items = [i for i in base if i.group_label == group]
        elif self.view == "list" and (hidden := set(self._hidden_groups())):
            items = [i for i in base if i.group_label not in hidden]  # « Toutes » sans les catégories masquées
        else:
            items = base
        if text:
            items = [i for i in items if text in self._norm_name(i)]

        poster = self.view == "episodes" or (self.view == "list" and self.tab in ("movie", "series"))
        self.list_delegate.set_mode(poster)
        keep = self.details_item.key if self.details_item is not None else None
        # Ordre des favoris modifiable, sauf pendant une recherche (on ne verrait pas tous les voisins)
        self.list.set_reorderable(self.view == "list" and group == FAV and not text and len(items) > 1)
        self.model.set_items(items)
        self.count_label.setText(f"{len(items)} / {len(base)}")
        if not self._select_current() and keep:
            self._select_key(keep)
        if self.list.currentIndex().row() < 0:
            self._show_details(None)

    @staticmethod
    def _norm_name(it: playlist.Item) -> str:
        if not it.norm:
            it.norm = _norm(it.name)
        return it.norm

    def _select_key(self, key: str, center=False) -> bool:
        for row, it in enumerate(self.model.items):
            if it.key == key:
                idx = self.model.index(row)
                self.list.setCurrentIndex(idx)
                self._scroll_to(QPersistentModelIndex(idx), center)
                return True
        return False

    def _scroll_to(self, pidx, center: bool, tries: int = 0):
        """Fait défiler jusqu'à la ligne. La liste étant mise en page par lots, une ligne lointaine
        n'est atteignable qu'une fois son lot calculé : on réessaie tant qu'elle n'est pas affichée."""
        if not pidx.isValid():
            return
        idx = self.model.index(pidx.row())
        self.list.scrollTo(idx, QListView.PositionAtCenter if center else QListView.EnsureVisible)
        if tries < 200 and not self.list.viewport().rect().intersects(self.list.visualRect(idx)):
            QTimer.singleShot(5, lambda: self._scroll_to(pidx, center, tries + 1))

    def _select_current(self) -> bool:
        return self.current is not None and self._select_key(self.current.key)

    # ---- Recherche (page à part : bandes Films et Séries) ---------------------- #
    def show_search(self):
        self.pages.setCurrentWidget(self.search_page)
        self.tabs.blockSignals(True)
        self.tabs.setCurrentIndex(SEARCH_TAB)
        self.tabs.blockSignals(False)
        self._run_search()
        self.search_page.field.setFocus()
        self.search_page.field.selectAll()
        self._update_now_playing()

    def _run_search(self):
        """Films et séries dont le nom contient le texte (sans accents) : une bande chacun."""
        text = _norm(self.search_page.field.text().strip())
        if len(text) < SEARCH_MIN:
            self.search_page.set_results(None, None, "Tape au moins 2 lettres pour chercher un film ou une série.")
            return
        lib = self.library

        def tiles(kind):
            found = [i for i in self.by_tab.get(kind, []) if text in self._norm_name(i)]
            out = []
            for it in found[:SEARCH_MAX]:
                sub = " · ".join(x for x in (it.year, f"★ {it.rating}" if it.rating else "") if x) or it.group_label
                pos, length = lib.resume_position(it.key), lib.progress.get(it.key, {}).get("len", 0)
                out.append(ui.Tile(it, it.name, sub, pos / length if pos and length else -1))
            return out, len(found)

        (films, n_films), (series, n_series) = tiles("movie"), tiles("series")
        more = " (300 premiers affichés)" if max(n_films, n_series) > SEARCH_MAX else ""
        self.search_page.set_results(
            films, series, f"{n_films} film{'s' if n_films > 1 else ''}, {n_series} série{'s' if n_series > 1 else ''}{more}")

    def _open_from_search(self, kind: str, it: playlist.Item):
        """Clic sur un résultat : sa fiche dans une fenêtre par-dessus la recherche (Échap : retour aux résultats).
        Descriptif du film / épisodes de la série chargés en arrière-plan, affiche dès qu'elle arrive."""
        it = self.by_key.get(it.key, it)  # catalogue actualisé depuis la recherche : la version à jour
        dlg = ItemCardDialog(self, "Film" if kind == "movie" else "Série")
        state = {"open": True, "failed": False}

        def refresh(_=None):
            if state["open"]:
                self._fill_card(dlg, kind, it, state["failed"])

        def on_image(url):
            if url == it.logo:
                refresh()

        def failed(_msg):
            state["failed"] = True
            refresh()

        self.images.loaded.connect(on_image)
        refresh()
        need_info = self.client is not None and kind == "movie" and not it.info_loaded
        need_eps = self.client is not None and kind == "series" and it.episodes is None
        if need_info or need_eps:
            client = self.client
            run_async(lambda: client.fill_movie_info(it) if need_info else client.load_episodes(it), refresh, failed)
        elif kind == "series" and it.episodes is None:
            it.episodes = []  # playlist M3U sans API : rien à charger
            refresh()
        dlg.exec()
        state["open"] = False
        self.images.loaded.disconnect(on_image)

    def _card_tracks(self, dlg, kind: str, it: playlist.Item, failed: bool):
        """Langues et sous-titres dans la fiche de la recherche (même fonctionnement que la fiche des onglets)."""
        target = self._lang_target(it) if (kind == "movie" or self.client is not None) else None
        if target is None:
            dlg.tracks.set_message("" if kind == "movie" or it.episodes == [] or failed
                                   else "Recherche des langues disponibles…")
            return
        found = self._track_cache.get(target.url)
        if not found:
            if target.url in dlg.probed:
                dlg.tracks.set_message("Langues non disponibles pour ce fichier.")
                return
            dlg.probed.add(target.url)
            dlg.tracks.set_message("Recherche des langues disponibles…")
            self._probe(target.url, lambda _found: dlg.isVisible() and self._fill_card(dlg, kind, it, failed))
            return

        def audio(t):
            dlg.accept()
            self.show_browse(kind)
            self._launch_with_audio(it, target, t)

        def sub(t):
            self.library.set_pref(self._pref_key(target), "spu", "off" if t is None else t.pref())
            self._fill_card(dlg, kind, it, failed)

        dlg.tracks.set_entries(*self._track_entries(target, found, audio, sub))

    def _fill_card(self, dlg, kind: str, it: playlist.Item, failed: bool):
        lib = self.library
        if not hasattr(dlg, "probed"):
            dlg.probed = set()  # fichiers dont les pistes ont déjà été demandées
        self._card_tracks(dlg, kind, it, failed)
        pm = self.images.pixmap(it.logo, dlg.poster.width(), dlg.poster.height(), large=True) if it.logo else None
        dlg.set_poster(pm, "…" if it.logo and not self.images.has_failed(it.logo, True) else "Pas d'image")
        meta = [_esc(x) for x in (it.year, it.genre, it.duration) if x]
        if it.imdb_rating:
            meta.append(f"<b>IMDb ★ {_esc(it.imdb_rating)}</b>")
        elif it.rating:
            meta.append(f"★ {_esc(it.rating)}/10")
        credits = []
        if it.director:
            credits.append(f"<b>Réalisation</b> : {_esc(it.director)}")
        if it.cast:
            credits.append(f"<b>Avec</b> : {_esc(it.cast)}")
        dlg.set_info(it.name, " · ".join(meta), self._plot_html(it), "<br>".join(credits))

        def close_then(action):
            return lambda: (dlg.accept(), action())

        specs = []
        if kind == "movie":
            pos = lib.resume_position(it.key)
            specs.append((f"▶ Reprendre à {fmt_time(pos)}" if pos else "▶ Lire", "primary",
                          close_then(lambda: self._play_from_search("movie", it, None, True)), None, True))
            if pos:
                specs.append(("Depuis le début", "secondary",
                              close_then(lambda: self._play_from_search("movie", it, None, False)), None, True))
        elif it.episodes:
            target = self._series_resume_target(it)
            ep, pos = target if target else (it.episodes[0], 0)
            label = f"S{ep.season:02d}E{ep.episode:02d}" if (ep.season or ep.episode) else ep.name
            specs.append((f"▶ Reprendre {label} à {fmt_time(pos)}" if pos else f"▶ Lire {label}", "primary",
                          close_then(lambda: self._play_from_search("series", it, ep, True)), None, True))
        else:
            text = "Épisodes indisponibles" if failed or it.episodes == [] else "Chargement des épisodes…"
            specs.append((text, "primary", None, None, False))
        fav = lib.is_favorite(kind, it.key)

        def toggle_fav():
            lib.toggle_favorite(kind, it.key)
            self._library_changed()
            self._fill_card(dlg, kind, it, failed)

        specs.append(("★  Favori" if fav else "☆  Favori", "secondary", toggle_fav, None, True))
        specs.append(("", "secondary", None, "download", kind == "movie" or bool(it.episodes)))
        specs.append(("Fiche complète", "secondary", close_then(lambda: self._show_in_tab(kind, it)), None, True))
        buttons = dlg.set_buttons(specs)
        dl = buttons[-2]
        dl.setToolTip("Télécharger le film sur le disque" if kind == "movie"
                      else "Télécharger une saison (ou toute la série) sur le disque")
        dl.clicked.connect(lambda: self._download_menu(it, dl))

    def _play_from_search(self, kind: str, it: playlist.Item, ep, resume: bool):
        """Lecture depuis la fiche de la recherche (comme depuis l'accueil : dans l'onglet Films / Séries)."""
        self.show_browse(kind)
        if kind == "movie":
            self._select_key(it.key, center=True)
            self.play_item(it, resume=resume)
        else:
            self.open_series(it)
            self.play_item(ep, resume=resume)

    def _show_in_tab(self, kind: str, it: playlist.Item):
        """« Fiche complète » : la fiche dans l'onglet Films / Séries (langues, épisodes…)."""
        it = self.by_key.get(it.key, it)
        self.show_browse(kind)
        if self.view != "list":
            self._leave_sub_view(restore=False)
        self.search.blockSignals(True)
        self.search.clear()  # filtre de l'onglet : rien, pour retrouver le résultat dans la liste
        self.search.blockSignals(False)
        self.tab_group[kind] = ALL
        self._populate_groups(ALL)
        self._apply_filter()
        self._select_key(it.key, center=True)
        self._show_details(it)

    def _focus_search(self):
        if self._fullscreen:
            return
        self.search.setFocus()
        self.search.selectAll()

    def _enter_sub_view(self, view: str, parent: playlist.Item, items: list, select_key=None):
        if self.view == "list":
            self.back_state = {"group": self.group_combo.currentData(), "search": self.search.text(),
                               "key": parent.key}
        self.view = view
        self.view_parent = parent
        self.view_items = items
        self.nav_title.setText(parent.name)
        self.nav_row.show()
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self._populate_groups(ALL)
        self._apply_filter()
        if select_key and self._select_key(select_key, center=True):
            pass
        elif self.list.currentIndex().row() < 0 and self.model.items:
            self.list.setCurrentIndex(self.model.index(0))
        self.list.setFocus()

    def _leave_sub_view(self, restore=True):
        self.view = "list"
        self.view_parent = None
        self.view_items = []
        self.nav_row.hide()
        if restore:
            st = self.back_state
            self.search.blockSignals(True)
            self.search.setText(st.get("search", ""))
            self.search.blockSignals(False)
            self._populate_groups(st.get("group", ALL))
            self._apply_filter()
            if st.get("key"):
                self._select_key(st["key"], center=True)
            self.list.setFocus()

    def go_back(self):
        if self.view != "list" and not self._fullscreen:
            self._leave_sub_view()

    # ---- Libellés et icônes de la liste ----------------------------------- #
    def _row(self, it: playlist.Item) -> "ui.Row":
        """Ce qu'affiche une ligne de liste : titre, ligne d'infos, progression et badges."""
        lib = self.library
        title, sub, progress = it.name, "", -1.0
        if it.kind == "episode":
            label = playlist.episode_label(it)
            code, sep, rest = label.partition(" · ")
            title = rest or label
            sub = " · ".join(x for x in ((code if sep else ""), it.duration) if x)
        elif it.kind == "program":
            title = it.extra.get("title") or it.name
            hours = f"{time.strftime('%H:%M', time.localtime(it.start))}–{time.strftime('%H:%M', time.localtime(it.end))}"
            sub = f"{xtream.day_label(it.start)} · {hours}" + (" · en cours" if it.end > time.time() else "")
        elif it.kind == "live":
            sub = it.group_label
            if self.tab == "replay" and self.view == "list":
                sub += f" · replay {it.archive_days} j"
        else:  # film, série
            bits = [it.year, f"★ {it.rating}" if it.rating else "", it.genre]
            sub = " · ".join(b for b in bits if b) or it.group_label
            entry = lib.recent.get(it.key) if it.kind == "series" else None
            if entry:
                sub = "En cours" + (f" · {entry['last_label']}" if entry.get("last_label") else "")
        if it.kind in RESUMABLE:
            pos = lib.resume_position(it.key)
            length = lib.progress.get(it.key, {}).get("len", 0)
            if pos and length:
                progress = pos / length
        return ui.Row(
            title=title, subtitle=sub, progress=progress,
            fav=self.view == "list" and lib.is_favorite(self.tab, it.key),
            playing=self.current is not None and it.key == self.current.key and self._is_playing(),
            watched=it.kind == "episode" and lib.is_watched(it),
        )

    def _on_images_ready(self):
        self.list.viewport().update()
        if self.pages.currentWidget() is self.home:
            self.home.refresh_images()
        if self.details_item is not None:
            self._update_poster(self.details_item)

    # ---- Fiche détaillée --------------------------------------------------- #
    def _on_current_changed(self, current, _previous):
        if current.isValid() and current.row() < len(self.model.items):
            self._show_details(self.model.item(current.row()))
        else:
            self._show_details(None)

    def _show_details(self, it: playlist.Item | None):
        self.details_item = it
        d = self.details
        self._update_right()
        if it is None or it.kind == "live":
            return
        d.verticalScrollBar().setValue(0)
        d.title.setText(playlist.episode_label(it) if it.kind == "episode" else it.name)
        d.plot.setText(self._plot_html(it))

        meta = []
        if it.kind == "program":
            meta.append(xtream.day_label(it.start))
        if it.kind == "episode" and (it.season or it.episode):
            meta.append(f"Saison {it.season} · épisode {it.episode}")
        meta += [_esc(x) for x in (it.year, it.genre, it.duration) if x]
        if it.imdb_rating:
            meta.append(f"<b>IMDb ★ {_esc(it.imdb_rating)}</b>")
        elif it.rating:
            meta.append(f"★ {_esc(it.rating)}/10")
        d.meta.setText(" · ".join(meta))
        credits = []
        if it.director:
            credits.append(f"<b>Réalisation</b> : {_esc(it.director)}")
        if it.cast:
            credits.append(f"<b>Avec</b> : {_esc(it.cast)}")
        d.credits.setText("<br>".join(credits))
        self._update_poster(it)

        lib = self.library
        d.alt_btn.hide()
        d.fav_btn.setVisible(it.kind in ("movie", "series"))
        d.dl_btn.setVisible(it.kind in ("movie", "series", "episode"))
        d.dl_btn.setToolTip({"movie": "Télécharger le film sur le disque",
                             "series": "Télécharger une saison (ou toute la série) sur le disque",
                             "episode": "Télécharger l'épisode sur le disque"}.get(it.kind, ""))
        if it.kind in ("movie", "series"):
            fav = lib.is_favorite(it.kind, it.key)
            d.fav_btn.setText("★  Favori" if fav else "☆  Favori")
            d.fav_btn.setToolTip("Retirer des favoris  (Ctrl+D)" if fav else "Ajouter aux favoris  (Ctrl+D)")
        if it.kind in RESUMABLE:
            pos = lib.resume_position(it.key)
            d.play_btn.setText(f"▶ Reprendre à {fmt_time(pos)}" if pos else "▶ Lire")
            if pos:
                d.alt_btn.setText("Depuis le début")
                d.alt_btn.show()
        elif it.kind == "series":
            target = self._series_resume_target(it)
            if target is not None:
                ep, pos = target
                label = f"S{ep.season:02d}E{ep.episode:02d}"
                d.play_btn.setText(f"▶ Reprendre {label} à {fmt_time(pos)}" if pos else f"▶ Lire {label}")
                d.alt_btn.setText("Voir les épisodes")
                d.alt_btn.show()
            else:
                d.play_btn.setText("Voir les épisodes")
        else:  # programme de replay
            d.play_btn.setText("▶ Lire")

        self._show_tracks(it)
        self._fetch_details(it)

    def _lang_target(self, it: playlist.Item):
        """Fichier dont la fiche montre les langues : le film, l'épisode, ou pour une série l'épisode
        que « Lire » lancerait (le premier si elle n'est pas commencée)."""
        if it.kind in ("movie", "episode"):
            return it
        if it.kind == "series" and it.episodes:
            target = self._series_resume_target(it)
            return target[0] if target else it.episodes[0]
        return None

    def _show_tracks(self, it: playlist.Item):
        d = self.details
        if it.kind not in ("movie", "episode", "series") or (it.kind == "series" and self.client is None):
            d.set_tracks_message("")
            return
        target = self._lang_target(it)
        found = self._track_cache.get(target.url) if target is not None else None
        if not found:
            d.set_tracks_message("Recherche des langues disponibles…")
            self.tracks_timer.start()
            return
        d.set_tracks(*self._track_entries(target, found, lambda t: self._launch_with_audio(it, target, t),
                                          lambda t: self._choose_subtitles(it, target, t)))

    def _track_entries(self, target: playlist.Item, found: list, on_audio, on_sub):
        """Boutons de langue (on_audio(piste) : lecture dans cette langue) et de sous-titres (on_sub(piste ou
        None)) d'un fichier, avec le choix mémorisé coché. Retourne (audio, sous-titres, note)."""
        pref = self.track_prefs.get(self._pref_key(target), {})
        what = "le film" if target.kind == "movie" else f"S{target.season:02d}E{target.episode:02d}"
        audio = [(t.label, tracklib.is_pref(t, pref.get("audio")), f"Lancer {what} en {t.label}",
                  lambda t=t: on_audio(t)) for t in found if t.kind == "audio"]
        subs = [t for t in found if t.kind == "spu"]
        sub_entries = [("Aucun", pref.get("spu") == "off", "Lecture sans sous-titres",
                        lambda: on_sub(None))] if subs else []
        sub_entries += [(t.label, tracklib.is_pref(t, pref.get("spu")), "Sous-titres de la lecture",
                         lambda t=t: on_sub(t)) for t in subs]
        note = "Le choix est conservé pour les épisodes suivants." if target.kind == "episode" else ""
        return audio, sub_entries, note

    def _probe_details(self):
        """Lit les pistes du fichier de la fiche affichée (et les épisodes d'une série si besoin)."""
        it = self.details_item
        if it is None or it.kind not in ("movie", "episode", "series"):
            return
        if it.kind == "series" and it.episodes is None:
            if self.client is None or it.extra.get("_eps_loading"):
                return
            it.extra["_eps_loading"] = True
            client = self.client

            def loaded(_result=None):
                it.extra["_eps_loading"] = False
                if self.details_item is it:
                    self._show_details(it)  # bouton « Lire SxxEyy » et langues de cet épisode

            run_async(lambda: client.load_episodes(it), loaded, loaded)
            return
        target = self._lang_target(it)
        if target is None:
            self.details.set_tracks_message("")
            return

        def done(found):
            if self.details_item is not it:
                return
            if found:
                self._show_tracks(it)
            else:
                self.details.set_tracks_message("Langues non disponibles pour ce fichier.")

        self._probe(target.url, done)

    def _launch_with_audio(self, it: playlist.Item, target: playlist.Item, t):
        """Bouton de langue de la fiche : mémorise la langue puis lance le film / l'épisode."""
        self.library.set_pref(self._pref_key(target), "audio", t.pref())
        if it.kind == "series":
            self.open_series(it)  # vue des épisodes, comme un double-clic
            self._select_key(target.key)
        self.play_item(target, resume=True)

    def _choose_subtitles(self, it: playlist.Item, target: playlist.Item, t):
        self.library.set_pref(self._pref_key(target), "spu", "off" if t is None else t.pref())
        self._show_tracks(it)

    def _plot_html(self, it: playlist.Item) -> str:
        """Résumé à afficher. Beaucoup d'épisodes n'en ont pas chez les fournisseurs : on montre alors
        celui de la série ; s'il n'y a rien du tout, on le dit plutôt que de laisser un vide."""
        def html(text):
            return _esc(text.strip()).replace("\n", "<br>")

        note = f"<span style='color:{ui.C['muted']}; font-style:italic'>{{}}</span>"
        if it.plot:
            return html(it.plot)
        if it.extra.get("_loading"):
            return note.format("Chargement du descriptif…")
        if it.kind == "episode" and it.parent is not None and it.parent.plot:
            return note.format("Pas de résumé pour cet épisode. Résumé de la série :") + "<br>" + html(it.parent.plot)
        msg = "Aucun résumé n'est fourni pour ce titre."
        if it.kind in ("movie", "series") and not self.cfg.get("omdb_api_key"):
            msg += " Une clé OMDb (menu ☰ > Clé OMDb) permet d'en récupérer un, en anglais."
        return note.format(msg)

    def _update_poster(self, it: playlist.Item):
        lbl = self.details.poster
        # Épisode : l'affiche de la série (les images d'épisode sont des captures en largeur)
        url = it.parent.logo if it.kind == "episode" and it.parent is not None and it.parent.logo else it.logo
        pm = self.images.pixmap(url, lbl.width(), lbl.height(), large=True) if url else None
        if pm is not None:
            lbl.setPixmap(pm)
        else:
            lbl.setPixmap(QPixmap())
            lbl.setText("…" if url and not self.images.has_failed(url, True) else "Pas d'image")

    def _fetch_details(self, it: playlist.Item):
        """Récupère en arrière-plan le descriptif complet et la note IMDb si besoin."""
        key = self.cfg.get("omdb_api_key", "")
        need_info = self.client is not None and it.kind == "movie" and not it.info_loaded
        need_eps = (self.client is not None and it.kind == "series" and it.episodes is None
                    and it.key in self.library.recent)
        need_omdb = bool(key) and it.kind in ("movie", "series") and "omdb" not in it.extra
        if it.extra.get("_loading") or not (need_info or need_eps or need_omdb):
            return
        it.extra["_loading"] = True
        client = self.client

        def job():
            errors = []
            if need_info:
                try:
                    client.fill_movie_info(it)
                except Exception as exc:
                    errors.append(str(exc))
            if need_eps:
                try:
                    client.load_episodes(it)
                except Exception as exc:
                    errors.append(str(exc))
            if need_omdb:
                title, year = playlist.clean_title(it.name)
                try:
                    r = omdb.lookup(key, [it.extra.get("o_name", ""), title], it.year or year, it.kind)
                    it.imdb_rating = r.get("rating", "")
                    it.imdb_id = r.get("imdb_id", "")
                    it.plot = it.plot or r.get("plot", "")
                    it.logo = it.logo or r.get("poster", "")
                    it.extra["omdb"] = True
                except omdb.InvalidKey as exc:
                    errors.append(str(exc))
                except Exception as exc:
                    it.extra["omdb"] = True  # pas de nouvelle tentative pendant la session
                    errors.append(str(exc))
            return errors

        def done(errors):
            it.extra["_loading"] = False
            if errors:
                self.statusBar().showMessage("Descriptif : " + errors[0], 6000)
            if self.details_item is it:
                self._show_details(it)
            self.model.refresh()

        run_async(job, done)
        if self.details_item is it and not it.plot:
            self.details.plot.setText(self._plot_html(it))

    def _details_action(self, which: str):
        it = self.details_item
        if it is None:
            return
        if which == "fav":
            self._toggle_favorite(it)
        elif it.kind in RESUMABLE:
            self.play_item(it, resume=(which == "play"))
        elif it.kind == "series":
            target = self._series_resume_target(it)
            if which == "play" and target is not None:
                self.open_series(it, play_resume=True)
            else:
                self.open_series(it)
        elif it.kind == "program":
            self.play_item(it)

    # ---- Téléchargements sur le disque ----------------------------------------- #
    def _details_download(self):
        it = self.details_item
        if it is None:
            return
        if it.kind in ("movie", "episode"):
            self._queue_downloads([it])
            return
        if it.kind != "series":
            return
        if it.episodes is None:  # épisodes pas encore chargés : on les charge, puis on propose les saisons
            if self.client is None:
                return
            self.statusBar().showMessage(f"Chargement des épisodes de {it.name}…", 4000)
            client = self.client
            run_async(lambda: client.load_episodes(it),
                      lambda _r=None: self.details_item is it and self._details_download(),
                      lambda msg: self.statusBar().showMessage(f"Épisodes indisponibles : {msg}", 6000))
            return
        self._download_menu(it, self.details.dl_btn)

    def _download_menu(self, it: playlist.Item, btn):
        """Film / épisode : en file aussitôt ; série : menu des saisons (ou toute la série) sous le bouton btn."""
        if it.kind in ("movie", "episode"):
            self._queue_downloads([it])
            return
        eps = it.episodes
        if not eps:
            self.statusBar().showMessage("Aucun épisode à télécharger", 4000)
            return
        menu = QMenu(self)
        for s in sorted({e.season for e in eps}):
            n = sum(1 for e in eps if e.season == s)
            menu.addAction(f"Saison {s}  ·  {n} épisode{'s' if n > 1 else ''}",
                           lambda s=s: self._queue_downloads([e for e in eps if e.season == s]))
        menu.addSeparator()
        menu.addAction(f"Toute la série  ·  {len(eps)} épisodes", lambda: self._queue_downloads(list(eps)))
        menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    def _download_dir(self) -> Path | None:
        """Dossier des téléchargements ; demandé au premier téléchargement (Téléchargements, disque externe…)."""
        folder = self.cfg.get("download_dir", "")
        if folder and Path(folder).is_dir():
            return Path(folder)
        return self._choose_download_dir(self)

    def _choose_download_dir(self, parent) -> Path | None:
        start = self.cfg.get("download_dir") or str(Path.home() / "Downloads")
        folder = QFileDialog.getExistingDirectory(parent, "Où enregistrer les films et séries téléchargés ?", start)
        if not folder:
            return None
        self.cfg["download_dir"] = folder
        config.save(self.cfg, self.profile_id)
        return Path(folder)

    def _download_path(self, base: Path, it: playlist.Item) -> Path:
        """Film : « Titre (année).ext » ; épisode : « Série/Saison 01/Série - S01E02 - Titre.ext »."""
        from .downloads import safe_name
        ext = it.ext or Path(it.url.split("?")[0]).suffix.lstrip(".") or "mp4"
        if it.kind == "episode" and it.parent is not None:
            show, _ = playlist.clean_title(it.parent.name)
            label = playlist.episode_label(it).replace(" · ", " - ")
            return (base / safe_name(show) / f"Saison {it.season:02d}"
                    / f"{safe_name(f'{show} - {label}')}.{ext}")
        title, year = playlist.clean_title(it.name)
        year = year or it.year
        return base / f"{safe_name(f'{title} ({year})' if year else title)}.{ext}"

    def _queue_downloads(self, items: list):
        base = self._download_dir()
        if base is None:
            return
        entries = []
        for it in items:
            if not it.url:
                continue
            label = it.name if it.kind == "movie" else f"{it.parent.name if it.parent else ''} · {playlist.episode_label(it)}"
            entries.append((label, it.url, self._download_path(base, it)))
        added = self.downloads.add(entries)
        if added:
            self.statusBar().showMessage(
                f"{added} téléchargement{'s' if added > 1 else ''} ajouté{'s' if added > 1 else ''} → {base}", 6000)
        else:
            self.statusBar().showMessage("Déjà téléchargé (ou déjà en file d'attente)", 5000)

    def open_downloads(self):
        folder = self.cfg.get("download_dir") or str(Path.home() / "Downloads")
        DownloadsDialog(self, self.downloads, folder,
                        lambda parent: (str(p) if (p := self._choose_download_dir(parent)) else None)).exec()

    def _update_dl_btn(self):
        text = self.downloads.summary()
        self.dl_btn.setText(text)
        self.dl_btn.setVisible(bool(text))

    def _series_resume_target(self, show: playlist.Item):
        """(épisode à reprendre, position) pour une série en cours, sinon None."""
        entry = self.library.recent.get(show.key)
        eps = show.episodes
        if not entry or not eps:
            return None
        last = entry.get("last_ep")
        idx = next((i for i, e in enumerate(eps) if e.key == last), None)
        if idx is None:
            return None
        pos = self.library.resume_position(last)
        if pos:
            return eps[idx], pos
        watched = self.library.watched_keys(show.key)
        if last not in watched:
            return eps[idx], 0  # épisode lancé moins de 15 s : on le relance depuis le début
        for e in eps[idx + 1:] + eps[:idx]:
            if e.key not in watched:
                return e, self.library.resume_position(e.key)
        return None

    # ---- Favoris ----------------------------------------------------------- #
    def _fav_tab(self, it: playlist.Item):
        if it.kind == "episode":
            return "series", it.parent
        if it.kind == "program":
            return None, None
        return (self.tab if self.view == "list" else it.kind), it

    def _toggle_favorite(self, it: playlist.Item):
        tab, target = self._fav_tab(it)
        if target is None:
            return
        added = self.library.toggle_favorite(tab, target.key)
        self.statusBar().showMessage(
            f"{target.name} : {'ajouté aux' if added else 'retiré des'} favoris", 4000)
        if self.view == "list" and self.group_combo.currentData() == FAV:
            self._apply_filter()
        else:
            self.model.refresh()
        if self.details_item is not None:
            self._show_details(self.details_item)

    def _move_favorite(self, row: int, dest: int):
        """★ Favoris : la ligne row passe à la position d'insertion dest (0 = en tête, len = à la fin)."""
        items = self.model.items
        if not self.model.reorderable or not 0 <= row < len(items) or dest in (row, row + 1):
            return
        key = items[row].key
        self.library.move_favorite(self.tab, key, items[dest].key if dest < len(items) else None)
        self._apply_filter()
        self._select_key(key)
        if self.tab in ("live", "replay"):  # bandes de l'accueil dans le même ordre
            self._refresh_home()

    def move_favorite_selected(self, delta: int):
        idx = self.list.currentIndex()
        if self.model.reorderable and idx.isValid() and 0 <= idx.row() + delta < len(self.model.items):
            self._move_favorite(idx.row(), idx.row() + (delta if delta < 0 else delta + 1))

    def toggle_favorite_selected(self):
        idx = self.list.currentIndex()
        if idx.isValid():
            self._toggle_favorite(self.model.item(idx.row()))

    def _context_menu(self, pos):
        idx = self.list.indexAt(pos)
        if not idx.isValid():
            return
        it = self.model.item(idx.row())
        menu = QMenu(self)
        lib = self.library
        if self.tab == "replay" and it.kind == "live":
            menu.addAction("Voir les replays", lambda: self.open_programs(it))
            menu.addAction("Regarder en direct", lambda: self.play_item(it))
        elif it.kind == "series":
            menu.addAction("Voir les épisodes", lambda: self.open_series(it))
        else:
            menu.addAction("Lire", lambda: self.play_item(it))
            if it.kind in RESUMABLE and lib.resume_position(it.key):
                menu.addAction("Lire depuis le début", lambda: self.play_item(it, resume=False))
        tab, target = self._fav_tab(it)
        if target is not None:
            fav = lib.is_favorite(tab, target.key)
            menu.addAction(("Retirer des favoris" if fav else "Ajouter aux favoris") + "\tCtrl+D",
                           lambda: self._toggle_favorite(it))
        if it.kind == "episode":
            if lib.is_watched(it):
                menu.addAction("Marquer comme non vu", lambda: self._set_watched(it, False))
            else:
                menu.addAction("Marquer comme vu", lambda: self._set_watched(it, True))
        if it.kind in ("movie", "episode") and it.url:
            menu.addAction("Télécharger " + ("le film" if it.kind == "movie" else "l'épisode"),
                           lambda: self._queue_downloads([it]))
        recent_key = it.parent.key if it.kind == "episode" else it.key
        if recent_key in lib.recent:
            menu.addAction("Retirer de « Vu récemment »", lambda: self._remove_recent(recent_key))
        if self.model.reorderable:
            row, last = idx.row(), len(self.model.items) - 1
            menu.addSeparator()
            if row > 0:
                menu.addAction("Mettre en premier", lambda: self._move_favorite(row, 0))
                menu.addAction("Monter\tCtrl+↑", lambda: self.move_favorite_selected(-1))
            if row < last:
                menu.addAction("Descendre\tCtrl+↓", lambda: self.move_favorite_selected(+1))
                menu.addAction("Mettre en dernier", lambda: self._move_favorite(row, last + 1))
        menu.exec(self.list.viewport().mapToGlobal(pos))

    def _set_watched(self, ep: playlist.Item, watched: bool):
        lib = self.library
        if watched:
            lib.update(ep, 0, 0, finished=True)
        else:
            lib.set_unwatched(ep)
        lib.save()
        self.model.refresh()

    def _remove_recent(self, key: str):
        it = self.by_key.get(key)
        eps = [e.key for e in (it.episodes or [])] if it is not None else []
        self.library.remove_recent(key, eps)
        if self.view == "list" and self.group_combo.currentData() == RECENT:
            self._apply_filter()
        else:
            self.model.refresh()

    # ---- Ouverture des séries et des replays ------------------------------ #
    def _on_activated(self, index):
        if not index.isValid():
            return
        it = self.model.item(index.row())
        if it.kind == "series":
            self.open_series(it)
        elif it.kind == "live" and self.tab == "replay" and self.view == "list":
            self.open_programs(it)
        else:
            self.play_item(it)

    def open_series(self, show: playlist.Item, play_resume=False):
        self._open_token = show.key
        if show.episodes is not None:
            self._show_series(show, play_resume)
            return
        if self.client is None:
            show.episodes = []
            self._show_series(show, play_resume)
            return
        self.statusBar().showMessage(f"Chargement des épisodes : {show.name}…")
        QApplication.setOverrideCursor(Qt.WaitCursor)

        def done(_eps):
            QApplication.restoreOverrideCursor()
            if self._open_token == show.key:
                self._show_series(show, play_resume)

        def failed(msg):
            QApplication.restoreOverrideCursor()
            self.statusBar().showMessage(f"Impossible de charger les épisodes : {msg}", 8000)

        client = self.client
        run_async(lambda: client.load_episodes(show), done, failed)

    def _show_series(self, show: playlist.Item, play_resume: bool):
        if not show.episodes:
            self.statusBar().showMessage(f"Aucun épisode disponible pour {show.name}", 6000)
            return
        target = self._series_resume_target(show)
        entry = self.library.recent.get(show.key) or {}
        select = target[0].key if target else entry.get("last_ep")
        self._enter_sub_view("episodes", show, show.episodes, select)
        n_seasons = len({e.season for e in show.episodes})
        self.statusBar().showMessage(
            f"{show.name} : {len(show.episodes)} épisodes, {n_seasons} saison(s)", 6000)
        if play_resume and target is not None:
            self.play_item(target[0], resume=True)

    def open_programs(self, channel: playlist.Item):
        cached = channel.extra.get("programs")
        if cached and time.time() - cached[0] < PROGRAMS_TTL:
            self._show_programs(channel, cached[1])
            return
        client = self.client
        if client is None:
            derived = xtream.client_from_stream_url(channel.url)
            if derived is None:
                QMessageBox.information(self, "Replay", "Le replay n'est pas disponible avec cette playlist.")
                return
            client, channel.stream_id = derived
        self._open_token = channel.key
        self.statusBar().showMessage(f"Chargement des replays : {channel.name}…")
        QApplication.setOverrideCursor(Qt.WaitCursor)

        def done(programs):
            QApplication.restoreOverrideCursor()
            channel.extra["programs"] = (time.time(), programs)
            if self._open_token == channel.key:
                self._show_programs(channel, programs)

        def failed(msg):
            QApplication.restoreOverrideCursor()
            self.statusBar().showMessage(f"Impossible de charger les replays : {msg}", 8000)

        run_async(lambda: client.archive_programs(channel), done, failed)

    def _show_programs(self, channel: playlist.Item, programs: list):
        if not programs:
            self.statusBar().showMessage(f"Aucun programme disponible en replay sur {channel.name}", 6000)
            return
        self._enter_sub_view("programs", channel, programs)
        self.statusBar().showMessage(f"{channel.name} : {len(programs)} programmes en replay", 6000)

    # ---- Lecture --------------------------------------------------------- #
    def play_item(self, it: playlist.Item, resume=True):
        self._cancel_auto_next()
        self._save_progress()
        start_ms = self.library.resume_position(it.key) if (resume and it.kind in RESUMABLE) else 0
        self.current = it
        self.track_pref = {}
        self.play_list = list(self.model.items) if it in self.model.items else [it]
        self.want_playing = True
        self.retries = 0
        self.last_pos = start_ms
        self.last_len = self.library.progress.get(it.key, {}).get("len", 0) if start_ms else 0
        self.play_tab = "replay" if it.kind == "program" else self.tab
        remember = it.parent if it.kind in ("episode", "program") and it.parent is not None else it
        self.cfg["last_key"] = remember.key
        self.cfg["last_tab"] = "replay" if it.kind == "program" else self.tab
        self.seek.setValue(0)
        self.time_cur.setText("00:00")
        self.time_total.setText("00:00")
        self._set_player_titles(it)
        self.video.set_idle(False)
        self.seek_row.setVisible(it.kind in SEEKABLE)
        self.seek_buttons.setVisible(it.kind in SEEKABLE)
        self._set_seek_buttons(minutes=it.kind == "program")
        self._update_next_btn()
        self.live_badge.setVisible(it.kind == "live")
        self.audio_btn.setEnabled(True)
        self.sub_btn.setEnabled(True)
        title = it.name if it.parent is None else f"{it.parent.name} - {it.name}"
        self.setWindowTitle(f"{title} - IPTV Player")
        pref = self.track_prefs.get(self._pref_key(it)) if it.kind in RESUMABLE else None
        if pref:
            # Langue / sous-titres mémorisés : on cherche d'abord leurs numéros dans ce fichier
            self._play_token = token = object()
            self.last_play_ts = time.time()  # le contrôle du flux patiente pendant la lecture des pistes
            if self.player is not None:
                self.player.stop()

            def start(found):
                if self._play_token is token and self.current is it:
                    self._play_token = None
                    for kind in ("audio", "spu"):
                        tid = tracklib.match(found, kind, pref.get(kind))
                        if tid is not None:
                            self.track_pref[kind] = tid
                    self._start_stream(start_ms)

            self._probe(it.url, start)
        else:
            self._play_token = None
            self._start_stream(start_ms)
        self._update_live_badge()
        self.statusBar().showMessage(
            f"Connexion : {it.name}…" + (f" (reprise à {fmt_time(start_ms)})" if start_ms else ""))
        self.model.refresh()
        self.right_stack.setCurrentWidget(self.player_panel)

    def _next_episode(self):
        """Suite de la lecture en cours, sinon None : épisode suivant de la série (saison suivante comprise)
        ou programme suivant de la chaîne en replay (un programme déborde souvent sur le créneau d'après)."""
        it = self.current
        if it is None or it.parent is None:
            return None
        if it.kind == "episode" and it.parent.episodes:
            eps = it.parent.episodes
            i = next((k for k, e in enumerate(eps) if e.key == it.key), None)
            return eps[i + 1] if i is not None and i + 1 < len(eps) else None
        if it.kind == "program":
            cached = it.parent.extra.get("programs")
            later = [p for p in (cached[1] if cached else []) if p.start > it.start]
            return min(later, key=lambda p: p.start) if later else None
        return None

    @staticmethod
    def _next_label(nxt: playlist.Item) -> tuple[str, str]:
        """(texte court du bouton, description complète) pour l'épisode / le programme suivant."""
        if nxt.kind == "program":
            title = nxt.extra.get("title") or nxt.name
            return f"Programme suivant · {datetime.fromtimestamp(nxt.start):%H:%M}", title
        label = playlist.episode_label(nxt)
        return f"Épisode suivant · {label.split(' · ')[0]}", label

    def _update_next_btn(self):
        nxt = self._next_episode()
        if nxt is not None:
            short, full = self._next_label(nxt)
            self.next_ep_btn.setText(short)
            self.next_ep_btn.setToolTip(f"{full}  (N)")
            if nxt.kind == "episode" and self.track_prefs.get(self._pref_key(nxt)):
                self._probe(nxt.url, lambda _found: None)  # pistes prêtes : la suite démarre sans attente
        self.next_ep_btn.setVisible(nxt is not None)

    # ---- Langues et sous-titres mémorisés ---------------------------------- #
    @staticmethod
    def _pref_key(it: playlist.Item) -> str:
        """Le choix de langue vaut pour toute la série (épisodes), ou pour le film."""
        return it.parent.key if it.kind == "episode" and it.parent is not None else it.key

    def _probe(self, url: str, callback):
        """Pistes du fichier, lues une fois en arrière-plan ; callback(liste) est appelé dans l'interface."""
        found = self._track_cache.get(url)
        if found:
            callback(found)
            return
        if url in self._probe_waiters:
            self._probe_waiters[url].append(callback)
            return
        if self.instance is None or not url:
            callback([])
            return
        self._probe_waiters[url] = [callback]
        instance = self.instance

        def done(result):
            if result:
                self._track_cache[url] = result
            for cb in self._probe_waiters.pop(url, []):
                cb(result or [])

        run_async(lambda: tracklib.probe(vlc, instance, url, timeout=5.0), done, lambda _msg: done([]))

    def _remember_track(self, kind: str, tid: int):
        """Choix fait pendant la lecture : mémorisé pour le film / la série (épisodes suivants)."""
        it = self.current
        if it is None or it.kind not in RESUMABLE or (kind == "audio" and tid < 0):
            return
        key = self._pref_key(it)

        def save(found):
            if tid < 0:
                value = "off"
            else:
                t = next((t for t in found if t.kind == kind and t.id == tid), None)
                if t is None:
                    return
                value = t.pref()
            self.library.set_pref(key, kind, value)
            self._update_next_btn()

        self._probe(it.url, save)

    def play_next_episode(self):
        nxt = self._auto_next or self._next_episode()
        if nxt is None:
            if self.current is not None and self.current.kind in ("episode", "program"):
                what = "épisode" if self.current.kind == "episode" else "programme en replay"
                self.statusBar().showMessage(f"C'était le dernier {what} disponible.", 5000)
            return
        if self.view in ("episodes", "programs"):
            self._select_key(nxt.key)
        self.play_item(nxt, resume=True)

    def _schedule_next(self, nxt: playlist.Item):
        """Fin d'un épisode / d'un replay : la suite démarre aussitôt."""
        self._auto_next = nxt
        short, full = self._next_label(nxt)
        what = short.split(" · ")[0]
        self.video.set_idle(True, f"{what} : {full}")
        self.statusBar().showMessage(f"{what} : {full}")
        self.next_timer.start()

    def _cancel_auto_next(self):
        self.next_timer.stop()
        self._auto_next = None

    def _play_auto_next(self):
        if self._auto_next is not None:
            self.play_next_episode()

    def _set_player_titles(self, it: playlist.Item):
        if it.kind == "episode" and it.parent is not None:
            title, sub = it.parent.name, playlist.episode_label(it)
        elif it.kind == "program" and it.parent is not None:
            title = it.extra.get("title") or it.name
            sub = f"Replay · {it.parent.name} · {xtream.day_label(it.start)}"
        elif it.kind == "live":
            title, sub = it.name, f"En direct · {it.group_label}"
        else:
            title, sub = it.name, " · ".join(x for x in (it.year, it.genre, it.duration) if x)
        self.player_title.setText(title)
        self.player_sub.setText(sub)

    def _start_stream(self, start_ms: int = 0):
        if self.player is None:
            self._build_vlc()
        self._embed()
        it = self.current
        url, self._offset_ms = it.url, 0
        if it.kind == "program" and start_ms >= 60000:
            # Replay : VLC ne connaît pas sa durée et ignore « start-time » (retour au début). On demande au
            # serveur le replay qui commence à la bonne minute : il ne sait se placer qu'à la minute (voir
            # seek_by), on reprend donc au début de la minute en cours.
            shifted = xtream.shift_timeshift_url(url, start_ms // 60000)
            if shifted:
                url, self._offset_ms = shifted, start_ms // 60000 * 60000
        media = self.instance.media_new(url)
        if start_ms > 0 and it.kind != "program":
            media.add_option(f":start-time={start_ms / 1000:.1f}")
        # Pistes choisies par l'utilisateur (conservées après une reconnexion ou un changement d'écran)
        if self.track_pref.get("audio") is not None:
            media.add_option(f":audio-track-id={self.track_pref['audio']}")
        spu = self.track_pref.get("spu")
        if spu is not None and spu >= 0:
            media.add_option(f":sub-track-id={spu}")
        elif spu is not None:
            # Sous-titres désactivés. « sub-track-id=-1 » ne suffit pas : VLC remet la piste par défaut
            # du fichier (souvent « Forcés »). Ils restent réactivables pendant la lecture.
            media.add_option(":sub-language=none")
        self._pending_seek = None
        if it.kind == "program":
            self.last_pos = self._offset_ms
        else:
            self._pending_seek = start_ms if start_ms > 15000 else None
        self._seek_target, self._seek_hold = None, None
        self.seek_timer.stop()
        self._live_delay, self._paused_at = 0.0, None  # un flux (re)lancé repart du direct
        if self.cast_target is not None:  # la vidéo part vers la télé au lieu de s'afficher ici
            live = self.current.kind in ("live", "program")
            spu = self.track_pref.get("spu")
            burn = spu is not None and spu >= 0
            compat = live and self._cast_key() in self.cast_compat
            # Direct et replays : son converti en AAC (MP2 / E-AC3 illisibles par les Chromecast)
            for opt in cast.media_options(self.cast_target, convert_audio=live, burn_subtitles=burn,
                                          convert_video=compat, live=self.current.kind == "live"):
                media.add_option(opt)
            extra = " · sous-titres incrustés" if burn else (" · mode compatible" if compat else "")
            self.video.set_idle(True, f"Diffusion sur « {self.cast_target.name} »{extra}")
        else:
            self.video.set_idle(False)
        self.player.set_media(media)
        self.player.play()
        self.last_play_ts = time.time()
        # Pour distinguer un échec de diffusion d'une fin de lecture
        self._stream_start_pos = self._offset_ms if it.kind == "program" else start_ms

    def zap(self, delta: int):
        items = self.play_list or self.model.items
        items = [i for i in items if i.kind != "series"]
        if not items:
            return
        pos = next((i for i, c in enumerate(items) if c is self.current), None)
        if pos is None:
            new = 0 if delta > 0 else len(items) - 1
        else:
            new = (pos + delta) % len(items)
        self.play_item(items[new])
        self._select_key(items[new].key)

    def toggle_pause(self):
        if self.current is None:
            return
        state = self.player.get_state()
        if state == vlc.State.Paused:
            self.player.play()
        elif state in (vlc.State.Ended, vlc.State.Stopped, vlc.State.Error):
            self.play_item(self.current)
        else:
            self.player.pause()
            self._save_progress()

    def _update_live_badge(self):
        """Direct : « En direct », ou « Différé : 2 min 05 s » après une pause (sur le PC comme en diffusion)."""
        it = self.current
        if it is None or it.kind != "live" or self.player is None:
            return
        state = self.player.get_state()
        now = time.monotonic()
        if state == vlc.State.Paused:
            if self._paused_at is None:
                self._paused_at = now
        elif state == vlc.State.Playing and self._paused_at is not None:
            self._live_delay += now - self._paused_at
            self._paused_at = None
        delay = self._live_delay + (now - self._paused_at if self._paused_at is not None else 0.0)
        delayed = delay >= 1
        text = f"Différé : {fmt_delay(delay)}" if delayed else "En direct"
        if text == self._live_badge_text:
            return
        self._live_badge_text = text
        b = self.live_badge
        b.setText(text)
        if b.property("delayed") != delayed:
            b.setProperty("delayed", delayed)
            b.setIcon(ui.icon("dot", ui.C["accent_hi"] if delayed else ui.C["live"]))
            b.setToolTip("Revenir au direct" if delayed else "Tu regardes le direct")
            b.setCursor(Qt.PointingHandCursor if delayed else Qt.ArrowCursor)
            b.style().unpolish(b)
            b.style().polish(b)

    def back_to_live(self):
        if self.current is None or self.current.kind != "live" or not self.live_badge.property("delayed"):
            return
        self.retries = 0
        self.want_playing = True
        self._start_stream(0)
        self._update_live_badge()
        self.statusBar().showMessage(f"Retour au direct : {self.current.name}", 4000)

    def _sync_play_icon(self):
        playing = self.player is not None and self.player.get_state() == vlc.State.Playing
        if playing != self._play_icon_playing:
            self._play_icon_playing = playing
            self.play_btn.setIcon(ui.icon("pause" if playing else "play", "white"))

    def stop(self):
        if self._auto_next is not None:  # Stop pendant le décompte : on annule la suite
            self._cancel_auto_next()
            self.video.set_idle(True)
            self.statusBar().showMessage("Lecture automatique de la suite annulée")
            self._update_right()
            return
        self._play_token = None
        self._save_progress()
        self.want_playing = False
        if self.player is not None:
            self.player.stop()
        self.video.set_idle(True)
        self.statusBar().showMessage("Arrêté")
        self._update_right()
        self._update_now_playing()
        self.model.refresh()

    def toggle_mute(self):
        if self.player is not None:
            self.player.audio_toggle_mute()
            muted = not self.player.audio_get_mute()  # l'état change de façon asynchrone
            self.mute_btn.setIcon(ui.icon("mute" if muted else "volume"))

    def _on_volume(self, value: int):
        if self.player is not None:
            self.player.audio_set_volume(value)
        self.cfg["volume"] = value

    def _save_progress(self, finished: bool | None = None):
        """Mémorise la position du film / de l'épisode en cours (et le retire s'il est terminé)."""
        it = self.current
        if it is None or it.kind not in RESUMABLE or self.last_pos <= 0:
            return
        if finished is None:
            finished = library.is_finished(self.last_pos, self.last_len)
        self.library.update(it, self.last_pos, self.last_len, finished)
        self.library.save()
        self.last_progress_save = time.time()

    def _on_finished(self):
        it = self.current
        self.want_playing = False
        self.video.set_idle(True)
        if it.kind in RESUMABLE:
            self.last_pos = max(self.last_pos, self.last_len)
            self._save_progress(finished=True)
        nxt = self._next_episode()
        if nxt is not None:
            self._schedule_next(nxt)  # la vidéo reste affichée (sur le PC comme en diffusion)
        else:
            if not self._fullscreen:
                self._update_right()
            self.statusBar().showMessage(f"Lecture terminée : {it.name}")
        self._update_now_playing()
        if self.view == "list" and self.group_combo.currentData() == RECENT:
            self._apply_filter()
        else:
            self.model.refresh()
        if self.details_item is not None:
            self._show_details(self.details_item)

    def _check_player(self):
        """Appelé toutes les 2 s : met à jour le statut et relance un flux coupé."""
        if not self.want_playing or self.current is None or self.player is None:
            return
        if time.time() - self.last_play_ts < 6:  # laisse le temps au flux de démarrer
            return

        state = self.player.get_state()
        it = self.current
        name = it.name

        # Échec de diffusion : le flux s'arrête peu après le lancement sans avoir vraiment été lu
        # (une fin normale juste après un saut vers la fin de l'épisode n'en est pas une)
        if self.cast_target is not None and state in (vlc.State.Error, vlc.State.Ended) \
                and time.time() - self.last_play_ts < 25 \
                and abs(self.last_pos - self._stream_start_pos) < 5000:
            key = self._cast_key()
            if it.kind in ("live", "program") and key not in self.cast_compat:
                self._set_cast_compat(True)  # nouvel essai, image convertie pour la télé
                self.statusBar().showMessage(
                    f"{name} ne passait pas sur la télé : nouvel essai en mode compatible…", 8000)
                return
            dev = self.cast_target
            self._set_cast(None)  # retour à la lecture sur cet ordinateur
            QMessageBox.warning(
                self, "Diffusion impossible",
                f"Impossible de diffuser sur « {dev.name} ». Vérifie que la télé est allumée et sur le même "
                "réseau que le PC, et que le pare-feu Windows autorise IPTV Player (réseau en profil "
                "« Privé » de préférence). La lecture continue sur cet ordinateur.")
            return

        if state == vlc.State.Playing:
            self.retries = 0
            self.statusBar().showMessage(f"Lecture : {name}")
            return
        if state == vlc.State.Paused:
            self.statusBar().showMessage(f"Pause : {name}")
            return

        if it.kind in SEEKABLE and state in (vlc.State.Ended, vlc.State.Stopped):
            # Fin normale... sauf si on était loin de la fin (coupure réseau) : on reprend où on en était
            cut = self.last_len > 0 and not library.is_finished(self.last_pos, self.last_len)
            if not cut or self.retries >= MAX_RETRIES:
                self._on_finished()
                return

        stuck_opening = state == vlc.State.Opening and time.time() - self.last_play_ts > 20
        if state in (vlc.State.Error, vlc.State.Ended, vlc.State.Stopped) or stuck_opening:
            if self.retries < MAX_RETRIES:
                self.retries += 1
                self.statusBar().showMessage(
                    f"Flux interrompu, reconnexion ({self.retries}/{MAX_RETRIES})… {name}"
                )
                self._start_stream(self.last_pos if it.kind in SEEKABLE else 0)
            else:
                self.want_playing = False
                self.statusBar().showMessage(f"Flux indisponible : {name}. Essayez une autre chaîne.")

    def _update_power(self):
        """Toutes les 0,5 s : pas de veille pendant une lecture (ou une diffusion, même en pause) ;
        au réveil du PC, le flux est relancé là où il en était."""
        now = time.time()
        slept = now - self._last_tick > 20  # les minuteurs sont arrêtés pendant la veille
        self._last_tick = now
        if self.player is None or self.current is None:
            power.keep_awake(False)
            return
        state = self.player.get_state()
        if slept and self.want_playing and state != vlc.State.Paused and now - self.last_play_ts > 5:
            # La connexion au serveur (et à la télé) n'a pas survécu à la veille. On repart de la position
            # d'avant la veille : celle que VLC donne au réveil est souvent fausse (retour au début).
            self.retries = 0
            self._start_stream(self.last_pos if self.current.kind in SEEKABLE else 0)
            self.statusBar().showMessage(f"Reprise après la mise en veille : {self.current.name}", 6000)
        power.keep_awake(self.want_playing and (self.cast_target is not None or state == vlc.State.Playing))

    # ---- Navigation dans les films / épisodes / replays ------------------- #
    def _item_ms(self) -> int:
        """Replay : durée du programme (guide des programmes), que VLC ne connaît pas ; sinon 0."""
        it = self.current
        if it is not None and it.kind == "program" and it.end > it.start:
            return int((it.end - it.start) * 1000)
        return 0

    def _cur_ms(self) -> int:
        """Position dans le film / l'épisode / le programme (ms), -1 si inconnue."""
        t = self.player.get_time() if self.player is not None else -1
        return t + self._offset_ms if t and t > 0 else -1

    def _shown_ms(self):
        """Position demandée, affichée tant que la lecture ne l'a pas rejointe (sinon None)."""
        if self._seek_target is not None:
            return self._seek_target
        if self._seek_hold is not None:
            ms, until = self._seek_hold
            if time.time() < until and abs(self._cur_ms() - ms) > 15000:
                return ms
            self._seek_hold = None
        return None

    def _set_seek_buttons(self, minutes: bool):
        """Boutons de déplacement : ± 10 s / 30 s, ou ± 1 min / 5 min pour un replay (voir seek_by)."""
        if minutes:
            rows = (("back5m", "Reculer de 5 min"), ("back1m", "Reculer de 1 min  (←)"),
                    ("fwd1m", "Avancer de 1 min  (→)"), ("fwd5m", "Avancer de 5 min"))
        else:
            rows = (("back30", "Reculer de 30 s"), ("back10", "Reculer de 10 s  (←)"),
                    ("fwd10", "Avancer de 10 s  (→)"), ("fwd30", "Avancer de 30 s"))
        for b, (name, tip) in zip(self._seek_btns, rows):
            b.setIcon(ui.icon(name))
            b.setToolTip(tip)

    def seek_by(self, delta_ms: int):
        if self.current is None or self.current.kind not in SEEKABLE or self.player is None:
            return
        shown = self._shown_ms()  # clics rapprochés : ils s'ajoutent
        t = shown if shown is not None else self._cur_ms()
        if t < 0:
            return
        if self._item_ms():
            # Replay : le serveur découpe l'enregistrement en blocs d'une minute et renvoie toujours le début
            # d'un bloc, même pour un endroit précis du fichier (vérifié octet par octet). Un saut de 10 s est
            # donc impossible : les boutons et ←/→ avancent d'une minute, les autres de 5 minutes.
            step = 60000 if abs(delta_ms) <= 10000 else 300000
            self._request_seek(t // 60000 * 60000 + (step if delta_ms > 0 else -step))
        else:
            self._request_seek(t + delta_ms)

    def _on_seek(self, fraction: float):
        if self.current is None or self.current.kind not in SEEKABLE or self.player is None:
            return
        fraction = max(0.0, min(1.0, fraction))
        total = self._item_ms() or self.player.get_length()
        if total > 0 and self._item_ms():
            self._request_seek(round(fraction * total / 60000) * 60000)  # replay : minute la plus proche
        elif total > 0:
            self._request_seek(int(fraction * total))
        else:
            self.player.set_position(fraction)

    def _request_seek(self, ms: int):
        prog = self._item_ms()
        total = prog or self.player.get_length()
        end = (total - 60000) // 60000 * 60000 if prog else total - 3000  # replay : dernière minute entière
        ms = max(0, min(ms, end) if total > 0 else ms)
        # Sur le PC, un déplacement dans un film est immédiat. Ailleurs, chaque déplacement relance la
        # lecture (replay : nouveau flux ; télé : rechargement) : les clics rapprochés n'en font qu'un.
        if self.cast_target is None and not prog:
            self._seek_to(ms)
            return
        self._seek_target = ms
        self.seek_timer.setInterval(900 if self.cast_target is not None else 450)
        self.seek_timer.start()  # relancé à chaque clic
        self._show_position(ms, total)
        self.statusBar().showMessage(f"Déplacement à {fmt_time(ms)}…", 4000)

    def _apply_seek(self):
        ms, self._seek_target = self._seek_target, None
        if ms is None or self.current is None or self.player is None:
            return
        self._seek_to(ms)
        self._seek_hold = (ms, time.time() + 30)
        if self.cast_target is not None:
            self.statusBar().showMessage(f"La télé se place à {fmt_time(ms)}…", 8000)

    def _seek_to(self, ms: int):
        """Déplacement immédiat à ms (position dans l'élément en cours)."""
        if self._item_ms():  # replay : flux demandé au serveur à partir de cette minute
            self.retries = 0
            self._start_stream(ms)
        else:
            self.player.set_time(ms)

    def _show_position(self, ms: int, total: int):
        if not self.seek.dragging and total > 0:
            self.seek.setValue(int(min(ms, total) * 1000 / total))
        self.time_cur.setText(fmt_time(ms))

    def _update_seek(self):
        if self.player is None or self.current is None or self.current.kind not in SEEKABLE:
            return
        state = self.player.get_state()
        if state == vlc.State.Ended and self.want_playing:
            self._check_player()  # fin détectée en 0,5 s au lieu de 2 s : la suite démarre plus tôt
            return
        t = self._cur_ms()
        length = self.player.get_length()
        prog = self._item_ms()
        if prog:
            length = prog
            if t < 0:
                t = self._offset_ms  # replay en cours de lancement : il commence là
        if self._pending_seek is not None:
            # Relance (diffusion, changement de langue) : si la lecture a repris trop tôt, on y retourne
            if state == vlc.State.Playing and t > 0:
                if t < self._pending_seek - 15000:
                    self._seek_to(self._pending_seek)
                self._pending_seek = None
            return
        if state in (vlc.State.Playing, vlc.State.Paused) and t and t > 0:
            self.last_pos = t
            if length and length > 0:
                self.last_len = length
            if time.time() - self.last_progress_save > 10:
                self._save_progress(finished=False)
        if self.seek.dragging or not self.seek_row.isVisible():
            return
        self.time_total.setText(fmt_time(length) if length and length > 0 else "--:--")
        shown = self._shown_ms()
        if shown is not None or (length and length > 0):
            self._show_position(shown if shown is not None else max(t, 0), length)
            return
        pos = self.player.get_position()
        if pos is not None and pos >= 0:
            self.seek.setValue(int(pos * 1000))
        self.time_cur.setText(fmt_time(max(t, 0)))

    # ---- Diffusion vers une télé (Google Cast) ------------------------------ #
    def _on_cast_menu(self):
        if not self._cast_scanning and time.time() - self._cast_scan_t > 20:
            self._scan_cast()
        self._fill_cast_menu()

    def _scan_cast(self):
        if self._cast_scanning:
            return
        self._cast_scanning = True

        def done(devices):
            self._cast_scanning = False
            self._cast_scan_t = time.time()
            self.cast_devices = devices
            if self.cast_menu.isVisible():
                self._fill_cast_menu()

        def failed(msg):
            self._cast_scanning = False
            self.statusBar().showMessage(f"Recherche des appareils impossible : {msg}", 6000)

        run_async(lambda: cast.discover(3.0), done, failed)

    def _fill_cast_menu(self):
        m = self.cast_menu
        m.clear()
        head = m.addAction("Diffuser sur…")
        head.setEnabled(False)
        group = QActionGroup(m)
        choices = [(None, "Cet ordinateur")] + [
            (d, d.name + (f"  ·  {d.model}" if d.model else "")) for d in self.cast_devices]
        for dev, label in choices:
            act = m.addAction(ui.icon("cast") if dev else ui.icon("fullscreen"), label)
            act.setCheckable(True)
            act.setChecked(dev == self.cast_target)
            group.addAction(act)
            act.triggered.connect(lambda _=False, d=dev: self._set_cast(d))
        if self._cast_scanning:
            m.addAction("Recherche des appareils…").setEnabled(False)
        elif not self.cast_devices:
            m.addAction("Aucune télé trouvée : elle doit être allumée et sur le même réseau").setEnabled(False)
        if self.cast_target is not None and self.current is not None and self.current.kind in ("live", "program"):
            m.addSeparator()
            compat = m.addAction("Mode compatible pour cette chaîne")
            compat.setCheckable(True)
            compat.setChecked(self._cast_key() in self.cast_compat)
            compat.setToolTip("Convertit l'image pour la télé : à activer si cette chaîne ne s'affiche pas")
            compat.triggered.connect(self._set_cast_compat)
        m.addSeparator()
        m.addAction("Rechercher à nouveau").triggered.connect(self._scan_cast)

    def _cast_key(self) -> str:
        """Clé de la chaîne en cours (un replay utilise celle de sa chaîne)."""
        it = self.current
        if it is None:
            return ""
        return it.parent.key if it.kind == "program" and it.parent is not None else it.key

    def _set_cast_compat(self, enabled: bool):
        key = self._cast_key()
        if not key:
            return
        if enabled:
            self.cast_compat.add(key)
        else:
            self.cast_compat.discard(key)
        self.cfg["cast_compat"] = sorted(self.cast_compat)
        config.save(self.cfg, self.profile_id)
        if self.cast_target is not None and self.current is not None:
            self.retries = 0
            self.want_playing = True
            self._start_stream(self.last_pos if self.current.kind in SEEKABLE else 0)

    def _set_cast(self, dev):
        if dev == self.cast_target:
            return
        self.cast_target = dev
        b = self.cast_btn
        b.setProperty("casting", dev is not None)
        b.style().unpolish(b)
        b.style().polish(b)
        b.setIcon(ui.icon("cast_on", "white") if dev else ui.icon("cast"))
        b.setText(dev.name if dev else "Diffuser")
        self.statusBar().showMessage(f"Diffusion vers « {dev.name} »…" if dev else "Lecture sur cet ordinateur", 6000)
        if self.current is not None and (self.want_playing or self._is_playing()):
            # On relance le flux vers la nouvelle destination, à la même position
            self.want_playing = True
            self.retries = 0
            self._start_stream(self.last_pos if self.current.kind in SEEKABLE else 0)
        else:
            self.video.set_idle(True, f"Prêt à diffuser sur « {dev.name} »" if dev else "")

    # ---- Pistes audio et sous-titres --------------------------------------- #
    def _tracks(self, kind: str):
        """[(id, nom)] des pistes audio ("audio") ou de sous-titres ("spu") du flux en cours."""
        if self.player is None:
            return [], -1
        if kind == "audio":
            raw, cur = self.player.audio_get_track_description(), self.player.audio_get_track()
        else:
            raw, cur = self.player.video_get_spu_description(), self.player.video_get_spu()
        tracks = []
        for tid, name in raw or []:
            if isinstance(name, bytes):
                name = name.decode("utf-8", errors="replace")
            tracks.append((tid, unicodedata.normalize("NFC", name)))
        return tracks, cur

    def _fill_tracks_menu(self, menu: QMenu, kind: str):
        menu.clear()
        tracks, cur = self._tracks(kind)
        if not tracks:
            act = menu.addAction("Aucune piste disponible" if self.current else "Aucune lecture en cours")
            act.setEnabled(False)
            return
        group = QActionGroup(menu)
        for tid, name in tracks:
            act = menu.addAction(name)
            act.setCheckable(True)
            act.setChecked(tid == cur)
            group.addAction(act)
            act.triggered.connect(lambda _=False, t=tid, n=name: self._set_track(kind, t, n))

    def _set_track(self, kind: str, tid: int, name: str):
        if self.player is None:
            return
        self.track_pref[kind] = tid
        self._remember_track(kind, tid)
        label = "Audio" if kind == "audio" else "Sous-titres"
        if self.cast_target is not None and self.current is not None:
            # Pendant une diffusion, la télé reçoit les pistes choisies au démarrage du flux :
            # on relance la diffusion avec la nouvelle piste, à la même position.
            self.retries = 0
            self.want_playing = True
            self._start_stream(self.last_pos if self.current.kind in SEEKABLE else 0)
            self.statusBar().showMessage(f"{label} : {name} (la télé recharge le flux…)", 6000)
            return
        if kind == "audio":
            self.player.audio_set_track(tid)
        else:
            self.player.video_set_spu(tid)
        self.statusBar().showMessage(f"{label} : {name}", 4000)

    def _cycle_track(self, kind: str):
        tracks, cur = self._tracks(kind)
        if len(tracks) < 2:
            self.statusBar().showMessage("Pas d'autre piste " + ("audio" if kind == "audio" else "de sous-titres"), 3000)
            return
        ids = [t for t, _ in tracks]
        i = (ids.index(cur) + 1) % len(ids) if cur in ids else 0
        if kind == "audio" and ids[i] == -1 and len(ids) > 2:  # on ne coupe pas le son en faisant défiler
            i = (i + 1) % len(ids)
        self._set_track(kind, *tracks[i])

    # ---- Affichage ------------------------------------------------------- #
    def toggle_list(self):
        if not self._fullscreen:
            self.left.setVisible(not self.left.isVisible())

    def toggle_fullscreen(self):
        if self._fullscreen:
            self._exit_fullscreen()
            return
        if self.pages.currentWidget() is not self.browse or self.right_stack.currentWidget() is not self.player_panel:
            if not self._is_playing():
                return  # rien à afficher en plein écran
            self.show_player()
        self._fullscreen = True
        self._was_maximized = self.isMaximized()
        self._left_was_visible = self.left.isVisible()
        self.left.hide()
        self.header.hide()
        self.statusBar().hide()
        self.overlay.inner.addWidget(self.controls)  # la barre de contrôle passe sur la vidéo
        self.controls.show()
        self.top_overlay.inner.addWidget(self.player_top)  # titre + bouton Diffuser en haut
        self.player_top.show()
        self.showFullScreen()
        self._last_cursor = None  # affiche la barre quelques secondes à l'entrée
        self.fs_timer.start()

    def _exit_fullscreen(self):
        if not self._fullscreen:
            return
        self._fullscreen = False
        self.fs_timer.stop()
        self.overlay.hide()
        self.top_overlay.hide()
        self.right_layout.insertWidget(0, self.player_top)
        self.right_layout.addWidget(self.controls)  # la barre revient sous la vidéo
        self.controls.show()
        self.statusBar().show()
        self.header.show()
        self.left.setVisible(self._left_was_visible)
        # On revient à l'état d'avant (fenêtre agrandie si elle l'était), pas à la petite taille par défaut
        if self._was_maximized:
            self.showMaximized()
            QTimer.singleShot(80, self._ensure_maximized)
        else:
            self.showNormal()

    def _ensure_maximized(self, retry: bool = True):
        """Sous Windows, après le plein écran, la fenêtre peut se dire « agrandie » tout en étant
        plus petite que l'écran : on vérifie la taille réelle et on refait l'agrandissement."""
        if self._fullscreen:
            return
        screen = self.screen()
        if screen is None:
            return
        area = screen.availableGeometry()
        frame = self.frameGeometry()
        if self.isMaximized() and frame.width() >= area.width() - 16 and frame.height() >= area.height() - 16:
            return
        self.showNormal()
        self.showMaximized()
        if retry:
            QTimer.singleShot(120, lambda: self._ensure_maximized(False))

    def _fs_poll(self):
        """Plein écran : affiche la barre de contrôle quand la souris bouge, la masque après 3 s."""
        pos = QCursor.pos()
        now = time.time()
        overlays = ((self.overlay, "bottom"), (self.top_overlay, "top"))
        if pos != self._last_cursor:
            self._last_cursor = pos
            self._last_move = now
            for ov, _ in overlays:
                if not ov.isVisible():
                    ov.show()
                    ov.raise_()
        for ov, where in overlays:
            if ov.isVisible():
                ov.place_over(self.video, where)  # suit la taille de la vidéo (animation du plein écran)
        hovering = any(ov.isVisible() and ov.geometry().contains(pos) for ov, _ in overlays)
        if (now - self._last_move > 3 and not hovering
                and QApplication.activePopupWidget() is None):  # pas pendant qu'un menu est ouvert
            for ov, _ in overlays:
                ov.hide()

    # ---- Fermeture ------------------------------------------------------- #
    def closeEvent(self, event):
        if not self._switched and self.downloads.active and not confirm(
                self, "Quitter", f"{len(self.downloads.active)} téléchargement(s) en cours ou en attente. Quitter les "
                "arrête ; relancés plus tard (même film / même saison), ils reprendront là où ils en étaient.",
                "Quitter quand même", danger=True):
            event.ignore()
            return
        for timer in (self.ui_timer, self.watchdog, self.fs_timer, self.next_timer, self.tracks_timer,
                      self.sync_timer):
            timer.stop()
        power.keep_awake(False)
        self._exit_fullscreen()
        if not self._switched:
            self.cfg["window_geometry"] = bytes(self.saveGeometry().toHex()).decode()
            self._save_progress()
            self.library.save()
            config.save(self.cfg, self.profile_id)
            self._sync_now()
        else:  # fenêtre de l'ancien profil : on libère le catalogue
            self.by_tab, self.by_key = {k: [] for k, _ in TABS}, {}
            self.model.set_items([])
        player, instance = self.player, self.instance
        self.player = self.instance = None
        self.want_playing = False
        try:
            if player is not None:
                player.stop()
                player.release()
            if instance is not None:
                instance.release()
        except Exception:
            pass
        super().closeEvent(event)


_main_window = None  # fenêtre en cours (remplacée lors d'un changement de profil)


def main() -> int:
    global vlc, VLC_ERROR, _bridge
    app = QApplication(sys.argv)
    if sys.platform == "win32" and not getattr(sys, "frozen", False):
        # Lancé depuis les sources : sans identifiant propre, la barre des tâches afficherait l'icône
        # de Python. Pas pour l'exécutable : Windows l'identifie par son chemin, comme le raccourci
        # épinglé ; un identifiant différent créerait un 2e bouton, séparé de l'épingle.
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("IPTVPlayer.App")
        except Exception:
            pass
    app.setApplicationName("IPTV Player")
    app.setWindowIcon(QIcon(config.asset_path("icon.ico")))
    ui.apply_theme(app)
    _bridge = _Bridge()

    while vlc is None:
        answer = QMessageBox.question(
            None,
            "VLC introuvable",
            "Cette application a besoin de VLC (libVLC) avec la même architecture que "
            "Python / l'exécutable (64 bits en général).\n\n"
            f"Détail : {VLC_ERROR}\n\n"
            "Voulez-vous sélectionner le dossier de VLC (celui qui contient vlc.exe et libvlc.dll) ?",
        )
        if answer != QMessageBox.Yes:
            return 1
        folder = QFileDialog.getExistingDirectory(None, "Dossier de VLC")
        if not folder:
            return 1
        found = vlc_loader.resolve_vlc_dir(folder)
        if found is None:
            QMessageBox.warning(None, "Dossier invalide", "libvlc.dll est introuvable dans ce dossier.")
            continue
        folder = str(found)
        vlc_loader.use_vlc_dir(folder)
        vlc, VLC_ERROR = vlc_loader.try_import_vlc()
        if vlc is not None:
            cfg = config.load()
            cfg["vlc_dir"] = folder
            config.save(cfg)

    global _main_window
    session, notice = cloud.session(), ""
    while True:
        if not session.signed_in and not ask_account(notice=notice):
            return 0
        try:
            sync.startup(session)  # profils du foyer, avant « Qui regarde ? »
            break
        except cloud.AuthError as e:
            session.sign_out()
            notice = f"Reconnexion nécessaire : {e}."
    cfg = config.load()
    if session.vault_key is None and not cfg.get("vault_asked"):
        # PC connecté avant le partage chiffré de l'abonnement : on demande une fois le mot de passe (« Plus tard »
        # possible : ☰ > Compte du foyer > Activer le partage)
        ask_vault()
        cfg = config.load()
        cfg["vault_asked"] = True
        config.save_common(cfg, config.current_profile())
        cfg = config.load()
    if cfg.get("ask_profile", True) and len(cfg["profiles"]) > 1:
        picker = ProfilePicker(cfg["profiles"], config.current_profile())  # « Qui regarde ? »
        picker.exec()
        config.set_profile(picker.chosen)
    _main_window = MainWindow()
    _main_window.showMaximized()
    return app.exec()


def run() -> int:
    try:
        return main()
    except Exception:
        _excepthook(*sys.exc_info())
        return 1


if __name__ == "__main__":
    sys.exit(run())
