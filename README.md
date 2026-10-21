# IPTV Player (v2)

Lecteur de playlists IPTV pour PC : M3U (URL ou fichier) et Xtream Codes.
Python + PySide6 (interface) + libVLC (lecture des flux).

## Organisation du projet
```
iptv_player/
├─ main.py                 lanceur (python main.py)
├─ run_windows.bat         lancer depuis les sources (Windows)
├─ run_dev.bat             idem, sur une copie des données (%LOCALAPPDATA%\IPTVPlayer-dev)
├─ build_windows.bat       créer l'application dans dist\IPTVPlayer
├─ build_installer.bat     créer l'installeur dist\IPTVPlayer-Setup-<version>.exe (appli + VLC)
├─ installer/              IPTVPlayer.iss (script Inno Setup de l'installeur)
├─ requirements.txt
├─ assets/                 logo.svg (source) et icon.ico
├─ iptvplayer/             code de l'application
│  ├─ app.py               fenêtre principale : navigation, lecture, diffusion
│  ├─ ui.py                thème, icônes, accueil, fiche détaillée, rendu des listes
│  ├─ widgets.py           composants : zone vidéo, barres flottantes, connexion, modèle de liste
│  ├─ vlc_loader.py        recherche et chargement de libVLC
│  ├─ cast.py              diffusion Google Cast (découverte des télés, options VLC)
│  ├─ power.py             pas de mise en veille du PC pendant une lecture / une diffusion
│  ├─ update.py            mise à jour depuis l'appli (releases GitHub)
│  ├─ library.py           favoris, reprises de lecture, « Vu récemment »
│  ├─ cloud.py             compte du foyer (Firebase) : connexion, accès à la base Firestore
│  ├─ sync.py              synchro des profils et de leurs données avec le compte du foyer
│  ├─ images.py            affiches et logos (téléchargement, cache)
│  ├─ config.py            réglages et fichiers de données
│  └─ sources/             catalogue : playlist.py (M3U), xtream.py (API Xtream),
│                          catalog.py (cache disque), omdb.py (notes IMDb)
├─ tools/                  make_icon.py, slim_dist.bat, bundle_vlc.bat, build_windows_debug.bat, build_linux_mac.sh
├─ dist/                   application compilée (générée)
└─ .venv/                  environnement Python (généré)
```

## Prérequis
- **Python 3.10+** (64 bits)
- **VLC** (même architecture que Python : 64 bits). libVLC est utilisé comme moteur de lecture.
  Installation classique ou **dossier VLC portable** : l'appli cherche automatiquement `libvlc.dll` dans un dossier `vlc` à côté du programme, dans `Téléchargements\vlc`, ou dans Program Files. Sinon, elle te demande le dossier au lancement et s'en souvient (`vlc_dir` dans `settings.json`).

## Lancer depuis les sources
- Windows : double-clic sur `run_windows.bat` (sans fenêtre console ; le premier lancement installe les dépendances)
- Linux / macOS :
  ```
  python3 -m venv .venv && source .venv/bin/activate
  pip install -r requirements.txt
  python main.py
  ```

Pour essayer une version en cours sans risquer les données de l'appli installée : `run_dev.bat` (copie réglages et profils dans `%LOCALAPPDATA%\IPTVPlayer-dev` au premier lancement ; supprimer ce dossier pour repartir des données actuelles). Le dossier de données peut aussi être choisi avec la variable d'environnement `IPTVPLAYER_DATA`.

