# Surveillance automatique — conception

*Groupe 2 · CARE · novembre 2026 · branche `detection-surveillance`*

## Pourquoi

L'essai manuel (« Lancer l'analyse » une fois sorti du véhicule) mesure le détecteur, pas le
**système**. Dans une vraie voiture, personne n'appuie sur un bouton : l'analyse doit partir
toute seule quand le conducteur s'en va, et l'alerte doit arriver vite. La surveillance
automatique joue donc la scène complète et mesure ce qui compte pour l'usager : **le temps entre
le départ du conducteur et l'alerte**.

## Référence réglementaire : Euro NCAP 2026, *Child Presence Detection*

| Exigence Euro NCAP | Réglage du banc (`config.json` → `surveillance`) |
|---|---|
| Premier avertissement < 15 s après verrouillage | `delai_sortie_s` = 8 s + analyse (≈ 1 à 4 s) → **9 à 12 s** mesurés |
| Escalade dans les 90 s si l'avertissement n'est pas traité | `delai_escalade_s` = 90 |
| Rappel chaque minute pendant au moins 20 minutes | `periode_rappel_s` = 60, `duree_rappels_s` = 1200 |
| Détection **directe** (mouvement, respiration, chaleur), pas une simple déduction d'ouverture de porte arrière | caméras RGB + thermique : détection directe |
| Toutes les places, plancher compris | 4 caméras RGB (avant / arrière, gauche / droite) |

Le banc ne pilote ni klaxon ni climatisation (phase « intervention » du protocole) : la
notification téléphone en tient lieu.

## Machine à états

```
             armer (référence capturée)
INACTIF ───────────────────────────────▶ VEILLE ◀──────────────── rien à signaler
                                           │ adulte vu ≥ 1,5 s
                                           ▼
                           ┌──────────▶ OCCUPÉ ◀───────────┐
                           │ adulte     │ plus d'adulte     │ conducteur revenu
                           │ revenu     ▼                   │ (alerte levée)
                           └─────────  SORTIE               │
                                        │ 8 s sans adulte   │
                                        │  ou verrouillage  │
                                        ▼                   │
                                     ANALYSE ──oubli──▶ ALERTE ── 90 s, puis chaque minute ─▶ rappel
```

Choix de conception, chacun motivé par un cas réel du banc :

- **Adulte = grande silhouette.** Seule une détection `person` dont la boîte couvre au moins
  35 % de la hauteur de l'image compte comme « adulte à bord » (`detection.hauteur_min_adulte`).
  Un enfant dans un siège auto ou un bébé ne doit **jamais** empêcher de constater le départ du
  conducteur — sinon l'enfant oublié bloquerait sa propre alerte.
- **Présence confirmée, absence immédiate.** Il faut 1,5 s de présence continue pour passer à
  « Occupé » (un reflet ou une veste prise pour une personne ne déclenche rien), mais la
  première image sans adulte lance le compte à rebours : un oubli de détection d'une image ne
  fait que retarder l'analyse, jamais l'empêcher.
- **Départ = dernier instant où l'adulte a été vu.** La latence affichée part de là, pas du
  premier échantillon « absent » : le chiffre ne flatte pas le système.
- **Habitacle censé vide ⇒ toute personne est critique.** Après le départ, une détection
  « personne » est le plus souvent un enfant que le modèle ne sait pas nommer « enfant ».
- **Un seul exécutant.** Le bouton « Verrouiller » ne lance pas l'analyse lui-même : il dépose
  la demande, que le thread de surveillance exécute. Jamais deux analyses en parallèle, et un
  désarmement pendant l'analyse n'envoie aucune notification.

## Architecture du code

```
care/surveillance.py
  MachineOubli   logique pure : observer(adulte_present) → actions ; horloge injectable
  Superviseur    thread : boucle d'observation (0,5 s), exécution des actions
  Branchements   fonctions fournies par app.py (présence, analyse, décision, notification…)
care/decision.py decider(résultat) → Alerte(critique | objet) | None
care/alertes.py  Alerteur.notifier(alerte, image, motif) → ntfy
```

La machine ne connaît ni caméra, ni modèle, ni réseau : elle est testée sur une horloge simulée
(`tests/test_surveillance.py`), ce qui vérifie par exemple les 19 rappels en 20 minutes
d'escalade en quelques millisecondes.

## Format des événements (`data/essais/evenements.jsonl`)

Une ligne JSON par transition, pour l'application de suivi :

```json
{"t": 1793533155.21, "heure": "11:39:15", "type": "alerte",
 "detail": "alerte critique : présence humaine, source de chaleur", "source": "surveillance"}
```

`type` ∈ `veille`, `occupe`, `sortie`, `analyse`, `alerte`, `rappel`, `inactif`.

## API

| Méthode | Route | Effet |
|---|---|---|
| GET | `/api/surveillance` | état courant, compte à rebours, dernier verdict, historique |
| POST | `/api/surveillance/armer` | capture la référence puis arme ; corps : `scenario`, `variante`, `verite`, `commentaire`, `capturer_reference` |
| POST | `/api/surveillance/verrouiller` | simule le verrouillage : analyse immédiate |
| POST | `/api/surveillance/desarmer` | arrête la surveillance |
| POST | `/api/surveillance/demo` | démo uniquement : `{"occupant": true/false}` |

## Protocole de mesure proposé

Pour chaque scénario S1 à S8, 10 cycles armés avec vérité terrain : le journal donne
directement le rappel, le taux de fausses alertes **et la latence départ → alerte** (moyenne
et pire cas, à comparer aux 15 s Euro NCAP). Variante utile : le conducteur « oublie » puis
revient au bout de 30 s → vérifier que l'alerte est levée et qu'aucun rappel ne part.

## Sources

- [Euro NCAP — CPD Test and Assessment Protocol](https://cdn.euroncap.com/media/83740/euro-ncap-cpd-test-and-assessment-protocol-v13.pdf)
- [Euro NCAP — Safe Driving, Occupant Monitoring protocol v1.1](https://www.euroncap.com/media/91703/euro-ncap-protocol-safe-driving-occupant-monitoring-v11.pdf)
- [Smart Eye — What Euro NCAP 2026 says about child presence detection](https://smarteye.se/blog/what-euro-ncap-2026-says-about-child-presence-detection/)
