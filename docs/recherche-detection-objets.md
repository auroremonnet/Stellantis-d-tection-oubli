# Reconnaître les objets de valeur dans l'habitacle — état des lieux et choix

*Groupe 2 · CARE · 21 octobre 2026 · à partir des 8 essais réels du matin (Stellantis, 2 caméras RGB)*

## 1. Le problème constaté

Avec YOLOv8 (`yolov8n` puis `yolov8m`, 80 classes COCO), le banc détecte bien les
**personnes** et les **ordinateurs portables**, mais **aucun des 8 essais avec téléphone**
n'a déclenché d'alerte. Trois causes, mesurées sur nos propres images :

| Cause | Mesure |
|---|---|
| Le modèle n'a pas les classes qu'il nous faut | COCO n'a **ni clé, ni portefeuille, ni carte**. Seulement `cell phone`, `handbag`, `backpack`, `suitcase`, `laptop`. |
| Un téléphone posé à plat, vu d'en haut, ne ressemble pas aux photos d'entraînement (téléphone tenu en main, de face) | Score « téléphone » de `yolov8n` sur le téléphone bleu du siège avant : **0,06** (seuil : 0,40). `yolov8m` : 0,74 sur un essai, **0** sur les suivants. Téléphone sur la banquette arrière : **0 avec tous les modèles** (n, m, l, YOLO11). |
| Le grand sac de courses n'est pas reconnu non plus | Meilleur score « handbag » : 0,44 (`yolov8l` à 1280 px). |

Grossir le modèle ne règle rien : `yolov8l` est instable (0,94 puis 0 sur le même téléphone),
et la résolution 1280 n'aide pas.

## 2. Pistes étudiées

### A. Détecteur à vocabulaire ouvert (retenu)

Modèles entraînés à relier une image à du **texte** : on leur donne des mots, ils les cherchent.
Pas d'annotation, pas d'entraînement, changement de liste en 10 secondes.

| Modèle | Intégration | Vitesse CPU (nos images 1280×720) | Remarques |
|---|---|---|---|
| **YOLOE** (`yoloe-11s/m/l-seg.pt`) | `ultralytics`, même API que nos scripts (`set_classes`) | **0,3 s/image** (11s), 0,9 s (11l) | Encodeur texte MobileCLIP téléchargé depuis GitHub. **Retenu.** |
| YOLO-World (`yolov8s/m/l/x-world.pt`) | `ultralytics` | similaire | Ancêtre de YOLOE. A besoin du paquet CLIP d'OpenAI (téléchargement Azure, bloqué sur certains réseaux). |
| Grounding DINO / OWLv2 | `transformers` | plusieurs secondes/image | Meilleure précision zero-shot, mais trop lent sur le PC du banc. Utilisable hors ligne pour annoter un jeu de données. |
| `yolov8x-oiv7` (Open Images, 600 classes) | `ultralytics` | 0,9 s/image | A `Mobile phone`, `Handbag`, `Watch`, `Glasses`, mais **pas `Wallet` ni `Key`**. |

Résultats de **YOLOE-11s** sur nos images, prompts `cell phone, car key, keys, wallet, credit
card, handbag, backpack, bag, laptop, …`, seuil 0,05 :

- téléphone bleu sur le siège avant : **0,33** (bien localisé) ;
- téléphone sur la banquette arrière : **0,24 à 0,62** selon l'essai ;
- sac de courses : **0,55 à 0,88** (YOLOE-11m) ;
- ordinateur : 0,97.

Mais aussi des **faux positifs fixes** : la boucle de ceinture arrière vue comme un
téléphone à **0,62**, la clé/console avant comme un téléphone à 0,32, la veste comme une
personne à 0,4. Un détecteur seul ne suffit donc pas dans un habitacle : il faut lui dire ce
qui fait partie de la voiture.

### B. Référence « habitacle vide » + détection de changement (retenu, combiné avec A)

L'oubli est par définition **ce qui est apparu** dans l'habitacle. On photographie l'habitacle
vide une fois (par caméra), puis à chaque essai :

1. **Filtrage des faux positifs fixes** : une détection de même classe au même endroit sur la
   référence est ignorée (boucle, console, appuie-tête…). Mesuré au capture sur 5 images avec
   un seuil abaissé pour ne rien rater.
2. **Zones nouvelles** : différence d'image (niveaux de gris, flou, compensation d'exposition,
   morphologie), moyennée sur les 10 images de l'essai. Chaque zone est **zoomée** et
   re-soumise à YOLOE — ce qui aide précisément pour les petits objets (clés, carte).
3. Zone nouvelle non reconnue → **« objet non identifié » → ALERTE** quand même. On ne
   dépend plus du nom de l'objet pour signaler l'oubli.

Limites connues, à mesurer sur le banc : changement de lumière (le résultat le signale et
ignore alors les zones), caméra qui bouge (refaire la référence), objet « anodin » (scénario
S6) qui déclenchera aussi une zone nouvelle — c'est voulu, et c'est justement ce que le banc
doit quantifier (taux de fausses alertes de S6/S8 vs rappel de S5).

