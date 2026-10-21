"""Empêche la mise en veille de Windows pendant une lecture.

En diffusion, c'est le PC qui envoie la vidéo à la télé, mais rien ne s'affiche ici : Windows croyait
le PC inutilisé et se mettait en veille au bout de quelques minutes, ce qui coupait la télé.
L'écran reste allumé lui aussi : sur les portables récents (« veille moderne »), un écran qui s'éteint
met le PC en veille malgré la demande « système requis ». La session peut toujours être verrouillée.
"""
import sys

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002

_awake = False


def keep_awake(on: bool) -> None:
    """True : ni veille ni extinction de l'écran ; False : Windows reprend la main.
    À appeler toujours depuis le même thread (l'état est attaché au thread appelant)."""
    global _awake
    if on == _awake or sys.platform != "win32":
        return
    try:
        import ctypes
        fn = ctypes.windll.kernel32.SetThreadExecutionState
        fn.argtypes = [ctypes.c_uint]
        fn.restype = ctypes.c_uint
        fn(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED if on else 0))
        _awake = on
    except (OSError, AttributeError):
        pass
