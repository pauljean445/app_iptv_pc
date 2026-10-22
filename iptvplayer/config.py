"""Sauvegarde / chargement des réglages de l'application (fichiers JSON), profils compris.

Réglages communs : settings.json (volume, fenêtre, clé OMDb…, liste des profils).
Chaque profil a son dossier profiles/<id>/ : profile.json (réglages propres à cet appareil : source IPTV,
dernière lecture…), library.json (favoris, reprises, « Vu récemment », langues : à synchroniser entre
appareils) et catalog.bin (catalogue de sa source).
"""
import json
import os
import secrets
import shutil
import sys
import time
from pathlib import Path

DEFAULTS = {
    "mode": "xtream",          # "xtream" | "url" | "file"
    "server": "",
    "username": "",
    "password": "",
    "stream_format": "ts",     # "ts" | "m3u8"
    "url": "",
    "file": "",
    "remember": True,          # mémoriser les identifiants (en clair)
    "volume": 80,
    "last_key": "",            # dernière entrée lue (sélectionnée au démarrage)
    "network_cache_ms": 1500,  # tampon réseau de VLC (augmenter si ça saccade)
    # Playlists M3U hors Xtream : mots-clés (dans le nom du groupe) désignant des séries.
    "series_keywords": ["séries", "series", "série", "saison", "season"],
    "omdb_api_key": "",        # clé gratuite omdbapi.com pour afficher les notes IMDb
    "vlc_dir": "",             # dossier de VLC si installation portable (contient libvlc.dll)
    "ask_profile": True,       # « Qui regarde ? » au démarrage quand il y a plusieurs profils
    "start_profile": "",       # sinon, profil ouvert au démarrage (choisi avec l'interrupteur ; "" : le dernier utilisé)
}

# Réglages propres à chaque profil sur cet appareil ; tous les autres sont communs
PROFILE_KEYS = ("mode", "server", "username", "password", "stream_format", "url", "file", "remember",
                "source_t", "last_key", "last_tab", "series_keywords", "cast_compat")
SOURCE_KEYS = ("mode", "server", "username", "password", "stream_format", "url", "file", "remember")
PROFILE_COLORS = ("#7B66FF", "#FF5470", "#2EC4B6", "#FFB020", "#3A86FF", "#8AC926")
PROFILE_FILES = ("library.json", "catalog.bin")  # données d'un profil (avant les profils : à la racine)

_profile = ""  # identifiant du profil en cours


def asset_path(name: str) -> str:
    """Chemin d'un fichier du dossier assets (sources ou application compilée)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return str(base / "assets" / name)


def config_dir() -> Path:
    if os.environ.get("IPTVPLAYER_DATA"):  # dossier de données à part (essais depuis les sources : run_dev.bat)
        return Path(os.environ["IPTVPLAYER_DATA"])
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", str(Path.home())))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return base / "IPTVPlayer"


def config_path() -> Path:
    return config_dir() / "settings.json"


def current_profile() -> str:
    return _profile


def set_profile(pid: str) -> None:
    global _profile
    _profile = pid


def profile_dir(pid: str | None = None) -> Path:
    return config_dir() / "profiles" / (pid or _profile)


def _read(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(path: Path, data: dict, indent=None) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        pass


def _migrate(data: dict) -> dict:
    """Première version avec profils : les données existantes deviennent le profil « Principal »."""
    if data.get("profiles"):
        return data
    pid = "p1"
    folder = profile_dir(pid)
    folder.mkdir(parents=True, exist_ok=True)
    for name in PROFILE_FILES:
        old = config_dir() / name
        if old.exists() and not (folder / name).exists():
            try:
                os.replace(old, folder / name)
            except OSError:
                pass
    _write(folder / "profile.json", {k: data[k] for k in PROFILE_KEYS if k in data}, indent=2)
    data = {k: v for k, v in data.items() if k not in PROFILE_KEYS}
    data["profiles"] = [{"id": pid, "name": "Principal", "color": PROFILE_COLORS[0]}]
    data["profile"] = pid
    _write(config_path(), data, indent=2)
    return data


def _move_track_prefs(data: dict) -> None:
    """Langues choisies : de profile.json (propre à l'appareil) vers library.json (synchronisé avec le profil)."""
    for prof in data["profiles"]:
        folder = profile_dir(prof["id"])
        own = _read(folder / "profile.json")
        if "track_prefs" not in own:
            continue
        lib = _read(folder / "library.json")
        lib["track_prefs"] = {**own.pop("track_prefs"), **(lib.get("track_prefs") or {})}
        _write(folder / "library.json", lib)
        _write(folder / "profile.json", own, indent=2)


def load() -> dict:
    """Réglages communs + ceux du profil en cours (le dernier utilisé si aucun n'est choisi)."""
    data = _migrate(_read(config_path()))
    _move_track_prefs(data)
    ids = [p["id"] for p in data["profiles"]]
    if _profile not in ids:
        set_profile(data.get("profile") if data.get("profile") in ids else ids[0])
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in data.items() if k not in PROFILE_KEYS})
    cfg.update(_read(profile_dir() / "profile.json"))
    cfg["profile"] = _profile
    return cfg


