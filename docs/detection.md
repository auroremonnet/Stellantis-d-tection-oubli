# Détection RGB : localiser → nommer → trancher

*Refonte du 12/11/2026. Remplace le moteur « hybride », gardé pour comparaison.*

## Le problème mesuré

Sur les images des essais du 06/11 dans la voiture (4 caméras, 8 essais, 56 objets annotés à
la main), le moteur hybride ne retrouvait que **27 %** des objets, avec une précision de 44 % :

- téléphone : 1 sur 20 (les téléphones posés de dos sortaient en « portefeuille ») ;
- lunettes : 0 sur 4 ; clés : 4 sur 15 ; portefeuille : 2 sur 9 (un portefeuille ouvert sortait
  en « ordinateur ») ;
- les boucles de ceinture sortaient en « clés » ou « sac à main » ;
- avec la référence, jusqu'à 14 « objets non identifiés » sur un habitacle presque vide ;
- 36 à 160 s par essai.

Deux constats ont guidé la refonte :

1. **Les détecteurs savent où, pas quoi.** En abaissant son seuil à 0,03 et en ignorant ses
   noms, YOLOE (le petit modèle déjà installé) couvre 52 des 56 objets (93 %). Aucun modèle à
   vocabulaire ouvert plus gros ne nomme mieux sur ces vues plongeantes : YOLOE 11-L, v8-L,
   26-M, 26-L, 26-X plafonnent tous à F1 ≈ 0,30.
2. **Un classifieur image ↔ texte nomme très bien un recadrage.** MobileCLIP-B reconnaît
   49 recadrages sur 56 quand on lui montre l'objet seul. Et ses poids sont déjà sur le banc :
   `mobileclip_blt.ts`, téléchargé par YOLOE, contient l'encodeur d'images en plus de
   l'encodeur de texte (seul son code manquait : voir `care/detection/clip_image.py`).

## La chaîne

```
images des caméras
   │  observer()   YOLOE (seuil 0,03, tous mots du catalogue + décor) + modèle entraîné
   ▼
propositions ── suivi sur l'essai (présentes sur ≥ 50 % des images) ── doublons fusionnés
   │              + zones qui ont changé depuis la référence, s'il y en a une
   ▼
recadrages ── MobileCLIP ──► probabilité par classe du catalogue + « décor »
   ▼
trancher()   sûr (≥ 0,60)  ou  accord de deux modèles (≥ 0,30 + même nom du détecteur)
   ▼
détections ── écart de ce qui était déjà là (référence) ──► résultat de l'essai
```

Les êtres vivants gardent la règle d'avant (détecteur confiant, vote sur les images de
l'essai), à laquelle s'ajoute l'accord détecteur + classifieur. Le classifieur seul n'annonce
jamais un être vivant, et la référence ne peut pas écarter un être vivant sur la seule foi
des pixels.

## Résultats

Sans référence, image par image (`python outils/rejouer.py --moteurs care hybride yoloe coco`) :

| Classe | care | hybride (avant) |
|---|---|---|
| téléphone | 18 / 20 | 1 / 20 |
| clés | 12 / 15 | 4 / 15 |
| portefeuille | 9 / 9 | 2 / 9 |
| carte bancaire | 8 / 8 | 8 / 8 (+5 fausses) |
| lunettes | 2 / 4 | 0 / 4 |
| **Total** | **49 / 56 · rappel 88 % · précision 94 %** | 15 / 56 · 27 % · 44 % |
| Fausses alertes, habitacle vide | 0 / 9 | 1 / 9 |

Les 3 « clés en trop » sont des morceaux d'un vrai trousseau (porte-clés, étiquette) comptés
à part ; aucune fausse alerte sur une scène vide.

Essais complets rejoués (4 caméras, 3 images par caméra, référence du 06/11 à 16 h 11) :

| Essai | Avant | Maintenant |
|---|---|---|
| 16 h 15, 2 téléphones + clés | « objet non identifié », 14 zones, 162 s | clés, téléphone · 12 s |
| 16 h 11, habitacle vide | clés, sac à main, téléphone, objet non identifié · 136 s | rien à signaler · 7 s |
| 16 h 08, habitacle vide | clés, sac à main · 86 s | rien à signaler · 8 s |

Durées mesurées sur une machine à 2 cœurs, sans carte graphique.

## Limites connues

- **Peu de données.** 32 images, une seule voiture, de jour. Les réglages n'ont pas été
  ajustés image par image (mêmes résultats sur deux moitiés du jeu : F1 0,91 et 0,91), mais
  il faut rejouer la mesure sur de nouvelles prises : nuit, contre-jour, objets au sol.
- **Non mesuré : montre, ordinateur, tablette, sacs, valise, casque** (absents des essais du
  06/11) et **tous les êtres vivants** (pas de poupon ni d'animal sur ces images).
- **Lunettes** : 2 sur 4. Fines et transparentes, elles sont parfois mal localisées.
- **Objet clair sur siège clair** : la comparaison à la référence peut ne pas le voir ; ce
  sont alors les détecteurs qui le proposent.
- **Durée** : le classifieur coûte environ 0,15 s par recadrage sur processeur. Leviers :
  `detection.regles.candidats_max` (14), `images_par_essai` (3), `detection.taille_recadrage`
  (224 ; à 160 l'essai est 40 % plus rapide mais le rappel tombe à 79 %).

## Aller plus loin

1. **Entraîner le modèle sur nos vues** (dataset v2) : il devient un meilleur localisateur et
   son accord avec le classifieur valide les cas difficiles. `outils/preparer_lot.py`
   pré-annote maintenant avec le moteur care (classes `phone` et `glasses` ajoutées).
2. **LeftInCAR** (Université du Minho, CC BY 4.0, doi:10.17632/dd4hw3r6dh.1) : 971 images
   d'objets oubliés en voiture, annotées au format YOLO en 10 classes (smartphone, ordinateur,
   carte, valise, portefeuille, sac à dos, vêtement, clés, lunettes, sac à main). Deux usages :
   - *test indépendant* : télécharger `leftincar-data.zip` depuis
     https://data.mendeley.com/datasets/dd4hw3r6dh/1, le décompresser dans
     `datasets/leftincar/`, lancer le `yolo_dataset_splitter.py` fourni, puis
     `python outils/evaluer.py --donnees datasets/leftincar/data.yaml --classes leftincar` ;
   - *entraînement* : l'ajouter à nos photos pour la v2 (citer les auteurs dans le livrable).
3. **Vérité terrain** : annoter chaque nouvelle série d'essais (un point par objet, format de
   `tests/donnees/verite_voiture_20261106.json`) pour suivre le score dans le temps.
