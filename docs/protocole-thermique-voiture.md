# Thermique : mise en route et essais dans la voiture

La caméra imposée a une résolution de **256x192**. Le modèle reste à noter. Le banc lit la résolution
fournie par la caméra et les réglages de détection n'en dépendent pas : il n'y a aucune valeur de
résolution à saisir. Si le diagnostic affiche autre chose que 256x192, le signaler.

## Avant de partir

- Dépendances installées, `py -m pytest` au vert.
- Dépôt à jour, PC chargé, hub USB alimenté.
- De quoi tester : poupée chauffée ou bouillotte tiède, gourde très chaude, sac, couverture.

## 1. Identifier la caméra (5 min)

Noter la marque et la référence de la caméra, puis, habitacle portes ouvertes ou fermées :

```
py outils/diagnostic_thermique.py sonder --appliquer
```

La commande affiche la **résolution réelle** et le format, et écrit l'index et le mode de lecture
dans `config.local.json`. Trois résultats possibles :

| Résultat affiché | Conséquence |
|---|---|
| 16 bits, températures lisibles | Parfait, passer à l'étape 2 |
| 16 bits, échelle inconnue | Enregistrer quand même les images, chercher l'échelle dans la documentation du modèle |
| 8 bits gris, sans température | Seuil fixe uniquement, peu fiable. Chercher un mode radiométrique ou le logiciel du fabricant |

## 2. Vérifier les températures (2 min)

```
py outils/diagnostic_thermique.py direct
```

Viser sa main : le maximum affiché doit être autour de 30 à 35 °C, et la zone doit être entourée.
Si la valeur est absurde, l'échelle détectée est fausse : corriger `thermique.diviseur_kelvin`.

## 3. Fixer la caméra et définir les zones à ignorer (5 min)

Une fois la caméra **fixée à sa position définitive** :

```
py outils/diagnostic_thermique.py zones
```

Dessiner les vitres, le tableau de bord et ce qui chauffe au soleil. À refaire si la caméra bouge.

## 4. Enregistrer les scènes (20 min)

Dans `direct`, placer la scène puis appuyer sur **S**, ou lancer :

```
py outils/diagnostic_thermique.py enregistrer S7_vide
```

Nommer chaque scène et noter la température de l'habitacle. À enregistrer au minimum :

| Nom | Scène | Pourquoi |
|---|---|---|
| `S7_vide` | Habitacle vide | Faux positifs, et référence pour comparer les méthodes |
| `S1_poupee` | Poupée chauffée dans le siège | Cas principal |
| `S2_couverture` | La même sous une couverture | La couverture masque-t-elle la chaleur ? |
| `personne` | Une vraie personne sur la banquette | Vraie température de surface, à comparer aux hypothèses |
| `S8_gourde` | Gourde très chaude | Écartée au-dessus de 42 °C ? |
| `S8b_sac` | Sac resté au soleil | Fausse alerte attendue, à mesurer |
| `siege_0min`, `siege_1min`, `siege_3min` | Siège juste après s'être levé, puis 1 et 3 min après | **Vitesse de refroidissement**, pour distinguer un siège d'un corps |

## 5. Essais complets

```
py app.py
```

Le panneau thermique doit afficher la résolution et « radiométrique · contraste ». Faire ensuite les
essais S1 à S8. Chaque essai journalise la méthode et la résolution, et enregistre l'image thermique brute
dans `data/essais/brutes/`.

## 6. De retour, sans caméra

```
py outils/diagnostic_thermique.py rejouer --reference data/essais/brutes/thermique/<...>_S7_vide.npy
```

Repasse toutes les images dans le code actuel : on peut modifier `delta_c`, `part_min_image` ou
`temp_max_vivant_c` dans `config.json` et voir l'effet immédiatement. La simulation tourne déjà en 256x192 :

```
py outils/simuler_thermique.py
```

## Limites connues

- Quand l'habitacle approche la température du corps (simulation : dès 26 °C sous une couverture, 28 °C pour un animal, 32 à 40 °C pour un enfant), la thermique peut rater une
  présence : les caméras RGB restent indispensables.
- Un siège encore chaud ou un sac au soleil, sous 42 °C, déclenche une fausse alerte. Il faudra suivre
  l'évolution dans le temps : c'est le but des enregistrements `siege_*`.
- Si un corps occupe plus de la moitié de l'image, le fond est mal estimé : éviter de placer la caméra
  trop près.
- Tous les seuils viennent de la simulation et sont à recaler sur ces enregistrements.
