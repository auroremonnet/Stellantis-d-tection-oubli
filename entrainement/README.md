# Entraîner le modèle CARE

Objectif : un YOLO26 qui reconnaît ce que YOLOE rate dans l'habitacle — **bébé, clés,
portefeuille, carte bancaire** — utilisé par le moteur `hybride` du banc en complément de YOLOE.

## Le jeu de données (Roboflow, projet `care-oubli`)

Version **v1** (1er novembre 2026) : 2 584 images, 4 classes.

| Source (Roboflow Universe, CC BY 4.0) | Images | Classes retenues |
|---|---|---|
| item (lostitem) — objets perdus | 509 | wallet, credit_card → `wallet`, `card` |
| Keys Data | 600 | Keys → `keys` |
| Study desk items | 766 | Keys, Wallet, StudentID_card → `keys`, `wallet`, `card` |
| leftitem | 400 | carkeys, keys → `keys` |
| Baby / person / empty seat | 309 | baby |

Toutes les autres classes de ces jeux (stylos, calculatrices, écouteurs, téléphones…) ont été
**écartées sans supprimer les images** : ces objets restent visibles mais sans étiquette, et
servent d'exemples négatifs (« un étui à lunettes n'est pas un portefeuille »). Téléphones,
ordinateurs et sacs sont laissés à YOLOE, qui les reconnaît déjà.

Réglages de la version : redimensionnement « fit within 1024 » (proportions conservées : les
clés et les cartes ne sont pas déformées), **pas d'augmentation** dans Roboflow — Ultralytics
fait mosaïque, retournements et variations de couleur à chaque epoch, sans consommer de crédits.

**Point faible connu : `baby`** (309 images, prises sur banc avec poupons). La séance photo dans
la voiture avec un poupon dans un siège auto est indispensable avant la v2. Chaque essai du banc
sauvegarde désormais les images brutes dans `data/essais/brutes/` : les annoter dans Roboflow et
les ajouter au projet.

## v2 : peaufiner avec nos images de la voiture

La v1 est faite d'images de bureaux et de tables : le modèle n'a jamais vu **notre** habitacle
(angle plongeant, tissu des sièges, console, contre-jour). C'est l'écart principal à combler.

### 1. Collecter (dashboard → carte « Collecte dataset »)

Viser **~300 à 500 images gardées** sur une séance, réparties ainsi :

| Scène | Pourquoi | Part |
|---|---|---|
| Poupon dans le siège auto, avec / sans couverture, tête tournée | `baby` est la classe la plus faible (309 images de banc) | ~30 % |
| Clés, portefeuille, carte : console, banquette, sol, vide-poche, à moitié cachés | petits objets à plat, ce que YOLOE rate | ~35 % |
| **Habitacle vide** + objets anodins (gourde, vêtement, câble, papiers) | négatifs : apprend que la boucle de ceinture n'est pas une clé | ~25 % |
| Mêmes scènes de nuit / contre-jour | variantes du protocole d'essai | ~10 % |

Conseils : déplacer l'objet entre chaque prise (rafale de 15, une prise toutes les 2 s) ;
une rafale = une scène, avec une étiquette claire ; ne pas collecter avec une personne
reconnaissable dans le champ (dépôt et Roboflow publics).

### 2. Pré-annoter et importer

```
python outils/preparer_lot.py            # toutes les séances
python outils/preparer_lot.py --session 20261107
```

Le modèle actuel propose des boîtes (seuils × 0,8 : mieux vaut une boîte à supprimer qu'une à
dessiner). Roboflow → projet `care-oubli` → **Upload** → glisser le zip → *Save and continue*.
Dans l'éditeur d'annotation : corriger, compléter, supprimer les fausses boîtes ; **laisser
sans boîte** les images vides (ce sont des négatifs, il faut les garder).

### 3. Découper train / valid / test SANS fuite

Les 4 caméras filment la même scène au même instant : si une image va en train et sa voisine
en test, le score de test est artificiellement bon. Règle : **une séance entière dans le même
split**. Le plus simple : la séance du jour 1 en train/valid, une séance d'un autre jour (ou
d'une autre voiture / lumière) entièrement en test. Dans Roboflow, choisir le split au moment
de l'upload (*Add images to: Test*).

### 4. Générer la v2, réentraîner, comparer

Générer la version 2 avec les mêmes réglages que la v1 (fit within 1024, pas d'augmentation), puis :

```
python entrainement/entrainer.py --version 2 --imgsz 1280 --batch 8 --nom care-v2
python outils/evaluer.py --donnees datasets/care-oubli-v2/data.yaml --moteurs yoloe custom hybride
```

`--imgsz 1280` (batch réduit pour tenir sur le GPU T4 de Colab) aide sur les clés et les cartes vues de loin par les caméras du plafonnier.
Comparer v1 et v2 **sur le même test (images de la voiture)** : c'est ce chiffre qui va dans
le livrable, pas le mAP sur les images de bureau. Si la v2 est meilleure : `detection.modele_custom`
→ `modeles/care-v2.pt` dans `config.json`.

## Lancer l'entraînement

### Sur Google Colab (recommandé, GPU gratuit)

Ouvrir [`CARE_entrainement_colab.ipynb`](CARE_entrainement_colab.ipynb) dans Colab
(*Fichier → Importer → GitHub*), choisir un GPU T4, exécuter les cellules. La clé API Roboflow
est demandée au clavier, jamais écrite dans le code.

### En local (GPU conseillé)

```
pip install -r requirements.txt roboflow
set ROBOFLOW_API_KEY=xxxxxxxx              (Windows)
python entrainement/entrainer.py --version 1
```

Le modèle arrive dans `modeles/care-v1.pt`, avec sa fiche `modeles/care-v1.json` (jeu de
données, réglages, métriques **sur le split test**, jamais vu pendant l'entraînement).

## Réglages et pourquoi

Tirés du [guide de fine-tuning Ultralytics](https://docs.ultralytics.com/guides/finetuning-guide) :

| Réglage | Valeur | Raison |
|---|---|---|
| Modèle de départ | `yolo26s.pt` | YOLO26 : génération actuelle recommandée ; « s » : bon compromis vitesse/précision sur le PC du banc |
| `freeze` | 10 | petit jeu proche de COCO : on garde le squelette appris, on adapte le reste |
| Optimiseur | AdamW, lr0 = 0,001 | stable pour quelques milliers d'images |
| `patience` | 20 | arrêt précoce : évite le sur-apprentissage |
| `imgsz` | 640 | à comparer avec 1280 pour les petits objets (clés, carte) |

Pistes d'amélioration à mesurer (une à la fois, avec `outils/evaluer.py`) : `--imgsz 1280`,
`--freeze 0`, `--modele yolo26m.pt`, ajout de nos propres images.
