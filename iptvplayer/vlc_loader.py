"""Recherche et chargement de libVLC (installation standard OU dossier VLC « portable »)."""
import os
import sys
from pathlib import Path

from . import config


def app_dir() -> Path:
    """Dossier du programme : celui de l'exécutable, ou la racine du projet en mode sources."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def resolve_vlc_dir(path):
    """Retourne le dossier contenant libvlc.dll (path lui-même ou un sous-dossier direct), sinon None."""
    if not path:
        return None
    p = Path(path)
    if (p / "libvlc.dll").is_file():
        return p
    try:
        for sub in p.iterdir():
            if sub.is_dir() and (sub / "libvlc.dll").is_file():
                return sub
    except OSError:
        pass
    return None


def use_vlc_dir(path) -> None:
    """Indique à python-vlc où trouver libvlc.dll et ses plugins."""
    p = Path(path)
    os.environ["PYTHON_VLC_LIB_PATH"] = str(p / "libvlc.dll")
    plugins = p / "plugins"
    if plugins.is_dir():
        os.environ["PYTHON_VLC_MODULE_PATH"] = str(plugins)
        os.environ["VLC_PLUGIN_PATH"] = str(plugins)
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(p))
    os.environ["PATH"] = str(p) + os.pathsep + os.environ.get("PATH", "")


def try_import_vlc():
    try:
        import vlc as module
        return module, ""
    except Exception as exc:  # VLC absent ou architecture différente
        return None, str(exc)


def load():
    """Retourne (module vlc ou None, message d'erreur)."""
    vlc, error = None, ""
    if sys.platform == "win32":
        candidates = [
            config.load().get("vlc_dir", ""),
            os.environ.get("VLC_DIR", ""),
            app_dir() / "vlc",
            app_dir(),
            Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "VideoLAN" / "VLC",
            Path.home() / "Downloads" / "vlc",
            Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "VideoLAN" / "VLC",
        ]
        # On essaie chaque dossier jusqu'à en trouver un qui se charge (ex. ignore un VLC 32 bits).
        for c in candidates:
            found = resolve_vlc_dir(c)
            if found is None:
                continue
            print("Essai du dossier VLC :", found)
            use_vlc_dir(found)
            vlc, error = try_import_vlc()
            if vlc is not None:
                print("Dossier VLC utilisé :", found)
                break
            print("  -> échec :", error)
    if vlc is None:
        vlc, error = try_import_vlc()
    return vlc, error
