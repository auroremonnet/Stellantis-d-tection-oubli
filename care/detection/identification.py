"""Règles d'identification : des boîtes proposées + l'avis du classifieur → les détections.

Tout ici est en fonctions pures (pas de modèle, pas de caméra) : c'est le cœur de la
logique, et c'est ce que couvrent les tests.

    LOCALISER   YOLOE et le modèle entraîné proposent des boîtes. Sur nos vues plongeantes,
                ils trouvent 93 % des objets mais se trompent de nom trois fois sur quatre :
                on garde leurs boîtes, et leur nom seulement comme indice.
    NOMMER      MobileCLIP classe chaque recadrage parmi le catalogue + le fond.
    TRANCHER    une détection est retenue si le classifieur est sûr de lui, ou si deux
                modèles indépendants sont d'accord (classifieur + indice du détecteur).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .catalogue import FOND, VALEUR, VIVANT, Catalogue
from .geometrie import aire, contenue, entiers, iou, nms, recouvrement

ZONE, YOLOE, ENTRAINE = "zone", "yoloe", "entraîné"
_PRIORITE = {ENTRAINE: 2, YOLOE: 1, ZONE: 0}


@dataclass(frozen=True)
class Regles:
    seuil_objet: float = 0.6            # probabilité du classifieur pour nommer seul un objet
    seuil_accord: float = 0.3           # … abaissée quand le détecteur propose le même nom
    conf_accord: float = 0.15           # confiance minimale de YOLOE pour compter comme indice
    seuil_fond: float = 0.5             # zone nouvelle : au-delà, c'est du décor (câble, ombre…)
    conf_proposition: float = 0.03      # YOLOE : seuil très bas, on ne veut que ses boîtes
    conf_entraine: float = 0.10
    iou_doublon: float = 0.7
    aire_max: float = 0.5               # boîte / image : au-delà, ce n'est pas un objet posé
    aire_max_faible: float = 0.15       # idem pour une proposition peu confiante
    cote_min: int = 8
    candidats_max: int = 14             # par caméra (le classifieur coûte ~0,15 s par recadrage)
    part_deja_la: float = 0.15          # référence : boîte dont moins de 15 % a changé = déjà là

    @classmethod
    def depuis_config(cls, d: dict | None) -> Regles:
        d = d or {}
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


@dataclass
class Candidat:
    """Une boîte à nommer. `cle` est l'indice du détecteur (None pour le décor ou une zone)."""
    boite: list
    source: str
    conf: float = 0.0
    cle: str | None = None
    vues: int = 1                       # nombre d'images de l'essai où la boîte est proposée


@dataclass
class Detection:
    cle: str
    categorie: str
    conf: float
    boite: list
    sources: tuple = ()
    accord: bool = False                # retenue grâce à l'accord de deux modèles
    extra: dict = field(default_factory=dict)

    def en_dict(self) -> dict:
        return {"libelle": self.cle, "categorie": self.categorie, "confiance": round(float(self.conf), 2),
                "boite": entiers(self.boite), "sources": list(self.sources), **self.extra}


# ---- 1. LOCALISER : nettoyer les propositions ------------------------------
def preparer_candidats(candidats: list[Candidat], forme, regles: Regles) -> list[Candidat]:
    """Écarte les boîtes absurdes, fusionne les doublons (toutes classes confondues : une
    boîte = un objet) et plafonne le nombre de recadrages à classer."""
    h, w = forme[:2]
    ok = []
    for c in candidats:
        b = c.boite
        part = aire(b) / float(w * h)
        if min(b[2] - b[0], b[3] - b[1]) < regles.cote_min or part > regles.aire_max:
            continue
        if part > regles.aire_max_faible and c.source == YOLOE and c.conf < regles.conf_accord:
            continue
        ok.append(c)
    cle_tri = lambda c: (_PRIORITE[c.source], c.conf)  # noqa: E731
    gardes = nms(ok, boite=lambda c: c.boite, score=cle_tri, seuil_iou=regles.iou_doublon)
    return gardes[: regles.candidats_max]


def suivre(par_image: list[list[Candidat]], ratio: float, iou_min: float = 0.5) -> list[Candidat]:
    """Propositions stables sur l'essai : celles de la dernière image qu'on retrouve au même
    endroit dans au moins `ratio` des images (un reflet ou une main qui passe n'y sont pas)."""
    if not par_image:
        return []
    stables = []
    for c in par_image[-1]:
        c.vues = sum(any(iou(c.boite, o.boite) >= iou_min for o in autres) for autres in par_image)
        if c.vues / len(par_image) >= ratio:
            stables.append(c)
    return stables


