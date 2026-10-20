"""Modèle commun des entrées (chaînes, films, séries, épisodes, programmes de replay)
et parsing des playlists M3U/M3U8 (URL ou fichier local)."""
import re
from dataclasses import dataclass, field
from urllib.parse import parse_qs, quote, urlsplit

# Certains fournisseurs bloquent le User-Agent par défaut de Python.
USER_AGENT = "VLC/3.0.20 LibVLC/3.0.20"

_ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')
# URL de flux Xtream : http://hôte/[live|movie|series/]user/mdp/123.ext
_XT_URL_RE = re.compile(r"^https?://[^/]+/(?:(live|movie|series)/)?[^/]+/[^/]+/(\d+)(?:\.(\w+))?$", re.IGNORECASE)
_XT_KINDS = {"": "live", "live": "live", "movie": "movie", "series": "ep"}


def stable_key(url: str) -> tuple[str, str, str]:
    """(clé, stream_id, extension). Pour une URL Xtream, même clé que l'API (x:movie:123…) :
    favoris et reprises restent valables que le catalogue vienne de l'API ou de la playlist M3U."""
    m = _XT_URL_RE.match(url.strip())
    if not m:
        return "m3u:" + url, "", ""
    kind = _XT_KINDS[(m.group(1) or "").lower()]
    return f"x:{kind}:{m.group(2)}", m.group(2), m.group(3) or ""
# "Ma série S01E02", "Ma série S1 E2", "Ma série - S01.E02"
_EPISODE_RE = re.compile(r"\bS(\d{1,2})\s*[ ._-]?\s*E(\d{1,4})\b", re.IGNORECASE)
_VOD_EXT = (".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v", ".mpg", ".mpeg", ".divx")


@dataclass(eq=False, slots=True)
class Item:
    """Une entrée affichable : chaîne en direct, film, série, épisode ou programme de replay."""

    name: str
    url: str = ""
    group: str = ""
    logo: str = ""
    tvg_id: str = ""
    kind: str = "live"          # "live" | "movie" | "series" | "episode" | "program"
    key: str = ""               # identifiant stable (favoris, reprise de lecture)
    stream_id: str = ""         # identifiant Xtream (stream_id, series_id ou id d'épisode)
    ext: str = ""               # extension du fichier (films Xtream : mkv, mp4…)
    plot: str = ""
    rating: str = ""            # note du fournisseur (sur 10)
    year: str = ""
    genre: str = ""
    duration: str = ""
    cast: str = ""
    director: str = ""
    archive_days: int = 0       # direct : profondeur du replay en jours (0 = pas de replay)
    season: int = 0
    episode: int = 0
    start: float = 0.0          # programme : début / fin (timestamp)
    end: float = 0.0
    parent: "Item | None" = None   # épisode -> série ; programme -> chaîne
    episodes: list | None = None   # série : épisodes (None = pas encore chargés)
    info_loaded: bool = False      # descriptif détaillé déjà récupéré
    imdb_rating: str = ""
    imdb_id: str = ""
    norm: str = ""              # nom en minuscules sans accents (recherche), calculé à la demande
    extra: dict = field(default_factory=dict)

    @property
    def group_label(self) -> str:
        return self.group or "Sans groupe"


Channel = Item  # compatibilité


def episode_info(name: str):
    """Retourne (nom de la série, saison, épisode) si le nom contient SxxEyy, sinon None."""
    m = _EPISODE_RE.search(name)
    if not m:
        return None
    show = name[: m.start()].strip(" -_.|:")
    return (show or name.strip(), int(m.group(1)), int(m.group(2)))


def episode_label(it: "Item") -> str:
    """'Série (MULTI) FHD - S01E02 - Le titre' -> 'S01E02 · Le titre'."""
    m = _EPISODE_RE.search(it.name)
    if m:
        rest = it.name[m.end():].strip(" -_.|:")
        code = f"S{int(m.group(1)):02d}E{int(m.group(2)):02d}"
    elif it.season or it.episode:
        rest = it.name.strip()
        code = f"S{it.season:02d}E{it.episode:02d}"
    else:
        return it.name
    return f"{code} · {rest}" if rest else code