def save(cfg: dict, pid: str | None = None) -> None:
    """Enregistre les réglages communs et ceux du profil pid (par défaut : le profil en cours)."""
    pid = pid or _profile
    common = {k: v for k, v in cfg.items() if k not in PROFILE_KEYS}
    common["profile"] = pid
    own = {k: cfg[k] for k in PROFILE_KEYS if k in cfg}
    if not own.get("remember"):
        # On n'écrit pas les identifiants sur le disque si l'utilisateur ne le souhaite pas.
        own["password"] = ""
        own["url"] = ""
    _write(config_path(), common, indent=2)
    _write(profile_dir(pid) / "profile.json", own, indent=2)


def save_common(cfg: dict, pid: str) -> None:
    """Enregistre seulement les réglages communs, avec pid comme profil à rouvrir (profil supprimé)."""
    common = {k: v for k, v in cfg.items() if k not in PROFILE_KEYS}
    common["profile"] = pid
    _write(config_path(), common, indent=2)


# ---- Gestion des profils ------------------------------------------------- #
def create_profile(cfg: dict, name: str, color: str, copy_source_from: dict | None = None) -> str:
    """Ajoute un profil (sa source IPTV copiée depuis copy_source_from, sinon vide). Retourne son id."""
    pid = "p" + secrets.token_hex(4)  # unique aussi entre les appareils d'un même compte (synchronisation)
    init_profile_folder(pid, copy_source_from)
    cfg["profiles"].append({"id": pid, "name": name, "color": color, "t": time.time()})
    return pid


def init_profile_folder(pid: str, copy_source_from: dict | None = None) -> None:
    """Dossier d'un profil sur ce PC, avec la source IPTV (et le catalogue) de copy_source_from s'il est donné
    (réglages d'un autre profil, « profile » = son id)."""
    folder = profile_dir(pid)
    folder.mkdir(parents=True, exist_ok=True)
    own = {}
    if copy_source_from:
        own = {k: copy_source_from[k] for k in SOURCE_KEYS if k in copy_source_from}
        if not own.get("remember"):
            own["password"] = own["url"] = ""
        # Même fournisseur : on reprend son catalogue, inutile de le retélécharger
        src = profile_dir(copy_source_from.get("profile")) / "catalog.bin"
        if src.exists():
            try:
                shutil.copyfile(src, folder / "catalog.bin")
            except OSError:
                pass
    _write(folder / "profile.json", own, indent=2)


def read_profile(pid: str) -> dict:
    """Réglages propres d'un profil (autre que celui en cours : sa source IPTV par exemple)."""
    return _read(profile_dir(pid) / "profile.json")


def write_profile(pid: str, data: dict) -> None:
    own = {k: data[k] for k in PROFILE_KEYS if k in data}
    if not own.get("remember", True):
        own["password"] = own["url"] = ""
    _write(profile_dir(pid) / "profile.json", own, indent=2)


def delete_profile(cfg: dict, pid: str) -> None:
    """Supprime un profil ; la trace datée (profiles_deleted) le fait disparaître des autres appareils."""
    cfg["profiles"] = [p for p in cfg["profiles"] if p["id"] != pid]
    cfg.setdefault("profiles_deleted", {})[pid] = time.time()
    shutil.rmtree(profile_dir(pid), ignore_errors=True)


def load_json(name: str, folder: Path | None = None) -> dict:
    """Lit un fichier JSON du dossier de l'appli (ou de folder) ; dict vide s'il est absent ou illisible."""
    return _read((folder or config_dir()) / name)


def save_json(name: str, data: dict, folder: Path | None = None) -> None:
    """Écrit un fichier JSON (via un fichier temporaire, sans risque de le corrompre)."""
    _write((folder or config_dir()) / name, data)
