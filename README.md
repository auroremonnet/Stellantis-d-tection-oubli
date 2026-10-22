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

## Calibrer la thermique

Le panneau thermique affiche en direct le mode (radiométrique ou 8 bits), le nombre de pixels chauds et la T° max.

1. Faire un essai à vide, puis un essai avec la poupée chauffée.
2. Régler ensuite dans `config.json` le seuil (`seuil_celsius` en radiométrique, `seuil_8bit` sinon) et `pixels_chauds_min`.

## Données

- `data/essais/essais.csv` : un essai par ligne, s'ouvre directement dans Excel (bouton **Exporter CSV**).
- `data/essais/images/` : mosaïque RGB annotée et image thermique de chaque essai, à utiliser comme preuves pour le L3.
- `data/essais/reference/` : images de référence « habitacle vide » et détections fixes associées.
- Les essais du mode démo sont rangés à part, dans `data/demo/`.

## Structure

```
app.py               serveur Flask + API
config.json          caméras, détection (moteur, prompts, seuils), référence, scénarios, variantes
config_5cameras.json configuration complète 4 RGB + thermique (à recopier dans config.json le jour J)
lister_cameras.py    trouver les index des caméras
care/cameras.py      acquisition (1 thread par caméra) + sources démo
care/detecteur.py    YOLOE (prompts) ou YOLO COCO, zoom sur zones nouvelles, seuil thermique, fusion
care/reference.py    référence habitacle vide : détections fixes à ignorer, zones nouvelles
care/stockage.py     journal CSV + métriques (rappel, FN, faux positifs, précision)
templates/, static/  dashboard
```
