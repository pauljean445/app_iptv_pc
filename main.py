"""IPTV Player - lecteur de playlists IPTV (M3U / Xtream Codes) avec PySide6 + libVLC.

Lanceur minimal : le script principal n'est jamais mis en cache par Python (il est recompilé
à chaque lancement), alors que le paquet iptvplayer l'est (__pycache__). On gagne ~50 ms au démarrage.
"""
import sys

from iptvplayer.app import run

sys.exit(run())
