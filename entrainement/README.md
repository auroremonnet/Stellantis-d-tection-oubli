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