def voter(par_image: list[list[Candidat]], ratio: float) -> list[Candidat]:
    """Êtres vivants : vote par classe (un enfant bouge, sa boîte aussi). Une classe est
    retenue si elle est vue sur au moins `ratio` des images ; on rend ses boîtes les plus récentes."""
    if not par_image:
        return []
    retenus = []
    for cle in {c.cle for obs in par_image for c in obs}:
        vues = sum(any(c.cle == cle for c in obs) for obs in par_image)
        if vues / len(par_image) >= ratio:
            derniere = next(obs for obs in reversed(par_image) if any(c.cle == cle for c in obs))
            retenus += [c for c in derniere if c.cle == cle]
    return retenus


# ---- 2 et 3. NOMMER puis TRANCHER --------------------------------------------
def trancher(candidats: list[Candidat], probas: list[dict], catalogue: Catalogue,
             regles: Regles) -> tuple[list[Detection], list[list]]:
    """Renvoie (détections, zones nouvelles non identifiées)."""
    detections, inconnues = [], []
    valeurs, vivants = catalogue.cles(VALEUR), catalogue.cles(VIVANT)
    for c, p in zip(candidats, probas):
        premier = max(p, key=p.get)
        objet = max(valeurs, key=lambda k: p.get(k, 0.0)) if valeurs else None
        d = None
        if objet and premier == objet and p[objet] >= regles.seuil_objet:
            d = Detection(objet, VALEUR, p[objet], c.boite, (c.source, "clip"))
        elif objet and c.cle == objet and p.get(objet, 0.0) >= regles.seuil_accord \
                and (c.source == ENTRAINE or c.conf >= regles.conf_accord):
            d = Detection(objet, VALEUR, p[objet], c.boite, (c.source, "clip"), accord=True)
        elif premier in vivants and catalogue.categorie(c.cle) == VIVANT and p[premier] >= regles.seuil_objet:
            # un être vivant n'est jamais annoncé par le classifieur seul : il faut que le
            # détecteur ait lui aussi vu un être vivant à cet endroit
            d = Detection(premier, VIVANT, p[premier], c.boite, (c.source, "clip"), accord=True)
        if d is not None:
            detections.append(d)
        elif c.source == ZONE and p.get(FOND, 0.0) < regles.seuil_fond:
            inconnues.append(c.boite)
    detections = dedoublonner(detections)
    inconnues = [z for z in inconnues if all(recouvrement(z, d.boite) < 0.3 for d in detections)]
    return detections, inconnues


def dedoublonner(detections: list[Detection]) -> list[Detection]:
    """Un objet = une détection. Deux boîtes de même classe qui se recouvrent sont le même
    objet ; une petite boîte dans un objet plus grand en est un morceau (les objectifs d'un
    téléphone ne sont pas un « casque audio »)."""
    gardees: list[Detection] = []
    for d in sorted(detections, key=lambda d: -d.conf):
        if not any(g.cle == d.cle and (iou(g.boite, d.boite) > 0.3 or contenue(d.boite, g.boite)
                                       or contenue(g.boite, d.boite)) for g in gardees):
            gardees.append(d)
    return [d for d in gardees
            if not any(g is not d and contenue(d.boite, g.boite, 0.8) and aire(g.boite) > 1.5 * aire(d.boite)
                       for g in gardees)]


# ---- Moteurs historiques (coco, yoloe, hybride) -------------------------------
def fusionner(dets, libelle=lambda n: n, iou_min=0.5, prioritaire="custom", iou_meme_moteur=0.8):
    """Supprime les doublons entre détections brutes des moteurs historiques, en deux règles :

    1. ENTRE moteurs : une détection est écartée si une détection d'un AUTRE moteur, de
       même libellé canonique, recouvre sa boîte (IoU >= iou_min). Le moteur `prioritaire`
       (le modèle entraîné) l'emporte quelle que soit la confiance : les scores de deux
       modèles ne se comparent pas.
    2. Dans un MÊME moteur, seulement pour les objets : deux boîtes quasi identiques
       (IoU >= iou_meme_moteur) de libellés différents sont un seul objet vu sous plusieurs
       mots-clés → on garde la plus confiante.
    """
    from ..metriques_detection import canonique
    cle = lambda d: canonique(libelle(d["nom"]))  # noqa: E731
    gardees = []
    for d in sorted(dets, key=lambda d: (d.get("source") != prioritaire, -d["conf"])):
        doublon = False
        for g in gardees:
            o = iou(g["boite"], d["boite"])
            if g.get("source") != d.get("source"):
                doublon = cle(g) == cle(d) and o >= iou_min
            else:
                doublon = g["type"] == d["type"] == "valeur" and o >= iou_meme_moteur
            if doublon:
                break
        if not doublon:
            gardees.append(d)
    return gardees


def est_adulte(det, hauteur_image, hauteur_min=0.35):
    """Un adulte à bord = une « personne » dont la boîte occupe une bonne part de la hauteur
    de l'image. Les petits gabarits (enfant dans un siège, bébé) ne comptent pas : ils ne
    doivent jamais empêcher la surveillance de constater le départ du conducteur."""
    if det["nom"] not in ("person", "personne") or det["type"] != "vivant":
        return False
    return (det["boite"][3] - det["boite"][1]) >= hauteur_min * hauteur_image
