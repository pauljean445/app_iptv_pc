"""Client de l'API Xtream Codes (player_api.php).

Bien plus riche que la playlist M3U : catégories séparées pour le direct, les films et les séries,
descriptifs / notes / affiches, saisons et épisodes, et programmes disponibles en replay.
"""
import base64
import hashlib
import json
import math
import re
import time
from datetime import datetime
from urllib.parse import quote, unquote

from .playlist import Item, http_get, normalize_server

CATALOG_ACTIONS = ("get_live_categories", "get_live_streams", "get_vod_categories",
                   "get_vod_streams", "get_series_categories", "get_series")
_DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def _rating(value) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return ""
    return f"{v:.1f}" if v > 0 else ""


def _b64(text) -> str:
    if not text:
        return ""
    try:
        return base64.b64decode(text).decode("utf-8", errors="replace").strip()
    except (ValueError, TypeError):
        return str(text)


def _year(value) -> str:
    value = str(value or "")
    return value[:4] if value[:4].isdigit() else ""


def _int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def day_label(ts: float) -> str:
    d = datetime.fromtimestamp(ts).date()
    delta = (datetime.now().date() - d).days
    if delta == 0:
        return "Aujourd'hui"
    if delta == 1:
        return "Hier"
    return f"{_DAYS[d.weekday()].capitalize()} {d:%d/%m}"


