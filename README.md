# CARE · Groupe 2 · Détection d'oubli dans l'habitacle

Banc de test et dashboard pour comparer **A1 (RGB seul)** et **A2 (RGB + thermique)**.

## Démarrer

**Sous Windows :** double-clic sur `lancer.bat`. Au premier lancement, l'environnement Python s'installe (quelques minutes), puis le dashboard s'ouvre sur http://localhost:5000.

- `lancer_demo.bat` : **mode démo**, sans matériel (flux et détections simulés). Utile pour prendre l'outil en main ou le montrer.
- En ligne de commande : `python app.py` ou `python app.py --demo`.

## Brancher le matériel (dans la voiture)

Le dashboard se branche sur les **4 caméras de la voiture**, jamais sur la webcam du PC :
les caméras sont choisies par leur **nom** (lu via `pygrabber` sous Windows, installé par
`lancer.bat`), et tout ce qui ressemble à une webcam intégrée (« Integrated », « Webcam »,
« FaceTime »…, liste dans `config.json` → `cameras.exclure`) est écarté.

1. Brancher les 4 caméras RGB et la thermique sur le hub USB actif, hub branché au PC.
2. Lancer `python lister_cameras.py` : il liste les caméras (la webcam du PC est signalée),
   ouvre un aperçu de chacune et demande la position filmée (1 = avant gauche… ; t = thermique ;
   Entrée = ignorer). Le résultat va dans `config.local.json` (propre au PC, hors git).
3. Lancer le dashboard : au démarrage, le terminal affiche quelle caméra filme quelle position.
   Dans le dashboard, survoler un flux affiche le périphérique ; une pastille orange signale
   un problème (webcam prise par erreur, index qui ont bougé…).
4. Si une caméra ne s'affiche pas, passer `resolution` à `[640, 360]` : le hub sature avec 4 flux 720p.

Sans l'assistant, `"index": "auto"` (valeur par défaut) prend les caméras libres hors webcam,
dans l'ordre : les 4 flux s'affichent, mais **les positions peuvent être mélangées**. Après un
débranchement / rebranchement sur d'autres ports, relancer `lister_cameras.py`.
Une caméra IP (si la voiture en a) se déclare avec `"url": "rtsp://…"` à la place de `index`.

## Déroulé d'un essai

1. Installer la scène, fermer les portes, sortir du véhicule.
2. Dans le dashboard, choisir le scénario et la variante. La vérité terrain se remplit seule et reste modifiable.
3. Cliquer sur **Lancer l'analyse**. Le banc analyse 10 images par caméra, puis affiche la décision : CRITIQUE, ALERTE ou RAS.
4. Le compteur « Répétition x / 10 » indique où on en est pour ce scénario.

Chaque essai enregistre **séparément** le verdict RGB et le verdict thermique. A1 et A2 sont donc évalués sur la même scène : la comparaison est appariée et il n'y a pas d'essai à refaire.

| Approche | Règle de décision « vivant » |
|---|---|
| A1 | Le détecteur voit une personne, un enfant, un chat ou un chien sur au moins une caméra |
| A2 | A1 **ou** la thermique voit une zone chaude (fusion OU, qui maximise le rappel) |

## Collecte d'images pour le dataset (v2)

