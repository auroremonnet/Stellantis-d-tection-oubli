"""Géométrie des boîtes englobantes ([x1, y1, x2, y2] en pixels). Fonctions pures."""
from __future__ import annotations

Boite = list  # [x1, y1, x2, y2]


def aire(b) -> float:
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def intersection(a, b) -> float:
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def iou(a, b) -> float:
    inter = intersection(a, b)
    return 0.0 if inter == 0 else inter / float(aire(a) + aire(b) - inter)


def recouvrement(a, b) -> float:
    """Part de `a` couverte par `b` (0..1)."""
    return intersection(a, b) / float(max(1.0, aire(a)))


def contenue(a, b, part: float = 0.7) -> bool:
    """Vrai si `a` est (presque) entièrement dans `b`."""
    return recouvrement(a, b) >= part


def nms(elements, boite=lambda e: e, score=lambda e: 0.0, seuil_iou: float = 0.7):
    """Suppression des doublons : parcourt par score décroissant, garde un élément s'il ne
    recouvre (IoU >= seuil) aucun élément déjà gardé."""
    gardes = []
    for e in sorted(elements, key=score, reverse=True):
        if all(iou(boite(e), boite(g)) < seuil_iou for g in gardes):
            gardes.append(e)
    return gardes


def entiers(b) -> list:
    return [int(round(v)) for v in b]