### C. Ré-entraînement sur nos propres images (à faire pour le L3 si le temps le permet)

Aucun jeu de données public ne couvre « objets de valeur oubliés dans un habitacle vu de
dessus ». Ce que l'on a trouvé :

| Jeu de données | Contenu | Utile ? |
|---|---|---|
| [leftitem (Roboflow Universe)](https://universe.roboflow.com/taekyu-ryu/leftitem) | 402 images, classes `cell phone`, `carkeys`, `keys`, licence CC BY 4.0 | Oui, pour les clés — à mélanger à nos images. |
| [Top Wallet datasets (Roboflow)](https://universe.roboflow.com/search?q=class:wallet) | plusieurs petits jeux « wallet » | Oui, en complément. |
| [SVIRO](https://arxiv.org/abs/2001.03483) (DFKI) | 25 000 images **synthétiques** de banquettes arrière : personnes, sièges enfant, objets | Occupation de siège, pas objets de valeur. Utile pour les scénarios « vivant ». |
| [TICaM](https://ar5iv.labs.arxiv.org/html/2103.11719) (DFKI) | habitacle en time-of-flight + RGB, personnes et objets | Idem, orienté occupants. |
| [ODAL (BMW, 2025)](https://arxiv.org/html/2508.19651v3) | 223 images d'un habitacle, 13 catégories dont sacs, portefeuilles, ordinateurs | **Non public**, mais confirme l'approche : les auteurs ont dû créer leur propre jeu, et un petit modèle vision-langage ajusté sur ces images bat GPT-4o. |

Conclusion : le meilleur jeu de données est **celui que le banc produit**. Chaque essai
enregistre déjà une mosaïque annotée dans `data/essais/images/`. Marche à suivre quand on
aura ~150 à 200 images (toutes variantes de lumière) :

1. Exporter les images brutes (sans annotation) vers Roboflow, annoter en partant des boîtes
   YOLOE (pré-annotation automatique), corriger à la main.
2. Ajouter `leftitem` pour les clés.
3. Fine-tuner `yoloe-11s` ou `yolo11s` (`model.train(data=..., epochs=50)`), ~1 h sur GPU Colab.
4. Comparer sur le banc : A1 COCO vs A1 YOLOE vs A1 fine-tuné, même scènes.

## 3. Ce qui est implémenté sur la branche `detection-objets`

- `config.json` → bloc `detection` : moteur `yoloe`, prompts vivant / valeur, seuils, zoom ;
  bloc `reference` : seuils de la détection de changement.
- `care/detecteur.py` : moteur YOLOE ou COCO, filtrage par référence, zones nouvelles zoomées.
- `care/reference.py` : capture, persistance (`data/essais/reference/`), masque de changement.
- `app.py` : `POST/DELETE /api/reference`, état dans `/api/etat`, colonnes CSV
  `moteur`, `zones_nouvelles`, `reference_utilisee`, `lumiere_changee` (ancien CSV migré).
- Dashboard : carte « Référence habitacle vide », colonne « Zones », résultat détaillé.

## 4. Protocole de test proposé pour valider (prochaine séance voiture)

1. Capturer la référence par caméra, habitacle vide.
2. S7 (vide) × 5 → doit donner RAS, 0 zone (sinon : baisser `seuil_changement` trop sensible → le remonter).
3. S5 avec téléphone **seul**, puis clés **seules**, puis carte bancaire **seule**, puis sac × 5 chacun, en notant dans le commentaire ce qui était posé.
4. S6 (vêtement) × 5 → mesure du taux de fausses alertes induit par les zones nouvelles.
5. Refaire 2 à 4 en variante « Contre-jour ».

Le CSV exporté donne directement rappel objets (S5) et taux de fausses alertes (S6/S7).

## Sources

- [YOLO-World — documentation Ultralytics](https://docs.ultralytics.com/models/yolo-world/) (API `set_classes`, pointeur vers YOLOE)
- [Open Images V7 — poids `yolov8*-oiv7` et classes](https://docs.ultralytics.com/datasets/detect/open-images-v7/)
- [Scalable Object Detection in the Car Interior With Vision Foundation Models (ODAL)](https://arxiv.org/html/2508.19651v3)
- [leftitem — Roboflow Universe](https://universe.roboflow.com/taekyu-ryu/leftitem)
- [SVIRO: Synthetic Vehicle Interior Rear Seat Occupancy Dataset](https://arxiv.org/abs/2001.03483)
- [TICaM: A Time-of-flight In-car Cabin Monitoring Dataset](https://ar5iv.labs.arxiv.org/html/2103.11719)
- [YOLO-World: Real-Time Open-Vocabulary Object Detection (CVPR 2024)](https://openaccess.thecvf.com/content/CVPR2024/papers/Cheng_YOLO-World_Real-Time_Open-Vocabulary_Object_Detection_CVPR_2024_paper.pdf)
- [Grounding DINO vs YOLO-World — comparatif Roboflow](https://playground.roboflow.com/models/compare/grounding-dino-vs-yolo-world)