Carte **Collecte dataset** du dashboard : indiquer ce qui est dans la scène (« clés console
centrale », « bébé siège auto », « vide »…), le nombre de prises et l'intervalle, puis
**Lancer la rafale**. Entre deux prises, déplacer l'objet / la poupée ou changer la lumière.
Les images identiques à la précédente (scène qui n'a pas bougé) sont écartées.

Images dans `data/essais/collecte/<jour>/<scène>/` (hors git : ce sont des photos de la
voiture), avec un `manifeste.csv`. Ensuite :

```
python outils/preparer_lot.py
```

→ un lot `datasets/lot-…zip` **pré-annoté par le modèle actuel**, à glisser dans Roboflow :
on corrige les boîtes au lieu de tout dessiner. Méthode complète :
[`entrainement/README.md`](entrainement/README.md#v2--peaufiner-avec-nos-images-de-la-voiture).

## Surveillance automatique : simuler l'oubli de bout en bout

Plus besoin de cliquer sur « Lancer l'analyse » : le banc joue la scène comme une vraie voiture.

1. Habitacle vide, choisir scénario / variante / vérité terrain dans le formulaire, puis **Armer** :
   la référence « habitacle vide » est capturée à cet instant.
2. Le conducteur monte (adulte vu ≥ 1,5 s → **Occupé**), installe la poupée ou pose ses affaires.
3. Il descend : plus aucun adulte vu → **Sortie**, compte à rebours de 8 s affiché en grand.
   Bouton **Verrouiller** : simule le verrouillage des portes, l'analyse part immédiatement.
4. **Analyse** complète (toutes caméras, référence, zoom, thermique), puis verdict.
5. **Alerte** : notification ntfy (urgente pour un enfant/animal), affichée avec la latence
   départ → verdict et l'objectif Euro NCAP (≤ 15 s). Sans retour du conducteur, l'alerte
   critique est **relancée à 90 s puis chaque minute** pendant 20 min. Le conducteur revient :
   l'alerte est levée (et une notification « Alerte levée » part). La notification critique et
   les rappels portent aussi un bouton **« Je m'en occupe »** qui lève l'alerte depuis le
   téléphone, sans ouvrir le dashboard, et un appui sur la notification elle-même ouvre la
   **page de suivi** `http://<IP-du-PC>:5000/suivi` : état en gros, compte à rebours, dernière
   alerte avec son image, acquittement et derniers événements. Renseigner `alertes.url_banc`
   (ex. `http://192.168.1.90:5000`) dans `config.local.json`, téléphone sur le même réseau
   que le PC.

Chaque cycle est journalisé comme un essai (`mode = auto`, colonnes `alerte` et
`latence_alerte_s`) si une vérité terrain a été choisie. Les événements sont aussi écrits, une
ligne JSON par transition, dans `data/essais/evenements.jsonl` (pour l'application de suivi).
Délais réglables dans `config.json` → `surveillance`. Détails : [`docs/surveillance.md`](docs/surveillance.md).

En démo, les boutons « Démo : le conducteur monte / descend » remplacent le vrai conducteur.

## Alertes téléphone

Notification push via [ntfy.sh](https://ntfy.sh) (gratuit, sans compte) avec l'image annotée :

1. Installer l'appli **ntfy** (Android / iOS) et s'abonner au topic des alertes.
   **Le topic fait office de mot de passe et le dépôt GitHub est public** : ne pas mettre le
   vrai topic dans `config.json`. Le définir hors dépôt, au choix :
   - variable d'environnement `CARE_NTFY_TOPIC` ;
   - fichier `config.local.json` (ignoré par git), fusionné par-dessus `config.json`, par ex.
     `{"alertes": {"topic": "care-g2-xxxxxxxx"}}`.
2. Tester sans caméra : `python test_alerte.py` — il lit le topic aux mêmes endroits et
   dans le même ordre que le dashboard. Tant que le topic de `config.json` n'est pas
   remplacé, **aucune notification ne part** et le message d'erreur le dit.

Règle (une seule, dans `care/decision.py`) :

| Niveau | Quand | Notification |
|---|---|---|
| **Critique** | enfant, bébé, chat, chien (RGB) ou source de chaleur (thermique) ; en surveillance, toute « présence humaine » après le départ du conducteur | priorité *urgent*, rappels |
| **Objet** | objet de `alertes.classes_surveillees` ou zone nouvelle non identifiée, sans adulte à bord | priorité *high*, cooldown 60 s par objet |

Les alertes critiques ne sont jamais filtrées par l'anti-spam. En essai manuel, un adulte
détecté à bord annule toute notification (l'opérateur est là). Pas de notification réelle en
`--demo` (sauf `"en_demo": true`). Le réglage `ratio_confirmation` de l'ancienne version des
alertes n'est plus utilisé : c'est `ratio_presence` (détection sur l'essai) qui joue ce rôle.

## Reconnaître les objets de valeur (téléphone, clés, portefeuille, carte, lunettes, sac…)

Le moteur par défaut (`"moteur": "care"`) travaille en trois temps :

1. **Localiser.** YOLOE (détecteur à vocabulaire ouvert) et notre modèle entraîné proposent des
   boîtes. Vus d'en haut dans l'habitacle, ils *trouvent* 93 % des objets, mais se trompent de
   *nom* trois fois sur quatre (téléphone posé de dos → « portefeuille », boucle de ceinture →
   « clés »). On garde donc leurs boîtes, et leur nom seulement comme indice.
2. **Nommer.** Chaque boîte est recadrée et classée par MobileCLIP parmi le catalogue
   (`care/detection/catalogue.py`) **et le décor** (siège, boucle, câble, console…) : le
   classifieur peut répondre « rien d'intéressant ».
3. **Trancher.** Un objet est retenu si le classifieur est sûr de lui (≥ 60 %), ou si deux
   modèles indépendants sont d'accord (classifieur ≥ 30 % + même nom proposé par un détecteur).
   Un être vivant n'est jamais annoncé par le classifieur seul.

Mesuré sur les 32 images des essais du 06/11 dans la voiture (56 objets annotés à la main,
9 images d'habitacle vide), sans référence :

| Moteur | Objets trouvés | Rappel | Précision | Fausses alertes (habitacle vide) |
|---|---|---|---|---|
| **care** (localiser + nommer) | 49 / 56 | **88 %** | **94 %** | 0 / 9 |
| hybride (avant) | 15 / 56 | 27 % | 44 % | 1 / 9 |
| yoloe seul | 3 / 56 | 5 % | 21 % | 0 / 9 |
| coco (YOLOv8) | 5 / 56 | 9 % | 56 % | 0 / 9 |

Pour refaire la mesure après un réglage ou un nouvel entraînement, sans retourner dans la voiture :

```
python outils/rejouer.py --moteurs care hybride --annoter rapports/rejeu
```

### La référence « habitacle vide »

1. Habitacle vide, portes fermées → bouton **Capturer la référence** (fait automatiquement à
   l'armement de la surveillance).
2. À chaque essai, seul **ce qui a changé** depuis la référence est examiné : une boucle de
   ceinture ou l'équipement de la console, déjà là, ne peuvent plus déclencher d'alerte — et
   l'essai est plus rapide.
3. Une zone qui a changé sans être reconnue remonte « objet non identifié » (orange), sauf si
   le classifieur y voit du décor (câble déplacé, ombre).

La comparaison résiste à l'auto-exposition de la caméra et à un léger déplacement. Si toute
l'image a changé (caméra bougée, nuit tombée), le résultat indique « lumière changée » : la
référence est à refaire.

### Régler et étendre

- Ajouter un objet : `detection.catalogue` dans `config.json`, sans toucher au code, par ex.
  `{"parapluie": {"mots": ["umbrella"], "descriptions": ["an umbrella"]}}`.
- Seuils : `detection.regles` (`seuil_objet`, `seuil_accord`, `candidats_max`…).
- Comparer avec les moteurs d'avant : `"moteur": "hybride"`, `"yoloe"` ou `"coco"`.
- Entraîner le modèle : [`entrainement/README.md`](entrainement/README.md). Évaluer sur un jeu
  annoté : `python outils/evaluer.py --donnees <data.yaml>`.

Architecture, mesures et limites : [`docs/detection.md`](docs/detection.md). Historique des
pistes testées : [`docs/recherche-detection-objets.md`](docs/recherche-detection-objets.md).

## Calibrer la thermique

La caméra thermique du banc s'annonce « UVC Camera » (USB 2BDF:0102, capteur 256×192 de la
famille InfiRay). Ce n'est pas une TC001 : son flux 256×392 contient des **comptes bruts du capteur**,
pas des températures. Le banc les lit en mode **relatif** : un pixel est chaud s'il dépasse le fond
de la scène de `thermique.seuil_comptes` (200 par défaut, à calibrer). Une vraie Topdon TC001
(flux 256×384, températures en °C) reste gérée : `thermique.resolution = [256, 384]`.

Sous Windows, le flux brut n'est lisible qu'avec Media Foundation (`thermique.backend = "msmf"`) :
DirectShow le convertit en couleur et les données sont perdues (le banc n'alerte alors plus, au lieu
d'alerter en permanence). Vérifier, dashboard arrêté : `python outils/diag_thermique.py`.
Dans le dashboard, le panneau doit afficher « relatif (comptes bruts) » ou « radiométrique (TC001) ».

**Calibrer `seuil_comptes`** : habitacle vide (hub USB et PC hors du champ), le nombre de pixels
chauds doit rester ~0 ; avec la poupée chauffée ou une main, il doit dépasser `pixels_chauds_min`.

Le panneau thermique affiche en direct le mode (radiométrique ou 8 bits), le nombre de pixels chauds et la T° max.

1. Faire un essai à vide, puis un essai avec la poupée chauffée.
2. Régler ensuite dans `config.json` le seuil (`seuil_celsius` en radiométrique, `seuil_8bit` sinon) et `pixels_chauds_min`.

## Données

- `data/essais/essais.csv` : un essai par ligne, s'ouvre directement dans Excel (bouton **Exporter CSV**).
- `data/essais/images/` : mosaïque RGB annotée et image thermique de chaque essai, à utiliser comme preuves pour le L3.
- `data/essais/reference/` : images de référence « habitacle vide » et détections fixes associées.
- `data/essais/brutes/` : images **sans annotation** de chaque caméra, à chaque essai — à verser
  dans Roboflow pour enrichir le jeu d'entraînement avec nos propres scènes.
- `data/essais/evenements.jsonl` : événements de la surveillance automatique.
- Les essais du mode démo sont rangés à part, dans `data/demo/`.

## Structure

```
app.py               serveur Flask + API
config.json          caméras, détection (moteur, règles, catalogue), référence, scénarios, variantes
config_5cameras.json copie de référence de la configuration 4 RGB + thermique
lister_cameras.py    assistant : quelle caméra filme quelle position → config.local.json
care/cameras.py      acquisition (1 thread par caméra) + sources démo
care/peripheriques.py caméra physique ↔ position (par nom, webcam du PC écartée)
care/collecte.py     rafales d'images brutes pour le dataset (doublons écartés)
care/detecteur.py    façade : chargement des modèles, essai complet, présence du conducteur
care/detection/      détection RGB : localiser → nommer → trancher
    catalogue.py       classes, mots du détecteur, descriptions du classifieur
    moteurs.py         moteur « care » + moteurs d'avant (hybride, yoloe, coco)
    classifieur.py     recadrage → probabilité par classe (MobileCLIP)
    clip_image.py      encodeur d'images MobileCLIP, reconstruit depuis mobileclip_blt.ts
    identification.py  règles pures : propositions + classifieur → détections
    changement.py      comparaison à la référence (éclairage, recalage, zones nouvelles)
    essai.py           analyse d'un essai multi-caméras
    rendu.py           images annotées, mosaïque
care/reference.py    référence habitacle vide : capture, persistance, « déjà là »
care/surveillance.py machine à états de la surveillance automatique + boucle de fond
care/decision.py     règle d'alerte unique (critique / objet / rien)
care/alertes.py      notifications ntfy (cooldown, rappels, levée d'alerte)
care/metriques_detection.py  précision / rappel boîte par boîte, tous moteurs
care/stockage.py     journal CSV + métriques (rappel, FN, faux positifs, précision)
entrainement/        entraînement du modèle (script + notebook Colab)
outils/rejouer.py    rejoue les images des essais et note la détection (avant / après)
outils/evaluer.py    comparaison des moteurs sur un jeu de test annoté
outils/preparer_lot.py lot Roboflow pré-annoté à partir des images collectées
tests/               tests automatiques (pytest)
templates/, static/  dashboard + page de suivi pour téléphone (/suivi)
```

## Tests

```
pip install pytest
python -m pytest
```

Les tests n'ont besoin ni de caméra ni de modèle : la machine à états tourne sur une horloge
simulée (délais Euro NCAP vérifiés en quelques millisecondes), l'envoi ntfy est simulé.