class XtreamClient:
    def __init__(self, server: str, username: str, password: str, fmt: str = "ts"):
        self.server = normalize_server(server)
        self.username = username
        self.password = password
        self.fmt = fmt if fmt in ("ts", "m3u8") else "ts"
        self._u = quote(username, safe="")
        self._p = quote(password, safe="")

    # ---- Requêtes --------------------------------------------------------- #
    def raw(self, action: str = "", timeout: int = 120, **params) -> bytes:
        url = f"{self.server}/player_api.php?username={self._u}&password={self._p}"
        if action:
            url += f"&action={action}"
        for k, v in params.items():
            url += f"&{k}={quote(str(v), safe='')}"
        return http_get(url, timeout, retries=2)

    @staticmethod
    def _json(data: bytes):
        try:
            return json.loads(data.decode("utf-8", errors="replace"))
        except ValueError as e:
            raise RuntimeError("Réponse inattendue du serveur (API Xtream indisponible ?).") from e

    def api(self, action: str = "", timeout: int = 120, **params):
        return self._json(self.raw(action, timeout, **params))

    @staticmethod
    def _check_auth(info) -> None:
        user = info.get("user_info") if isinstance(info, dict) else None
        if not user or str(user.get("auth")) != "1":
            raise RuntimeError("Identifiants refusés par le serveur.")
        if user.get("status") not in (None, "", "Active"):
            raise RuntimeError(f"Abonnement « {user.get('status')} ».")

    # ---- URL des flux ----------------------------------------------------- #
    def live_url(self, stream_id) -> str:
        return f"{self.server}/live/{self._u}/{self._p}/{stream_id}.{self.fmt}"

    def movie_url(self, stream_id, ext) -> str:
        return f"{self.server}/movie/{self._u}/{self._p}/{stream_id}.{ext or 'mp4'}"

    def episode_url(self, episode_id, ext) -> str:
        return f"{self.server}/series/{self._u}/{self._p}/{episode_id}.{ext or 'mp4'}"

    def timeshift_url(self, stream_id, start_local: str, minutes: int) -> str:
        """start_local : heure du serveur 'AAAA-MM-JJ HH:MM:SS' (champ « start » de l'EPG)."""
        s = start_local
        stamp = f"{s[:10]}:{s[11:13]}-{s[14:16]}"  # AAAA-MM-JJ:HH-MM
        return f"{self.server}/timeshift/{self._u}/{self._p}/{minutes}/{stamp}/{stream_id}.ts"

    # ---- Catalogue -------------------------------------------------------- #
    def fetch_catalog(self) -> dict[str, bytes]:
        """Télécharge (en parallèle) les réponses brutes de l'API nécessaires au catalogue."""
        from concurrent.futures import ThreadPoolExecutor

        actions = ("",) + CATALOG_ACTIONS  # "" = authentification
        with ThreadPoolExecutor(max_workers=len(actions)) as pool:
            raw = dict(zip(actions, pool.map(self.raw, actions)))
        self._check_auth(self._json(raw.pop("")))
        return raw

    @staticmethod
    def signature(raw: dict[str, bytes]) -> str:
        """Empreinte des réponses brutes : identique = catalogue inchangé, inutile de le reconstruire."""
        h = hashlib.sha1()
        for action in CATALOG_ACTIONS:
            h.update(raw.get(action, b""))
        return h.hexdigest()

    def load_catalog(self) -> list[Item]:
        return self.build_catalog(self.fetch_catalog())

    def build_catalog(self, raw: dict[str, bytes]) -> list[Item]:
        def rows(action):
            data = self._json(raw.get(action, b"[]"))
            return data if isinstance(data, list) else []

        live_c, live, vod_c, vod, ser_c, series = (rows(a) for a in CATALOG_ACTIONS)

        def cats(rows):
            return {str(c.get("category_id")): c.get("category_name") or "" for c in rows}

        live_c, vod_c, ser_c = cats(live_c), cats(vod_c), cats(ser_c)
        # Ordre des groupes = ordre des catégories du fournisseur
        order = {}
        for i, cid in enumerate(list(live_c) + list(vod_c) + list(ser_c)):
            order.setdefault(cid, i)

        items: list[Item] = []
        for s in sorted(live, key=lambda s: order.get(str(s.get("category_id")), 1 << 30)):
            sid = s.get("stream_id")
            if sid is None:
                continue
            archive = _int(s.get("tv_archive_duration")) if str(s.get("tv_archive")) == "1" else 0
            items.append(Item(
                name=str(s.get("name") or "").strip(), url=self.live_url(sid),
                group=live_c.get(str(s.get("category_id")), ""), logo=s.get("stream_icon") or "",
                tvg_id=s.get("epg_channel_id") or "", kind="live", key=f"x:live:{sid}",
                stream_id=str(sid), archive_days=archive,
            ))
        for s in sorted(vod, key=lambda s: order.get(str(s.get("category_id")), 1 << 30)):
            sid = s.get("stream_id")
            if sid is None:
                continue
            ext = s.get("container_extension") or ""
            items.append(Item(
                name=str(s.get("name") or "").strip(), url=self.movie_url(sid, ext), ext=ext,
                group=vod_c.get(str(s.get("category_id")), ""), logo=s.get("stream_icon") or "",
                kind="movie", key=f"x:movie:{sid}", stream_id=str(sid), rating=_rating(s.get("rating")),
                year=_year(s.get("year") or s.get("releasedate")),
            ))
        for s in sorted(series, key=lambda s: order.get(str(s.get("category_id")), 1 << 30)):
            sid = s.get("series_id")
            if sid is None:
                continue
            items.append(Item(
                name=str(s.get("name") or "").strip(), group=ser_c.get(str(s.get("category_id")), ""),
                logo=s.get("cover") or "", kind="series", key=f"x:series:{sid}", stream_id=str(sid),
                plot=s.get("plot") or "", rating=_rating(s.get("rating")), genre=s.get("genre") or "",
                year=_year(s.get("releaseDate") or s.get("release_date")),
                cast=s.get("cast") or "", director=s.get("director") or "",
            ))
        if not items:
            raise RuntimeError("Le serveur n'a renvoyé aucune chaîne.")
        return items

    # ---- Détails (à la demande) ------------------------------------------ #
    def fill_movie_info(self, it: Item) -> None:
        data = self.api("get_vod_info", timeout=30, vod_id=it.stream_id)
        info = data.get("info") if isinstance(data, dict) else None
        if isinstance(info, dict):
            it.plot = info.get("plot") or info.get("description") or it.plot
            it.genre = info.get("genre") or it.genre
            it.duration = info.get("duration") or it.duration
            it.cast = info.get("cast") or info.get("actors") or it.cast
            it.director = info.get("director") or it.director
            it.year = _year(info.get("releasedate")) or it.year
            it.rating = _rating(info.get("rating")) or it.rating
            it.logo = it.logo or info.get("cover_big") or info.get("movie_image") or ""
            it.extra["tmdb_id"] = info.get("tmdb_id") or ""
            it.extra["o_name"] = info.get("o_name") or ""
        it.info_loaded = True

    def load_episodes(self, show: Item) -> list[Item]:
        data = self.api("get_series_info", timeout=60, series_id=show.stream_id)
        if not isinstance(data, dict):
            data = {}
        info = data.get("info") if isinstance(data.get("info"), dict) else {}
        if info:
            show.plot = show.plot or info.get("plot") or ""
            show.genre = show.genre or info.get("genre") or ""
            show.rating = show.rating or _rating(info.get("rating"))
            show.logo = show.logo or info.get("cover") or ""
        raw = data.get("episodes") or {}
        groups = raw.values() if isinstance(raw, dict) else raw
        episodes: list[Item] = []
        for group in groups:
            for e in group if isinstance(group, list) else []:
                eid = e.get("id")
                if eid is None:
                    continue
                ei = e.get("info") if isinstance(e.get("info"), dict) else {}
                season = _int(e.get("season"))
                num = _int(e.get("episode_num"))
                title = str(e.get("title") or "").strip()
                episodes.append(Item(
                    name=title or f"Épisode {num}",
                    url=self.episode_url(eid, e.get("container_extension")),
                    group=f"Saison {season}", logo=ei.get("movie_image") or show.logo,
                    kind="episode", key=f"x:ep:{eid}", stream_id=str(eid),
                    plot=ei.get("plot") or ei.get("overview") or "", rating=_rating(ei.get("rating")),
                    duration=ei.get("duration") or "", year=_year(ei.get("air_date") or ei.get("releasedate")),
                    season=season, episode=num, parent=show, info_loaded=True,
                ))
        episodes.sort(key=lambda e: (e.season, e.episode))
        show.episodes = episodes
        show.info_loaded = True
        return episodes

    def archive_programs(self, channel: Item) -> list[Item]:
        """Programmes passés de la chaîne disponibles en replay (du plus récent au plus ancien)."""
        data = self.api("get_simple_data_table", timeout=60, stream_id=channel.stream_id)
        rows = data.get("epg_listings") if isinstance(data, dict) else None
        rows = rows if isinstance(rows, list) else []
        now = time.time()
        oldest = now - max(1, channel.archive_days) * 86400
        flagged = [r for r in rows if str(r.get("has_archive")) == "1"]
        if not flagged:  # certains serveurs ne remplissent pas has_archive
            flagged = [r for r in rows if oldest <= _int(r.get("start_timestamp")) < now]
        programs = []
        for r in flagged:
            start, end = _int(r.get("start_timestamp")), _int(r.get("stop_timestamp"))
            if not start or start >= now or not r.get("start"):
                continue
            end = end if end > start else start + 3600
            minutes = max(1, math.ceil((end - start) / 60))
            title = _b64(r.get("title")) or "Programme"
            hours = f"{datetime.fromtimestamp(start):%H:%M}–{datetime.fromtimestamp(end):%H:%M}"
            live_now = end > now
            programs.append(Item(
                name=f"{hours}  {title}" + ("  (en cours)" if live_now else ""),
                url=self.timeshift_url(channel.stream_id, str(r.get("start")), minutes),
                group=day_label(start), logo=channel.logo, kind="program",
                key=f"x:prog:{channel.stream_id}:{start}", stream_id=channel.stream_id,
                plot=_b64(r.get("description")), start=start, end=end, parent=channel,
                duration=f"{minutes} min", info_loaded=True, extra={"title": title},
            ))
        programs.sort(key=lambda p: p.start, reverse=True)
        return programs


_STREAM_RE = re.compile(r"^(https?://[^/]+)/(?:live/)?([^/]+)/([^/]+)/(\d+)(?:\.\w+)?$", re.IGNORECASE)


def client_from_stream_url(url: str):
    """Déduit un client Xtream d'une URL de flux (http://hôte/user/mdp/123.ts) : (client, stream_id) ou None."""
    m = _STREAM_RE.match(url.strip())
    if not m:
        return None
    return XtreamClient(m.group(1), unquote(m.group(2)), unquote(m.group(3))), m.group(4)
