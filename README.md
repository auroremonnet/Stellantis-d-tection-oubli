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

## Reconnaître les objets de valeur (téléphone, clés, portefeuille, carte, sac…)

Le détecteur est **YOLOE**, un modèle à vocabulaire ouvert : on lui donne une liste de mots
(`detection.prompts_valeur` dans `config.json`) et il les cherche, sans entraînement. YOLO
classique (80 classes COCO) ne connaît ni les clés, ni les portefeuilles, ni les cartes.

Mais dans un habitacle, un détecteur seul se trompe : la boucle de ceinture ressemble à un
téléphone, la console à un sac. D'où la **référence « habitacle vide »** :

1. Habitacle vide, portes fermées → bouton **Capturer la référence** dans le dashboard.
2. À chaque essai, les détections déjà présentes au même endroit sur la référence sont
   ignorées (affichées en gris sur l'image annotée).
3. Tout ce qui a changé par rapport à la référence est une **zone nouvelle** (orange) :
   elle est zoomée et re-soumise au détecteur. Si rien n'est reconnu, l'essai remonte quand
   même « objet non identifié » → décision ALERTE. Un objet oublié n'a pas besoin d'être nommé
   pour être signalé.

À refaire si la caméra bouge ou si la lumière change beaucoup (le résultat indique alors
« lumière changée, zones ignorées »). Pour revenir à YOLO classique et comparer :
`"moteur": "coco"` et `"modele": "yolov8m.pt"` dans `detection`.

Détails, pistes testées et jeux de données : [`docs/recherche-detection-objets.md`](docs/recherche-detection-objets.md).

### Moteur hybride : YOLOE + notre modèle entraîné

YOLOE rate encore les petits objets posés à plat (clés dans la console, téléphone sur la
banquette). Le moteur par défaut est donc `"hybride"` : YOLOE **et** un YOLO26 entraîné sur nos
classes (`baby`, `keys`, `wallet`, `card`) tournent sur chaque image ; les doublons entre les
deux sont fusionnés, le modèle entraîné étant prioritaire sur ses propres classes.

Tant que `modeles/care-v1.pt` n'existe pas, le banc tourne en YOLOE seul (pastille orange dans le
dashboard). Pour le produire : [`entrainement/README.md`](entrainement/README.md) (Colab, ~30 min).
Pour mesurer l'apport réel sur un jeu de test annoté :

```
python outils/evaluer.py --donnees datasets/care-oubli-v1/data.yaml --moteurs yoloe custom hybride
```

→ tableau précision / rappel par classe et par moteur dans `rapports/`, prêt pour le livrable.

## Calibrer la thermique

La caméra thermique est une **Topdon TC001** (256×192, radiométrique) : le banc lit ses
températures brutes (`thermique.modele = "tc001"`). Vérifier qu'elles sont bien lues,
dashboard arrêté : `python outils/diag_thermique.py` (main devant la caméra : la max doit
monter vers 30-35 °C). Il indique l'index et le `backend` à reporter dans `config.local.json`.
Dans le dashboard, le panneau doit afficher le mode « radiométrique (TC001) » : « 8 bits »
veut dire que les températures ne sont pas lues et le seuil ne veut rien dire.

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
config.json          caméras, détection (moteur, prompts, seuils), référence, scénarios, variantes
config_5cameras.json copie de référence de la configuration 4 RGB + thermique
lister_cameras.py    assistant : quelle caméra filme quelle position → config.local.json
care/cameras.py      acquisition (1 thread par caméra) + sources démo
care/peripheriques.py caméra physique ↔ position (par nom, webcam du PC écartée)
care/collecte.py     rafales d'images brutes pour le dataset (doublons écartés)
care/detecteur.py    YOLOE / COCO / hybride, zoom sur zones nouvelles, seuil thermique, fusion
care/reference.py    référence habitacle vide : détections fixes à ignorer, zones nouvelles
care/surveillance.py machine à états de la surveillance automatique + boucle de fond
care/decision.py     règle d'alerte unique (critique / objet / rien)
care/alertes.py      notifications ntfy (cooldown, rappels, levée d'alerte)
care/metriques_detection.py  précision / rappel boîte par boîte, tous moteurs
care/stockage.py     journal CSV + métriques (rappel, FN, faux positifs, précision)
entrainement/        entraînement du modèle (script + notebook Colab)
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
