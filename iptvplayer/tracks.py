"""Pistes audio et sous-titres d'un film ou d'un épisode, lues avant la lecture (préanalyse de VLC).

Sert à proposer les langues sur la fiche et à garder la même langue d'un épisode à l'autre. Les
numéros de pistes changent d'un fichier à l'autre (VF en 1re piste ici, en 2e là) : un choix est donc
mémorisé par langue + libellé ({"lang": "fre", "desc": "VFF"}), puis retrouvé dans chaque fichier.
"""
import ctypes
import time
import unicodedata
from dataclasses import dataclass

# Codes ISO 639 (2 ou 3 lettres) -> code de référence
_ALIASES = {"fr": "fre", "fra": "fre", "en": "eng", "es": "spa", "de": "ger", "deu": "ger", "it": "ita",
            "pt": "por", "nl": "dut", "nld": "dut", "sv": "swe", "no": "nor", "nb": "nor", "da": "dan",
            "fi": "fin", "ru": "rus", "pl": "pol", "tr": "tur", "ar": "ara", "ja": "jpn", "ko": "kor",
            "zh": "chi", "zho": "chi", "hi": "hin", "he": "heb", "el": "gre", "ell": "gre", "ro": "rum",
            "ron": "rum", "cs": "cze", "ces": "cze", "hu": "hun", "uk": "ukr"}
_NAMES = {"fre": "Français", "eng": "Anglais", "spa": "Espagnol", "ger": "Allemand", "ita": "Italien",
          "por": "Portugais", "dut": "Néerlandais", "swe": "Suédois", "nor": "Norvégien", "dan": "Danois",
          "fin": "Finnois", "rus": "Russe", "pol": "Polonais", "tur": "Turc", "ara": "Arabe",
          "jpn": "Japonais", "kor": "Coréen", "chi": "Chinois", "hin": "Hindi", "heb": "Hébreu",
          "gre": "Grec", "rum": "Roumain", "cze": "Tchèque", "hun": "Hongrois", "ukr": "Ukrainien"}


def norm_lang(code: str) -> str:
    code = (code or "").strip().lower()
    code = _ALIASES.get(code, code)
    return "" if code in ("und", "unk", "mis", "zxx") else code


@dataclass(frozen=True)
class Track:
    kind: str   # "audio" ou "spu"
    id: int     # identifiant VLC dans CE fichier
    lang: str   # code de référence (« fre », « eng »…) ou ""
    desc: str   # libellé donné par le fichier (« VFF », « VO », « Forcés »…)

    @property
    def label(self) -> str:
        name = _NAMES.get(self.lang) or self.lang.upper()
        desc = self.desc.strip()
        if not desc:
            return name or f"Piste {self.id}"
        if not name or name.lower() in desc.lower():
            return desc
        return f"{name} · {desc}"

    def pref(self) -> dict:
        return {"lang": self.lang, "desc": self.desc}


def match(tracks: list[Track], kind: str, pref) -> int | None:
    """Identifiant de la piste qui correspond au choix mémorisé (None : rien à imposer, -1 : désactivé)."""
    if pref is None:
        return None
    if pref == "off":
        return -1
    same = [t for t in tracks if t.kind == kind and t.lang == pref.get("lang", "")]
    for t in same:
        if t.desc.strip().lower() == (pref.get("desc") or "").strip().lower():
            return t.id
    return same[0].id if same else None  # même langue, autre libellé (ex. « VF » au lieu de « VFF »)


def is_pref(t: Track, pref) -> bool:
    return isinstance(pref, dict) and t.lang == pref.get("lang") and \
        t.desc.strip().lower() == (pref.get("desc") or "").strip().lower()


class _MediaTrack(ctypes.Structure):
    # libvlc_media_track_t (libVLC 3). Défini ici : la version de python-vlc décale les champs.
    _fields_ = [("codec", ctypes.c_uint32), ("fourcc", ctypes.c_uint32), ("id", ctypes.c_int),
                ("type", ctypes.c_int), ("profile", ctypes.c_int), ("level", ctypes.c_int),
                ("detail", ctypes.c_void_p), ("bitrate", ctypes.c_uint), ("language", ctypes.c_char_p),
                ("description", ctypes.c_char_p)]


_KINDS = {0: "audio", 2: "spu"}  # 1 = vidéo (ignorée)
_api = None


def _functions(vlc):
    global _api
    if _api is None:
        get = vlc.dll.libvlc_media_tracks_get
        get.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.POINTER(ctypes.POINTER(_MediaTrack)))]
        get.restype = ctypes.c_uint
        release = vlc.dll.libvlc_media_tracks_release
        release.argtypes = [ctypes.POINTER(ctypes.POINTER(_MediaTrack)), ctypes.c_uint]
        release.restype = None
        _api = get, release
    return _api


def _text(raw) -> str:
    # Forme composée : « ç » écrit en deux caractères dans certains fichiers ne se comparerait pas
    return unicodedata.normalize("NFC", raw.decode("utf-8", "replace")) if raw else ""


def probe(vlc, instance, url: str, timeout: float = 6.0) -> list[Track]:
    """Pistes audio / sous-titres du fichier (bloquant : à appeler dans un thread). [] si illisible."""
    get, release = _functions(vlc)
    media = instance.media_new(url)
    try:
        media.parse_with_options(vlc.MediaParseFlag.network, int(timeout * 1000))
        end = time.time() + timeout + 0.5
        while time.time() < end:
            status = media.get_parsed_status()
            if getattr(status, "value", status):  # 0 = analyse en cours
                break
            time.sleep(0.05)
        arr = ctypes.POINTER(ctypes.POINTER(_MediaTrack))()
        n = get(media, ctypes.byref(arr))
        out = []
        for k in range(n):
            t = arr[k].contents
            if t.type in _KINDS:
                out.append(Track(_KINDS[t.type], t.id, norm_lang(_text(t.language)), _text(t.description)))
        if n:
            release(arr, n)
        return out
    finally:
        media.release()
