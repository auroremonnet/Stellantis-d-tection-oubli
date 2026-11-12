"""Comparaison à la référence « habitacle vide », sur des scènes synthétiques."""
import cv2
import numpy as np

from care.detection.changement import Comparaison, Reglages


def habitacle(graine=0):
    """Siège clair texturé, console sombre à gauche, boucle orange."""
    rng = np.random.default_rng(graine)
    img = np.full((480, 640, 3), 170, np.uint8)
    for x in range(0, 640, 80):
        cv2.line(img, (x, 0), (x, 480), (150, 150, 150), 2)
    for y in range(0, 480, 80):
        cv2.line(img, (0, y), (640, y), (150, 150, 150), 2)
    cv2.rectangle(img, (0, 0), (120, 480), (40, 40, 40), -1)
    cv2.rectangle(img, (130, 200), (160, 240), (40, 90, 230), -1)
    return cv2.add(img, rng.integers(0, 6, img.shape, dtype=np.uint8))


def avec_telephone(img, boite=(300, 200, 420, 260)):
    out = img.copy()
    cv2.rectangle(out, boite[:2], boite[2:], (25, 25, 25), -1)
    return out


def test_objet_pose_donne_une_zone_et_la_boucle_est_deja_la():
    cp = Comparaison(habitacle(0), avec_telephone(habitacle(1)))
    zones = cp.zones()
    assert len(zones) == 1 and not cp.inutilisable
    x1, y1, x2, y2 = zones[0]
    assert abs(x1 - 300) < 12 and abs(y1 - 200) < 12 and abs(x2 - 420) < 12 and abs(y2 - 260) < 12
    assert cp.part_changee([300, 200, 420, 260]) > 0.8          # nouveau
    assert cp.part_changee([130, 200, 160, 240]) < 0.15         # la boucle était déjà là


def test_habitacle_identique_aucune_zone():
    assert Comparaison(habitacle(0), habitacle(1)).zones() == []


def test_changement_d_exposition_ignore():
    """Nuage, auto-exposition : toute l'image s'éclaircit de 20 %, rien n'est signalé."""
    plus_clair = cv2.convertScaleAbs(habitacle(1), alpha=1.2, beta=6)
    cp = Comparaison(habitacle(0), plus_clair)
    assert cp.zones() == [] and not cp.inutilisable
    cp = Comparaison(habitacle(0), avec_telephone(plus_clair))
    assert len(cp.zones()) == 1                                 # et l'objet reste vu


def test_camera_legerement_bougee_recalee():
    decale = np.roll(habitacle(1), (4, 6), axis=(0, 1))
    cp = Comparaison(habitacle(0), decale)
    assert cp.recalage_fiable and cp.zones() == []


def test_cable_deplace_n_est_pas_un_objet():
    img = habitacle(1)
    cv2.line(img, (200, 100), (560, 420), (20, 20, 20), 5)
    assert Comparaison(habitacle(0), img).zones() == []


def test_scene_bouleversee_reference_inutilisable():
    autre = np.full((480, 640, 3), 60, np.uint8)
    cv2.circle(autre, (320, 240), 200, (200, 220, 240), -1)
    cp = Comparaison(habitacle(0), autre)
    assert cp.inutilisable and cp.zones() == []


def test_reference_d_une_autre_resolution_et_reglages_de_la_config():
    ref = cv2.resize(habitacle(0), (1280, 960))
    assert len(Comparaison(ref, avec_telephone(habitacle(1))).zones()) == 1
    r = Reglages.depuis_config({"zones_max": 2, "_aide": "ignoré", "inconnu": 1})
    assert r.zones_max == 2 and r.seuil_luminance == 24.0
