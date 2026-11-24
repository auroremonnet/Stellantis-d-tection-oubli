"""Analyse d'une image thermique : où y a-t-il un corps vivant ?

Fonctions pures, sans caméra (le décodage du flux est dans care/cameras.py). Elles
travaillent sur un « champ » : un tableau 2D de flottants, dans l'une de deux unités :

    CELSIUS   températures, quand la caméra est radiométrique (Topdon TC001, Lepton) ;
    COMPTES   comptes bruts du capteur, non calibrés (caméra du banc, « UVC Camera ») :
              on ne connaît que des écarts, pas de température absolue.

Trois méthodes (thermique.methode dans config.json) :

    reference    compare au même habitacle, vide, capturé à l'armement. La seule qui ne
                 confond pas un siège chauffé par le soleil avec un occupant ; sans
                 référence disponible, repasse au contraste.
    contraste    compare chaque pixel au fond médian de l'image : rien à capturer, mais tout
                 ce qui est plus chaud que le reste de l'habitacle ressort.
    seuil_fixe   au-dessus d'une température donnée (ou, en comptes, d'un écart au centile bas).

Dans tous les cas un réchauffement global entre la référence et l'image (soleil, dérive du
capteur) est retiré avant de comparer, et les zones trop petites sont écartées.
"""
from __future__ import annotations

import cv2
import numpy as np

CELSIUS, COMPTES = "°C", "comptes"
TEMP_PLAUSIBLE_C = (-40.0, 120.0)   # au-delà, le format supposé des températures est faux

# Surchargeables dans config.json → thermique. Les valeurs en °C viennent de la simulation
# (outils/simuler_thermique.py) ; delta_comptes est à régler sur le banc avec
# `outils/diagnostic_thermique.py direct`, qui affiche l'écart maximal mesuré.
#   zones_ignorees : [[x1, y1, x2, y2], ...] en part de l'image (0 à 1) : vitres, tableau de bord
#   diviseur_kelvin : valeur brute / diviseur = kelvins (100 pour le format TLinear)
DEFAUTS = {
    "methode": "contraste",
    "delta_c": 2.5,                # écart minimal au fond pour un corps vivant
    "delta_comptes": 200,          # idem quand la caméra ne donne que des comptes bruts
    "temp_max_vivant_c": 42.0,     # plus chaud : gourde, objet au soleil
    "temp_corps_c": 37.0,          # habitacle plus chaud que ça : un vivant paraît plus froid
    "part_min_image": 0.004,       # taille minimale d'une zone, en part de l'image
    "zones_ignorees": [],
    "diviseur_kelvin": 100,
    "seuil_celsius": 30.0,
    "seuil_comptes": 200,
    "centile_fond": 10,
    "seuil_8bit": 200,
    "pixels_chauds_min": 20,
}


def temperatures(f, diviseur=100):
    """Image 16 bits → températures en °C."""
    return f.astype(np.float32) / diviseur - 273.15


def temperature_plausible(temp) -> bool:
    return TEMP_PLAUSIBLE_C[0] <= float(np.median(temp)) <= TEMP_PLAUSIBLE_C[1]


def masque_zones(forme, zones):
    """Vrai sur les pixels des zones ignorées, indiquées en part de l'image."""
    h, w = forme[:2]
    masque = np.zeros((h, w), bool)
    for x1, y1, x2, y2 in zones:
        masque[round(y1 * h):round(y2 * h), round(x1 * w):round(x2 * w)] = True
    return masque


def fond_uniforme(champ, p):
    """Fond estimé dans l'image elle-même : aucune capture à faire par l'utilisateur."""
    ignore = masque_zones(champ.shape, p.get("zones_ignorees", []))
    valeurs = champ[~ignore] if not ignore.all() else champ
    return np.full(champ.shape, np.median(valeurs), np.float32)


def ecart_au_fond(champ, ref, p):
    """Écart de chaque pixel à `ref` (fond de l'image ou habitacle vide), une fois retiré le
    réchauffement global de l'habitacle. Renvoie (écart, masque des zones ignorées)."""
    ignore = masque_zones(champ.shape, p.get("zones_ignorees", []))
    diff = champ.astype(np.float32) - ref
    return diff - np.median(diff[~ignore] if not ignore.all() else diff), ignore


def masque_vivant(champ, ref, p, unite=CELSIUS):
    """Zones qui peuvent être un corps vivant, par écart à `ref`.

    En comptes bruts, seules les règles relatives s'appliquent : sans température absolue,
    impossible de dire « trop chaud pour être vivant » ou « habitacle plus chaud qu'un corps ».
    """
    p = {**DEFAUTS, **p}
    diff, ignore = ecart_au_fond(champ, ref, p)
    delta = p["delta_c"] if unite == CELSIUS else p["delta_comptes"]
    plus_chaud = diff > delta
    # marge : le flou de l'optique déborde du bord d'une zone ignorée
    marge = cv2.dilate(ignore.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    masque = plus_chaud & ~marge
    if unite == CELSIUS:
        # dans un habitacle plus chaud que le corps, un être vivant apparaît comme une zone plus froide
        masque |= (ref > p["temp_corps_c"]) & (diff < -delta) & ~marge
        # trop chaud pour être vivant (gourde, objet au soleil) : on l'écarte avec son halo de flou,
        # sans écarter tout ce qui le touche, pour qu'un objet chaud ne masque pas un enfant
        brulant = plus_chaud & (champ > p["temp_max_vivant_c"])
        if brulant.any():
            masque &= ~(cv2.dilate(brulant.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0)
    # taille en part de l'image : le réglage ne dépend pas de la résolution de la caméra
    _, etiquettes, stats, _ = cv2.connectedComponentsWithStats(masque.astype(np.uint8), connectivity=8)
    taille_min = max(1, p["part_min_image"] * masque.size)
    gardees = [i for i in range(1, len(stats)) if stats[i, cv2.CC_STAT_AREA] >= taille_min]
    return np.isin(etiquettes, gardees)