_TAG_RE = re.compile(
    r"^\s*(\|[^|]*\||\[[^\]]*\]|[A-Z]{2,3}\s*[-:|]\s+)|"   # |FR|  [FR]  FR -  en tête
    r"\((?:MULTI|VF|VOSTFR|VO|VFF|VFQ|FR|EN|FRENCH|TRUEFRENCH)\)|"
    r"\b(?:4K|UHD|FHD|HD|SD|HEVC|H265|x265|1080p|720p|2160p|MULTI|VOSTFR|VFF|VFQ)\b",
    re.IGNORECASE,
)
_YEAR_RE = re.compile(r"[\(\[\s-]*((?:19|20)\d{2})[\)\]]?\s*$")


def clean_title(name: str) -> tuple[str, str]:
    """Nettoie un nom de fournisseur ('|FR| Titre (MULTI) FHD 2026') -> ('Titre', '2026')."""
    title = name
    for _ in range(3):
        title = _TAG_RE.sub(" ", title)
    title = re.sub(r"\s{2,}", " ", title).strip(" -_.|:")
    year = ""
    m = _YEAR_RE.search(title)
    if m and m.start() > 0:
        year = m.group(1)
        title = title[: m.start()].strip(" -_.|:(")
    return title, year


def parse_m3u(text: str) -> list[Item]:
    """Transforme le contenu texte d'un fichier M3U en liste d'entrées."""
    items: list[Item] = []
    pending: dict | None = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue

        if line.startswith("#EXTINF"):
            attrs = {k.lower(): v for k, v in _ATTR_RE.findall(line)}
            # Le nom est après la première virgule qui suit le dernier attribut entre guillemets.
            start = line.rfind('"')
            comma = line.find(",", start if start != -1 else 0)
            name = line[comma + 1:].strip() if comma != -1 else ""
            days = attrs.get("catchup-days") or attrs.get("tvg-rec") or attrs.get("timeshift") or "0"
            pending = {
                "name": name or attrs.get("tvg-name", ""),
                "group": attrs.get("group-title", ""),
                "logo": attrs.get("tvg-logo", ""),
                "tvg_id": attrs.get("tvg-id", ""),
                "archive_days": int(days) if days.isdigit() else 0,
            }
        elif line.startswith("#EXTGRP:"):
            if pending is not None and not pending["group"]:
                pending["group"] = line[len("#EXTGRP:"):].strip()
        elif line.startswith("#"):
            continue  # #EXTM3U, #EXTVLCOPT, commentaires...
        else:
            info = pending or {}
            key, sid, ext = stable_key(line)
            items.append(
                Item(
                    name=info.get("name") or line,
                    url=line,
                    group=info.get("group", ""),
                    logo=info.get("logo", ""),
                    tvg_id=info.get("tvg_id", ""),
                    archive_days=info.get("archive_days", 0),
                    key=key, stream_id=sid, ext=ext,
                )
            )
            pending = None

    return items


def _classify(it: Item, series_kw: tuple, xtream_style: bool) -> str:
    path = urlsplit(it.url).path.lower()
    # 1) Les URL Xtream Codes distinguent déjà films et séries
    if "/movie/" in path:
        return "movie"
    if "/series/" in path:
        return "episode"
    # Playlist Xtream : tout le reste est du direct, même si le groupe s'appelle « Cinéma »
    if xtream_style:
        return "live"
    # 2) Un flux sans extension vidéo (.ts, .m3u8, rien) est une chaîne en direct
    if not path.endswith(_VOD_EXT):
        return "live"
    # 3) Fichier vidéo : épisode si le nom contient SxxEyy ou si le groupe parle de séries
    if episode_info(it.name) or any(k in it.group.lower() for k in series_kw):
        return "episode"
    return "movie"


def classify_all(items: list[Item], rules: dict) -> list[Item]:
    """Classe les entrées et regroupe les épisodes en séries.

    Retourne la liste finale : chaînes (live), films (movie) et séries (series, avec `episodes`).
    """
    series_kw = tuple(str(x).lower() for x in rules.get("series", ()) if x)
    xtream_style = any(s in it.url.lower() for it in items for s in ("/movie/", "/series/", "/live/"))
    out: list[Item] = []
    shows: dict[str, Item] = {}
    for it in items:
        kind = _classify(it, series_kw, xtream_style)
        if kind != "episode":
            it.kind = kind
            out.append(it)
            continue
        info = episode_info(it.name)
        show_name, season, ep = info if info else (it.group_label, 0, 0)
        skey = "m3u-series:" + show_name.lower()
        show = shows.get(skey)
        if show is None:
            show = Item(name=show_name, group=it.group, logo=it.logo, kind="series", key=skey,
                        episodes=[], info_loaded=True)
            shows[skey] = show
            out.append(show)
        it.kind = "episode"
        it.parent = show
        it.season, it.episode = season, ep
        show.episodes.append(it)
    for show in shows.values():
        show.episodes.sort(key=lambda e: (e.season, e.episode))
    return out


