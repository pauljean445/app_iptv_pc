"""Cache disque du catalogue Xtream (catalog.bin) pour un démarrage quasi instantané.

Au lancement, l'appli affiche le catalogue en cache (~0,1 s) puis l'actualise en arrière-plan.
Format : marshal + zlib (≈ 1,3 Mo pour 23 000 entrées). Les URL (qui contiennent les identifiants)
ne sont pas stockées : elles sont reconstruites à partir du client Xtream.
"""
import hashlib
import marshal
import sys
import zlib

from .. import config
from .playlist import Item

FILE = "catalog.bin"
VERSION = 1
_KINDS = ("live", "movie", "series")


def source_id(src: dict) -> str:
    raw = "|".join(str(src.get(k, "")) for k in ("type", "server", "username", "format"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def save(src: dict, signature: str, items: list[Item], folder=None) -> None:
    groups: dict[str, int] = {}
    rows = []
    for it in items:
        if it.kind not in _KINDS:
            continue
        g = groups.setdefault(it.group, len(groups))
        rows.append((_KINDS.index(it.kind), it.name, g, it.logo, it.stream_id, it.ext, it.tvg_id,
                     it.archive_days, it.rating, it.year, it.plot, it.genre, it.cast, it.director))
    header = (VERSION, sys.version_info[:2], source_id(src), signature)
    blob = zlib.compress(marshal.dumps((header, list(groups), rows)), 6)
    folder = folder or config.profile_dir()  # dossier du profil (passé par l'appelant : thread)
    path = folder / FILE
    tmp = path.with_suffix(".tmp")
    try:
        folder.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(blob)
        tmp.replace(path)
    except OSError:
        pass


def load(src: dict, client, folder=None) -> tuple[str, list[Item]] | None:
    """Retourne (signature, entrées) si un cache valide existe pour cette source, sinon None."""
    try:
        header, groups, rows = marshal.loads(zlib.decompress(((folder or config.profile_dir()) / FILE).read_bytes()))
    except (OSError, ValueError, EOFError, TypeError, zlib.error):
        return None
    if header[:3] != (VERSION, sys.version_info[:2], source_id(src)):
        return None
    live_url, movie_url = client.live_url, client.movie_url
    items = []
    append = items.append
    for k, name, g, logo, sid, ext, tvg, archive, rating, year, plot, genre, cast, director in rows:
        kind = _KINDS[k]
        if kind == "live":
            url = live_url(sid)
        elif kind == "movie":
            url = movie_url(sid, ext)
        else:
            url = ""
        append(Item(name=name, url=url, group=groups[g], logo=logo, tvg_id=tvg, kind=kind,
                    key=f"x:{kind}:{sid}", stream_id=sid, ext=ext, archive_days=archive,
                    rating=rating, year=year, plot=plot, genre=genre, cast=cast, director=director))
    return header[3], items
