"""Notes IMDb officielles, à jour : fichier public d'IMDb (https://datasets.imdbws.com/title.ratings.tsv.gz,
gratuit pour un usage personnel non commercial, mis à jour chaque jour). OMDb recopie ces notes avec beaucoup de
retard pour les films récents (« N/A », ou une note ancienne).

Le fichier (~9 Mo, 1,7 million de titres) est téléchargé au plus une fois par jour, au moment où une note est
demandée, puis rangé dans imdb_ratings.bin : identifiants triés (entiers) + note × 10 (un octet), soit ~9 Mo en
mémoire, recherche par dichotomie.
"""
import gzip
import io
import struct
import threading
import time
import urllib.request
from array import array
from bisect import bisect_left

from .. import config

URL = "https://datasets.imdbws.com/title.ratings.tsv.gz"
FILE = "imdb_ratings.bin"
MAX_AGE = 86400          # nouveau fichier au plus une fois par jour
RETRY_AFTER = 3600       # téléchargement raté : nouvel essai au bout d'une heure
_MAGIC = b"IMDR1"

_lock = threading.Lock()
_ids: array | None = None
_notes: bytes = b""
_stamp = 0.0             # date du fichier chargé
_last_try = 0.0


def _path():
    return config.config_dir() / FILE


def _load_disk() -> None:
    global _ids, _notes, _stamp
    try:
        raw = _path().read_bytes()
    except OSError:
        return
    if not raw.startswith(_MAGIC):
        return
    stamp, n = struct.unpack_from("<dI", raw, len(_MAGIC))
    off = len(_MAGIC) + struct.calcsize("<dI")
    ids = array("I")
    ids.frombytes(raw[off:off + 4 * n])
    _ids, _notes, _stamp = ids, raw[off + 4 * n:off + 5 * n], stamp


def _download() -> None:
    """Télécharge et range le fichier d'IMDb (thread de l'appelant, quelques secondes)."""
    global _ids, _notes, _stamp
    req = urllib.request.Request(URL, headers={"User-Agent": "IPTVPlayer (lecteur IPTV de bureau)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        blob = r.read()
    rows = []
    with gzip.open(io.BytesIO(blob), "rt", encoding="utf-8") as f:
        next(f, None)  # en-tête : tconst, averageRating, numVotes
        for line in f:
            tconst, rating, _votes = line.split("\t", 2)
            try:
                rows.append((int(tconst[2:]), min(100, round(float(rating) * 10))))
            except ValueError:
                continue
    rows.sort()
    ids = array("I", (r[0] for r in rows))
    notes = bytes(r[1] for r in rows)
    stamp = time.time()
    data = _MAGIC + struct.pack("<dI", stamp, len(ids)) + ids.tobytes() + notes
    path = _path()
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_bytes(data)
        tmp.replace(path)
    except OSError:
        pass  # gardé en mémoire seulement
    _ids, _notes, _stamp = ids, notes, stamp


def _ensure_fresh() -> None:
    global _last_try
    if _ids is None:
        _load_disk()
    now = time.time()
    if (_ids is None or now - _stamp > MAX_AGE) and now - _last_try > RETRY_AFTER:
        _last_try = now
        try:
            _download()
        except Exception:
            pass  # IMDb injoignable : ancien fichier (s'il existe), nouvel essai dans une heure


def rating10(imdb_id: str) -> int:
    """Note IMDb × 10 (47 pour 4.7), -1 si inconnue."""
    text = rating(imdb_id)
    return round(float(text) * 10) if text else -1


def rating(imdb_id: str) -> str:
    """Note IMDb actuelle (« 4.7 ») d'un identifiant « tt… », ou "" si inconnue."""
    if not imdb_id or not imdb_id.startswith("tt") or not imdb_id[2:].isdigit():
        return ""
    with _lock:
        _ensure_fresh()
        if _ids is None:
            return ""
        n = int(imdb_id[2:])
        i = bisect_left(_ids, n)
        if i < len(_ids) and _ids[i] == n:
            return f"{_notes[i] / 10:.1f}"
    return ""