## Créer l'exécutable (recommandé : démarrage le plus rapide, ~63 Mo)
- Windows : `build_windows.bat` → dossier `dist\IPTVPlayer\` (lancer `IPTVPlayer.exe`)
- Linux / macOS : `./tools/build_linux_mac.sh` → `dist/IPTVPlayer/IPTVPlayer`

Le dossier `dist\IPTVPlayer` est autonome : on peut le déplacer où l'on veut, et supprimer `.venv` (~235 Mo) si on ne lance plus l'appli depuis les sources.
Ce dossier seul nécessite que **VLC soit installé** sur la machine qui le lance (voir l'installeur ci-dessous pour s'en passer).
Le script compile en mode « dossier » (pas `--onefile`, qui décompresse tout à chaque lancement) puis `tools/slim_dist.bat` retire les fichiers Qt inutiles.
Logo : `assets/logo.svg` (source) et `assets/icon.ico` (icône de la fenêtre et de l'exécutable). Si le logo change, régénérer l'icône avec `.venv\Scripts\python.exe tools\make_icon.py`.
Certains antivirus signalent à tort les exécutables PyInstaller : c'est un faux positif connu.

## Créer l'installeur Windows (pour installer l'appli sur un autre PC)
`build_installer.bat` → `dist\IPTVPlayer-Setup-<version>.exe` (~53 Mo). La version est `__version__` dans `iptvplayer/__init__.py` : l'augmenter avant chaque nouvel installeur (l'appli s'en sert pour savoir si elle est à jour).
Cet installeur contient tout : l'application **et VLC** (rien d'autre à installer sur le PC cible). Il crée les raccourcis (menu Démarrer, bureau en option) et une entrée de désinstallation ; par défaut il s'installe pour l'utilisateur courant, sans droits administrateur. Une mise à jour = lancer le nouvel installeur par-dessus ; les réglages (`%APPDATA%`) sont conservés.

### Mise à jour depuis l'appli
L'appli installée cherche une nouvelle version 8 s après le démarrage (et via *☰ > Mise à jour*). Si elle en trouve une, elle propose de la télécharger, lance l'installeur en mode silencieux, se ferme, puis l'installeur la relance (réglages, favoris et reprises conservés).

Les versions viennent de la page *Releases* du dépôt GitHub `pauljean445/app_iptv_pc` (constante `REPO` dans `iptvplayer/update.py`), qui doit être **public** : un dépôt privé n'est pas accessible sans identifiants. Pour garder le code privé, créer un dépôt public vide servant seulement aux installeurs et y faire pointer `REPO`.

Publier une version :
1. augmenter `__version__` dans `iptvplayer/__init__.py` (ex. `1.2.0`) ;
2. lancer `build_installer.bat` ;
3. sur GitHub : *Releases* > *Draft a new release*, tag `v1.2.0`, joindre `dist\IPTVPlayer-Setup-1.2.0.exe`, décrire les nouveautés (affichées dans l'appli), *Publish release*.

Une version installée avant la 1.1.0 ne sait pas se mettre à jour : installer une fois la 1.1.0 à la main.

Prérequis sur le PC qui **crée** l'installeur :
- ceux de `build_windows.bat` ;
- **VLC 64 bits** installé (copié dans `dist\IPTVPlayer\vlc` par `tools\bundle_vlc.bat`, sans `plugins\gui`) ; autre dossier VLC : `set VLC_DIR=C:\chemin\vers\vlc` avant de lancer le script ;
- **Inno Setup 6** : `winget install JRSoftware.InnoSetup`. Le script de l'installeur est `installer\IPTVPlayer.iss`.

L'installeur n'est pas signé : au premier lancement, Windows SmartScreen peut afficher « Windows a protégé votre ordinateur » → *Informations complémentaires* → *Exécuter quand même*.
VLC est sous licence GPL/LGPL : son fichier `COPYING.txt` est inclus dans `vlc\`.

## Utilisation
Pas de barre de menus : toutes les commandes sont dans le bouton **☰** en haut à droite, et les raccourcis clavier restent actifs.

Au premier lancement, la fenêtre **Connexion IPTV** s'ouvre (☰ > Connexion IPTV…, `Ctrl+K`) :
- **Xtream Codes** : serveur, utilisateur, mot de passe (l'appli construit l'URL M3U).
- **URL M3U** : colle l'URL de ta playlist.
- **Fichier M3U** : fichier .m3u / .m3u8 local.

En **Xtream Codes** (ou avec une URL `get.php?username=…&password=…`), l'appli utilise l'API du fournisseur (`player_api.php`) : les catégories Direct / Films / Séries sont celles du fournisseur, sans devinette. Si l'API ne répond pas, elle se rabat sur la playlist M3U.

**Profils** : bouton du profil (pastille et nom) en haut à droite, à côté de ☰. Chaque profil a sa propre source IPTV, ses favoris, ses lectures en cours, son « Vu récemment » et ses choix de langue ; le volume, la taille de la fenêtre et la clé OMDb sont communs. « Nouveau profil… » propose la même IPTV que le profil en cours (catalogue repris, rien à retélécharger) ou une autre (identifiants demandés à l'ouverture du profil). Avec plusieurs profils, l'appli demande « Qui regarde ? » au démarrage (désactivable dans le menu du profil). *Gérer les profils > Réinitialiser* efface les favoris, lectures en cours, « Vu récemment », épisodes vus et choix de langue d'un profil (à faire après un changement de fournisseur IPTV) ; le profil et sa source sont gardés. Données : `%APPDATA%\IPTVPlayer\profiles\<id>\` (`profile.json`, `library.json`, `catalog.bin`) ; les données d'avant les profils deviennent le profil « Principal ».

**Compte du foyer** : obligatoire. Au premier lancement (ou après *☰ > Compte du foyer > Se déconnecter*), l'appli demande l'email et le mot de passe du compte Firebase du foyer, et se ferme sans connexion. Une fois connecté, elle démarre ensuite directement, même si le serveur est momentanément injoignable. Le compte sert à partager profils, favoris, reprises et langues avec la TV et les autres PC. Les comptes sont créés par l'administrateur dans la console Firebase (*Authentication > Users*), les inscriptions depuis l'appli sont fermées, et les règles Firestore n'autorisent que les UID listés, chacun dans `households/<uid>`. Seule la clé publique du projet est dans le code (`cloud.py`) ; ne jamais y mettre de clé de compte de service. Le mot de passe n'est pas enregistré : `account.json` garde l'email, l'UID et le jeton de session, chiffré par Windows (DPAPI).

**Synchronisation** : la liste des profils (nom, couleur) et, pour chaque profil, favoris (et leur ordre), lectures en cours, « Vu récemment », épisodes vus et choix de langue sont partagés entre tous les appareils du foyer. La source IPTV, la dernière chaîne et les réglages de l'appareil restent propres à chaque appareil (un profil arrivé d'un autre appareil reprend la source IPTV du profil en cours : même abonnement dans un foyer).
- Quand : au lancement (liste des profils, avant « Qui regarde ? »), toutes les 30 s (liste des profils toutes les 2 min, aussitôt après un changement de profils), au changement de profil et à la fermeture.
- Règle : pour chaque entrée, la modification la plus récente gagne, ajout comme suppression (un favori retiré sur la TV l'est aussi sur le PC). Même film sur le même profil sur deux écrans : la dernière position enregistrée l'emporte.
- Serveur injoignable : l'appli fonctionne normalement avec ses données et rattrape au passage suivant.
- PC jamais synchronisé (données d'avant la synchro) : si le foyer n'a encore aucun profil, ceux du PC sont envoyés avec leurs données ; sinon le PC prend les profils du foyer (les siens sont laissés de côté).
- Changement de compte sur un PC : il prend les profils du nouveau foyer, ou un profil « Principal » neuf si ce foyer est vide (même source IPTV). Rien de l'ancien foyer n'est envoyé dans le nouveau ; ses données restent sur son compte et reviennent si l'on s'y reconnecte.
- Un profil supprimé sur un appareil disparaît des autres, avec ses données sur le serveur.
- Base Firestore : `households/<uid>` (liste des profils) et `households/<uid>/profiles/<id>` (données du profil, même forme que `library.json`). Chaque passage lit 1 à 2 documents et n'écrit que les champs plus récents sur ce PC.

L'appli s'ouvre sur l'**accueil** (onglet Accueil, `Ctrl+H`) : quatre bandes horizontales (flèches ‹ ›, Maj+molette ou pavé tactile pour les faire défiler ; la page défile si l'écran est trop petit).
- **Direct** et **Replays** : tes chaînes favorites. Un clic lance la chaîne (Direct) ou ouvre ses programmes (Replays).
- **Films** et **Séries** : ce que tu as commencé, avec la progression. Un clic reprend la lecture (pour une série, l'épisode en cours ou le suivant).
- Pour retirer une vignette : la croix en haut à droite (au survol), clic droit ou touche Suppr. Une chaîne quitte les favoris, un film ou une série les lectures en cours (position de reprise comprise).
- Un clic sur le titre d'un bloc ouvre l'onglet correspondant. Pendant une lecture, le bouton « En lecture » du bandeau y ramène.

Quatre onglets :
- **Direct** : les chaînes en direct.
- **Films** : la liste reste à gauche ; la fiche du film sélectionné (grande affiche, note, résumé complet, réalisateur, acteurs) occupe la partie droite. La vidéo prend sa place pendant la lecture, la fiche revient à l'arrêt.
- **Séries** : une ligne par série ; double-clic → liste des épisodes (filtre par saison), `← Retour` / `Retour arrière` pour revenir.
- **Replays** : les chaînes en direct qui proposent le replay (durée entre parenthèses) ; double-clic → programmes passés (filtre par jour), double-clic pour les regarder. Clic droit → « Regarder en direct ».

Dans chaque onglet, la liste des catégories propose aussi :
- **★ Favoris** : `Ctrl+D`, clic droit ou bouton de la fiche pour ajouter / retirer. Pour changer l'ordre : glisser-déposer une ligne, `Ctrl+↑` / `Ctrl+↓`, ou clic droit > Monter / Descendre / Mettre en premier / en dernier (pas pendant une recherche). L'ordre est repris dans les bandes Direct et Replays de l'accueil.
- **🕘 Vu récemment** (Films et Séries) : les films et séries entamés, du plus récent au plus ancien. Film : double-clic pour **reprendre la lecture** là où elle s'était arrêtée (bouton « Depuis le début » dans la fiche). Série : bouton « Reprendre SxxEyy » de la fiche, ou double-clic pour ouvrir les épisodes, l'épisode en cours étant présélectionné (▶ % dans la liste, ✓ = vu). Un film disparaît de la liste quand il est vu jusqu'au bout ; une série quand tous ses épisodes sont vus (clic droit sur un épisode : « Marquer comme vu »).

**Notes IMDb** : le fournisseur donne une note (souvent TMDB). Pour afficher la vraie note IMDb, crée une clé gratuite sur https://www.omdbapi.com/apikey.aspx et saisis-la dans *☰ > Clé OMDb*. Les notes sont mises en cache (limite de 1000 requêtes / jour pour la clé gratuite).

Playlist M3U simple (hors Xtream) : un flux sans extension vidéo (.ts, .m3u8) est classé en direct ; les fichiers vidéo (.mkv, .mp4…) en films, ou en épisodes s'ils contiennent `SxxEyy` (ou si le groupe contient un mot de `series_keywords` dans `settings.json`).

Films, épisodes et replays ont une barre de progression (clic pour se déplacer) ; `Maj+←` / `Maj+→` reculent / avancent de 10 s.

**Replays : déplacement à la minute.** Le serveur découpe les enregistrements en blocs d'une minute et renvoie toujours le début d'un bloc, même quand on lui demande un endroit précis du fichier (vérifié octet par octet). VLC, qui ne connaît pas la durée d'un replay, ignore en plus les demandes « aller à telle heure ». L'appli demande donc au serveur le replay qui commence à la minute voulue : les boutons et `←` / `→` avancent / reculent d'une minute, les grands boutons de 5 minutes, et un clic sur la barre va à la minute la plus proche. Les clics rapprochés sont regroupés en un seul déplacement. Une relance (passage sur la télé, reconnexion) reprend au début de la minute en cours.

**Langues et sous-titres** : la fiche d'un film, d'une série ou d'un épisode liste les langues et sous-titres du fichier (lus en 1 à 4 s). Un bouton de langue lance la lecture dans cette langue (pour une série : l'épisode que « Lire » lancerait, le premier si elle n'est pas commencée) ; les sous-titres se choisissent avant. Le choix, fait sur la fiche ou pendant la lecture, est mémorisé par film et par série (`prefs` dans le `library.json` du profil) et appliqué aux épisodes suivants, même quand l'ordre des pistes change d'un fichier à l'autre.

**Enchaînement automatique** : à la fin d'un épisode, l'épisode suivant démarre aussitôt (saison suivante comprise) ; à la fin d'un replay, le programme suivant de la même chaîne (utile quand une émission déborde sur le créneau d'après). Fonctionne aussi en diffusion sur la télé. `N` ou le bouton « Épisode suivant » / « Programme suivant » lance la suite avant la fin.

**Direct** : la pastille « En direct » devient « Différé : 2 min 05 s » après une pause (le direct reprend là où il s'était arrêté) ; un clic dessus revient au direct.

**Diffuser sur la télé (Chromecast, Google TV, télé « Chromecast intégré »)** : bouton **Diffuser** en haut à droite du lecteur (aussi en plein écran). Choisis la télé : la lecture continue dessus, à la même position ; « Cet ordinateur » la ramène sur le PC. VLC convertit à la volée les formats que la télé ne lit pas ; pour le direct et les replays, le son est toujours converti en AAC (beaucoup de chaînes diffusent en MP2 ou E-AC3, illisibles par les Chromecast). Seules la langue et les sous-titres choisis sont envoyés à la télé ; en changer pendant une diffusion relance le flux à la même position. Par défaut, aucun sous-titre n'est envoyé à la télé : certaines chaînes en ajoutent par moments (télétexte, sourds et malentendants) et la diffusion s'interrompait. Les sous-titres choisis explicitement pendant la diffusion d'un film ou d'une série sont incrustés dans l'image (conversion en 720p, nécessaire pour qu'un Chromecast les affiche).
- Films, séries et replays passent par une copie du module Chromecast de VLC qui les annonce comme « non direct » (sinon la télé affiche « Différé : 1 s » à chaque pause). Elle est créée automatiquement dans `%APPDATA%\IPTVPlayer\vlc_plugins` ; le direct garde le module d'origine.
- Une chaîne qui ne s'affiche pas sur la télé : menu Diffuser > **Mode compatible pour cette chaîne** (image convertie en H.264 720p et désentrelacée). Il s'active aussi tout seul si VLC détecte l'échec, et reste mémorisé pour la chaîne.
- En cas d'échec, les erreurs de VLC sont dans `%APPDATA%\IPTVPlayer\vlc.log` (remis à zéro à chaque lancement).
- La télé doit être allumée et sur le même réseau que le PC.
- Pendant une diffusion (même en pause), le PC ne se met pas en veille et son écran reste allumé : c'est lui qui envoie la vidéo à la télé (sur les portables récents, un écran qui s'éteint tout seul met le PC en veille). L'écran d'un PC fixe peut être éteint à la main avec son bouton. Si le PC se met quand même en veille (capot fermé…), la lecture reprend au réveil là où elle s'était arrêtée.
- La télé vient chercher la vidéo sur le PC : à la première diffusion, Windows demande d'autoriser IPTV Player dans le pare-feu. Accepte-le ; idéalement, mets ton réseau domestique en profil **Privé** (Paramètres > Réseau et Internet > Wi-Fi > ton réseau).

Puis : recherche par nom (sans tenir compte des accents), filtre par catégorie, double-clic (ou Entrée) pour lancer.

| Raccourci | Action |
|---|---|
| Entrée / double-clic | Lancer la chaîne sélectionnée |
| PgUp / PgDown | Précédent / suivant (chaîne, épisode…) |
| Espace | Pause / lecture |
| M | Muet |
| F11 ou double-clic vidéo | Plein écran |
| Échap | Quitter le plein écran |
| Ctrl+F | Rechercher |
| Ctrl+L | Masquer / afficher la liste |
| F5 | Recharger la playlist |
| Ctrl+K | Connexion IPTV |
| Ctrl+D | Ajouter / retirer des favoris |
| Ctrl+↑ / Ctrl+↓ | Monter / descendre le favori sélectionné (★ Favoris) |
| Ctrl+H | Accueil |
| N | Épisode suivant (séries) / programme suivant (replays) |
| B / V | Langue suivante / sous-titres suivants |
| Retour arrière ou Alt+← | Revenir à la liste (épisodes, replays) |
| Maj+← / Maj+→ | Reculer / avancer de 10 s (films, séries, replays) |

Si le flux se coupe, l'appli tente de se reconnecter automatiquement (5 essais) ; pour un film ou un épisode, elle reprend à la position atteinte.

## Réglages
Fichier `settings.json` dans `%APPDATA%\IPTVPlayer` (Windows) ou `~/.config/IPTVPlayer` (Linux).
- `network_cache_ms` (défaut 1500) : augmente-le (3000, 5000) si la lecture saccade.
- Les identifiants y sont stockés **en clair** si « Mémoriser la connexion » est coché. Décoche la case pour ne rien enregistrer.
- `profiles\<id>\profile.json` : réglages du profil propres à cet appareil (source IPTV, dernière lecture).
- `profiles\<id>\library.json` : favoris, positions de lecture, « Vu récemment », épisodes vus et langues choisies (données prévues pour la synchronisation entre appareils). Chaque entrée porte l'heure de sa dernière modification et chaque suppression laisse une trace datée (`deleted`), effacée après 3 mois ; les lectures en cours ne sont jamais purgées.
- `meta_cache.json` : notes IMDb.
- `catalog.bin` (~1,5 Mo) : copie du catalogue Xtream, affichée instantanément au lancement puis actualisée en arrière-plan (sans identifiants ; supprimable sans risque).
- `images\` : affiches (petite taille) et logos en cache, plafonné à 150 Mo (les plus anciennes sont supprimées automatiquement).

## Performances
- Démarrage : la fenêtre s'affiche en ~0,4 s et le catalogue (23 000 entrées) est disponible quasi immédiatement depuis le cache ; l'actualisation se fait en arrière-plan et ne reconstruit rien si le catalogue n'a pas changé (sinon l'onglet, le filtre, la sélection et la position dans la liste sont conservés).
- VLC s'initialise en parallèle du chargement du catalogue.
- Listes mises en page par lots : la première page s'affiche en quelques millisecondes même avec 13 000 films.
- Affiches TMDB téléchargées en petite taille et décodées directement à la taille d'affichage.
- Dépendance `PySide6-Essentials` (Qt de base) au lieu de `PySide6` complet : environnement Python ~235 Mo au lieu de ~680 Mo.

## En cas de problème
L'appli écrit un journal dans `%APPDATA%\IPTVPlayer\iptvplayer.log` (dernier lancement) et affiche les erreurs de démarrage dans une fenêtre.
`tools\build_windows_debug.bat` génère une version avec console pour diagnostiquer.

## Limites connues
- Pas de guide des programmes (EPG) pour les chaînes en direct (uniquement pour les replays).
- Résumés : ils viennent du fournisseur. Chez le tien, ~94 % des films et ~83 % des séries en ont, mais seulement ~30 % des épisodes ; un épisode sans résumé affiche celui de la série.
- Replays : disponibles avec l'API Xtream (ou une playlist dont les URL sont au format Xtream).
- Linux : forcé en mode X11 (XWayland), car libVLC ne s'intègre pas dans une fenêtre Wayland native.
- Le double-clic sur la vidéo pour le plein écran peut ne pas fonctionner selon le système ; F11 fonctionne toujours.
