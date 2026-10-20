"""Téléchargement asynchrone des affiches / logos, avec cache disque et mémoire.

Optimisations :
- les affiches TMDB sont demandées en petite taille (w185 au lieu de 600x900 : ~10x plus léger) ;
- les fichiers sont écrits tels quels (pas de décodage / réencodage dans le thread de l'interface) ;
- le décodage se fait directement à la taille d'affichage (QImageReader.setScaledSize) ;
- le cache disque est plafonné (les fichiers les plus anciens sont supprimés au démarrage).
"""
import hashlib
import os
import re
import threading
from collections import OrderedDict, deque

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QSize, QUrl, Qt, Signal
from PySide6.QtGui import QGuiApplication, QImageReader, QPixmap
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from . import config
from .sources.playlist import USER_AGENT

MAX_PARALLEL = 6
MAX_QUEUE = 300
MAX_MEMORY = 2000
MAX_FILE = 400_000            # au-delà, on ne garde pas l'image (fichier anormalement lourd)
CACHE_LIMIT = 150 * 1024**2   # taille max du cache disque…
CACHE_TARGET = 100 * 1024**2  # … ramenée à cette taille lors du nettoyage

_TMDB_RE = re.compile(r"(image\.tmdb\.org/t/p/)(?:w\d+(?:_and_h\d+_\w+)?|original)/", re.IGNORECASE)


def _format(data: bytes) -> bytes | None:
    """Format d'après les premiers octets : évite à Qt de tester chaque décodeur (2x plus rapide)."""
    if data[:2] == b"\xff\xd8":
        return b"jpeg"
    if data[:4] == b"\x89PNG":
        return b"png"
    if data[:4] == b"GIF8":
        return b"gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return b"webp"
    if data[:2] == b"BM":
        return b"bmp"
    return None


def small_url(url: str, large: bool = False) -> str:
    """Les images TMDB existent en plusieurs tailles : petite (listes, vignettes) ou moyenne (fiche)."""
    return _TMDB_RE.sub(r"\1w342/" if large else r"\1w185/", url, count=1)


def prune_cache(folder) -> None:
    """Supprime les images les plus anciennes si le cache dépasse CACHE_LIMIT."""
    files = []
    try:
        for e in os.scandir(folder):
            if not e.is_file():
                continue
            if e.name.endswith(".jpg"):  # ancien format de cache (images en grand) : on libère la place
                _remove(e.path)
                continue
            st = e.stat()
            files.append((st.st_mtime, st.st_size, e.path))
    except OSError:
        return
    total = sum(f[1] for f in files)
    if total <= CACHE_LIMIT:
        return
    for _, size, path in sorted(files):
        if _remove(path):
            total -= size
            if total <= CACHE_TARGET:
                break


def _remove(path) -> bool:
    try:
        os.remove(path)
        return True
    except OSError:
        return False


class ImageLoader(QObject):
    loaded = Signal(str)  # url

    def __init__(self, parent=None):
        super().__init__(parent)
        self.nam = QNetworkAccessManager(self)
        self.nam.setTransferTimeout(15000)
        self.dir = config.config_dir() / "images"
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        threading.Thread(target=prune_cache, args=(self.dir,), daemon=True).start()
        self.dpr = QGuiApplication.primaryScreen().devicePixelRatio() if QGuiApplication.primaryScreen() else 1.0
        self.mem: OrderedDict = OrderedDict()
        self.queue: deque = deque()
        self.queued: set[str] = set()
        self.failed: set[str] = set()
        self.inflight = 0

    def _path(self, url: str):
        return self.dir / hashlib.sha1(url.encode("utf-8", "replace")).hexdigest()

    def has_failed(self, url: str, large: bool = False) -> bool:
        return small_url(url, large) in self.failed

    def pixmap(self, url: str, w: int, h: int, large: bool = False) -> QPixmap | None:
        """Retourne l'image redimensionnée si elle est disponible, sinon lance son téléchargement.
        large=True : version plus détaillée (fiche en grand)."""
        if not url:
            return None
        url = small_url(url, large)  # adresse réellement téléchargée (et clé du cache)
        k = (url, w, h)
        pm = self.mem.get(k)
        if pm is not None:
            self.mem.move_to_end(k)
            return pm
        if url in self.queued or url in self.failed:
            return None  # déjà en cours : pas d'accès disque à chaque rafraîchissement
        if not url.startswith(("http://", "https://")):
            self.failed.add(url)
            return None
        try:
            with open(self._path(url), "rb") as f:
                data = f.read()
        except OSError:  # pas encore en cache
            self._request(url)
            return None
        fmt = _format(data)
        if fmt is None:
            self.failed.add(url)
            return None
        buf = QBuffer()
        buf.setData(QByteArray(data))
        buf.open(QIODevice.ReadOnly)
        reader = QImageReader(buf, fmt)
        size = reader.size()
        if size.isValid() and size.width() > 0:
            target = size.scaled(QSize(int(w * self.dpr), int(h * self.dpr)), Qt.KeepAspectRatio)
            reader.setScaledSize(target)
        img = reader.read()
        if img.isNull():
            self.failed.add(url)
            return None
        pm = QPixmap.fromImage(img)
        pm.setDevicePixelRatio(self.dpr)
        self.mem[k] = pm
        if len(self.mem) > MAX_MEMORY:
            self.mem.popitem(last=False)
        return pm

    def _request(self, url: str):
        self.queued.add(url)
        self.queue.append(url)
        while len(self.queue) > MAX_QUEUE:  # les plus anciennes ne sont plus à l'écran
            self.queued.discard(self.queue.popleft())
        self._pump()

    def _pump(self):
        while self.inflight < MAX_PARALLEL and self.queue:
            url = self.queue.pop()  # la plus récente d'abord (celle qui est visible)
            req = QNetworkRequest(QUrl(url))
            req.setRawHeader(b"User-Agent", USER_AGENT.encode())
            reply = self.nam.get(req)
            self.inflight += 1
            reply.finished.connect(lambda r=reply, u=url: self._done(r, u))

    def _done(self, reply: QNetworkReply, url: str):
        self.inflight -= 1
        self.queued.discard(url)
        ok = False
        if reply.error() == QNetworkReply.NoError:
            data = bytes(reply.readAll())
            if 0 < len(data) <= MAX_FILE and _format(data):
                try:
                    self._path(url).write_bytes(data)
                    ok = True
                except OSError:
                    pass
        reply.deleteLater()
        if ok:
            self.loaded.emit(url)
        else:
            self.failed.add(url)
        self._pump()
