# CARE · Groupe 2 · Détection d'oubli dans l'habitacle

Banc de test et dashboard pour comparer **A1 (RGB seul)** et **A2 (RGB + thermique)**.

## Démarrer

**Sous Windows :** double-clic sur `lancer.bat`. Au premier lancement, l'environnement Python s'installe (quelques minutes), puis le dashboard s'ouvre sur http://localhost:5000.

- `lancer_demo.bat` : **mode démo**, sans matériel (flux et détections simulés). Utile pour prendre l'outil en main ou le montrer.
- En ligne de commande : `python app.py` ou `python app.py --demo`.

## Brancher le matériel

1. Brancher les 4 caméras RGB et la thermique sur le hub USB actif.
2. Lancer `python lister_cameras.py` : une fenêtre par caméra s'ouvre et affiche son index.
3. Reporter ces index dans `config.json` (`cameras_rgb`, `camera_thermique`).
4. Si une caméra ne s'affiche pas, passer `resolution` à `[640, 360]` : le hub sature avec 4 flux 720p.

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
   l'alerte est levée (et une notification « Alerte levée » part).

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
config_5cameras.json configuration complète 4 RGB + thermique (à recopier dans config.json le jour J)
lister_cameras.py    trouver les index des caméras
care/cameras.py      acquisition (1 thread par caméra) + sources démo
care/detecteur.py    YOLOE / COCO / hybride, zoom sur zones nouvelles, seuil thermique, fusion
care/reference.py    référence habitacle vide : détections fixes à ignorer, zones nouvelles
care/surveillance.py machine à états de la surveillance automatique + boucle de fond
care/decision.py     règle d'alerte unique (critique / objet / rien)
care/alertes.py      notifications ntfy (cooldown, rappels, levée d'alerte)
care/metriques_detection.py  précision / rappel boîte par boîte, tous moteurs
care/stockage.py     journal CSV + métriques (rappel, FN, faux positifs, précision)
entrainement/        entraînement du modèle (script + notebook Colab)
outils/evaluer.py    comparaison des moteurs sur un jeu de test annoté
tests/               tests automatiques (pytest)
templates/, static/  dashboard
```

## Tests

```
pip install pytest
python -m pytest
```

Les tests n'ont besoin ni de caméra ni de modèle : la machine à états tourne sur une horloge
simulée (délais Euro NCAP vérifiés en quelques millisecondes), l'envoi ntfy est simulé.