def _decode(data: bytes) -> str:
    return data.decode("utf-8-sig", errors="replace")


def _check(items: list[Item]) -> list[Item]:
    if not items:
        raise ValueError(
            "Aucune chaîne trouvée : la réponse n'est pas une playlist M3U valide "
            "(identifiants incorrects, abonnement expiré ou mauvaise URL ?)."
        )
    return items


def http_get(url: str, timeout: int = 60, retries: int = 0) -> bytes:
    """Télécharge une URL. retries : nouvelles tentatives en cas d'erreur passagère (5xx, coupure, délai)."""
    import time

    for attempt in range(retries + 1):
        try:
            return _http_get_once(url, timeout)
        except _Transient as e:
            if attempt == retries:
                raise RuntimeError(str(e)) from e.__cause__
            time.sleep(1.0 + attempt)  # 1 s, puis 2 s


class _Transient(RuntimeError):
    """Erreur réseau qui peut disparaître en réessayant (serveur surchargé, coupure…)."""


def _http_get_once(url: str, timeout: int) -> bytes:
    # Import différé : urllib/ssl coûtent ~80 ms au démarrage et ne servent qu'au réseau.
    import socket
    import urllib.error
    import urllib.request

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        if e.code >= 500:
            raise _Transient(f"Le serveur du fournisseur est indisponible (« {e.code} {e.reason} »).") from e
        raise RuntimeError(
            f"Le serveur a répondu « {e.code} {e.reason} ». Vérifiez l'URL et vos identifiants."
        ) from e
    except urllib.error.URLError as e:
        raise _Transient(f"Impossible de joindre le serveur : {e.reason}") from e
    except (socket.timeout, TimeoutError) as e:
        raise _Transient("Délai dépassé : le serveur ne répond pas.") from e
    except ConnectionError as e:
        raise _Transient(f"Connexion interrompue par le serveur : {e}") from e


def load_from_url(url: str, timeout: int = 120) -> list[Item]:
    return _check(parse_m3u(_decode(http_get(url, timeout, retries=1))))


def load_from_file(path: str) -> list[Item]:
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        raise RuntimeError(f"Impossible de lire le fichier : {e}") from e
    return _check(parse_m3u(_decode(data)))


def normalize_server(server: str) -> str:
    server = server.strip().rstrip("/")
    if not server.lower().startswith(("http://", "https://")):
        server = "http://" + server
    return server


def build_xtream_url(server: str, username: str, password: str, output: str = "ts") -> str:
    """Construit l'URL de playlist M3U d'un fournisseur Xtream Codes."""
    return (
        f"{normalize_server(server)}/get.php?username={quote(username)}&password={quote(password)}"
        f"&type=m3u_plus&output={output}"
    )


def xtream_from_m3u_url(url: str):
    """Si l'URL est une playlist Xtream (get.php?username=…&password=…), retourne (serveur, user, mdp)."""
    parts = urlsplit(url.strip())
    if not parts.path.lower().endswith("get.php"):
        return None
    q = parse_qs(parts.query)
    user, pwd = q.get("username", [""])[0], q.get("password", [""])[0]
    if not (user and pwd and parts.netloc):
        return None
    return (f"{parts.scheme or 'http'}://{parts.netloc}", user, pwd)


def source_from_config(cfg: dict) -> dict | None:
    """Décrit la source à charger d'après la config, ou None si incomplète.

    {"type": "xtream", "server", "username", "password", "format"} ou {"type": "url"|"file", "value"}.
    """
    mode = cfg.get("mode")
    fmt = cfg.get("stream_format", "ts")
    if mode == "xtream":
        if cfg.get("server") and cfg.get("username") and cfg.get("password"):
            return {"type": "xtream", "server": normalize_server(cfg["server"]),
                    "username": cfg["username"], "password": cfg["password"], "format": fmt}
    elif mode == "url":
        if cfg.get("url"):
            xt = xtream_from_m3u_url(cfg["url"])
            if xt:
                return {"type": "xtream", "server": xt[0], "username": xt[1], "password": xt[2],
                        "format": fmt, "m3u_url": cfg["url"]}
            return {"type": "url", "value": cfg["url"]}
    elif mode == "file":
        if cfg.get("file"):
            return {"type": "file", "value": cfg["file"]}
    return None
