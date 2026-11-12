import pytest

from care.metriques_detection import Evaluation, apparier

B = [10, 10, 110, 110]
DECALEE = [15, 12, 112, 108]       # IoU ≈ 0,86 avec B
LOIN = [400, 400, 450, 450]


def test_vrai_positif_avec_synonymes():
    r = apparier([("clés", B)], [("clés de voiture", 0.8, DECALEE)])
    assert (r["clés"].vp, r["clés"].fp, r["clés"].fn) == (1, 0, 0)


def test_mauvaise_position_compte_fp_et_fn():
    r = apparier([("portefeuille", B)], [("portefeuille", 0.9, LOIN)])
    assert (r["portefeuille"].vp, r["portefeuille"].fp, r["portefeuille"].fn) == (0, 1, 1)


def test_doublon_compte_un_seul_vp():
    r = apparier([("clés", B)], [("clés", 0.9, B), ("clés", 0.5, DECALEE)])
    assert (r["clés"].vp, r["clés"].fp) == (1, 1)
    assert r["clés"].confiances_vp == [0.9]  # la plus confiante est appariée d'abord


def test_mauvaise_classe_ne_compte_pas():
    r = apparier([("clés", B)], [("téléphone", 0.9, B)])
    assert r["clés"].fn == 1 and r["téléphone"].fp == 1


def test_evaluation_globale_et_par_image():
    ev = Evaluation(classes=("clés", "portefeuille", "carte bancaire", "bébé"))
    ev.ajouter([("clés", B)], [("clés", 0.9, B)], latence_s=0.2)                 # bon
    ev.ajouter([("portefeuille", B)], [], latence_s=0.3)                          # raté
    ev.ajouter([], [("carte", 0.4, B)], latence_s=0.1)                            # fausse alerte
    ev.ajouter([], [("personne", 0.9, B)])                                        # classe non évaluée : ignorée
    d = ev.en_dict()
    assert d["images"] == 4
    assert d["global"] == {"VP": 1, "FP": 1, "FN": 1, "precision": 0.5, "rappel": 0.5, "f1": 0.5}
    assert d["alerte_par_image"]["VP"] == 1 and d["alerte_par_image"]["FP"] == 1
    assert d["par_classe"]["carte bancaire"]["FP"] == 1
    assert d["par_classe"]["bébé"]["precision"] is None   # aucune donnée : pas de faux 0 %
    assert d["latence_moyenne_s"] == pytest.approx(0.2)


def test_chemin_label_convention_yolo():
    from pathlib import PurePosixPath, PureWindowsPath

    from outils.evaluer import chemin_label
    assert chemin_label(PurePosixPath("/d/test/images/a.jpg")) == PurePosixPath("/d/test/labels/a.txt")
    win = PureWindowsPath(r"C:\d\images\test\images\b.png")
    assert chemin_label(win) == PureWindowsPath(r"C:\d\images\test\labels\b.txt")


def test_appariement_par_points():
    from care.metriques_detection import apparier_points
    verites = [("téléphone", 100, 100), ("clés", 300, 300), ("?", 500, 400)]
    preds = [("téléphone", 0.9, [60, 80, 140, 120]),          # juste
             ("clés de voiture", 0.8, [310, 305, 350, 340]),  # juste : synonyme, point à 10 px du bord
             ("portefeuille", 0.7, [480, 380, 520, 420]),     # zone ambiguë : ni juste ni faux
             ("téléphone", 0.6, [0, 0, 30, 30]),              # faux
             ("clés", 0.5, [0, 0, 400, 400])]                 # boîte démesurée : faux
    r = apparier_points(verites, preds, 640, 480)
    assert (r["téléphone"].vp, r["téléphone"].fp, r["téléphone"].fn) == (1, 1, 0)
    assert (r["clés"].vp, r["clés"].fp, r["clés"].fn) == (1, 1, 0)
    assert "portefeuille" not in r
    assert apparier_points([("lunettes", 10, 10)], [], 640, 480)["lunettes"].fn == 1
