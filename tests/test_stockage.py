import csv

import pytest

from care.stockage import COLONNES, Journal, detection_par_objet, indicateurs, metriques, retrouve

# En-tête du journal du 21/10 : ni mode, ni alerte, ni latence d'alerte, ni objets posés
ANCIEN_ENTETE = ["id", "horodatage", "scenario", "variante", "verite", "vivant_rgb", "vivant_thermique",
                 "classes_vivant", "objets", "cameras_vivant", "pixels_chauds", "tmax", "latence_s",
                 "commentaire", "moteur", "zones_nouvelles", "reference_utilisee", "lumiere_changee"]
ANCIENNES_LIGNES = [
    ["20261021-103458", "2026-10-21T10:34:58", "S1", "Jour", "vivant", "1", "", "personne",
     "lunettes, téléphone", "rgb0", "", "", "4.31", "", "yoloe", "0", "0", "0"],
    ["20261022-170405", "2026-10-22T17:04:05", "S5", "Jour", "objet", "0", "0", "",
     "ordinateur, portefeuille", "", "0", "", "28.43", "", "yoloe", "0", "0", "0"],
    ["20261022-170532", "2026-10-22T17:05:32", "S7", "Jour", "vide", "0", "", "", "", "", "", "", "3.1",
     "", "yoloe", "0", "0", "0"],
]


@pytest.fixture
def ancien_csv(tmp_path):
    p = tmp_path / "essais.csv"
    with open(p, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(ANCIEN_ENTETE)
        w.writerows(ANCIENNES_LIGNES)
    return p


def essai(verite, mode="auto", alerte="", objets="", poses="", latence=None, rgb=False, th=None,
          classes=""):
    """Ligne telle que Journal.lire() la rend (champs utiles aux calculs)."""
    from care.stockage import evaluer, niveau_alerte
    l = {"verite": verite, "scenario": "S?", "mode": mode, "alerte": alerte, "objets": objets,
         "objets_poses": poses, "classes_vivant": classes, "vivant_rgb": rgb, "vivant_thermique": th,
         "latence_alerte_s": "" if latence is None else str(latence), "latence_s": "1.0"}
    l.update(evaluer(l))
    l["niveau_alerte"] = niveau_alerte(l)
    return l


# ---- Journal : migration d'un ancien CSV ------------------------------------------
def test_ancien_csv_migre_sans_perte(ancien_csv):
    j = Journal(str(ancien_csv))
    with open(ancien_csv, encoding="utf-8-sig") as fh:
        entete = next(csv.reader(fh, delimiter=";"))
    assert entete == COLONNES                      # colonnes ajoutées par la migration
    lignes = j.lire()
    assert [l["id"] for l in lignes] == [r[0] for r in ANCIENNES_LIGNES]
    assert lignes[0]["objets"] == "lunettes, téléphone" and lignes[1]["latence_s"] == "28.43"
    assert all(l["objets_poses"] == "" and l["mode"] == "" for l in lignes)
    m = metriques(lignes)                         # les indicateurs se calculent sans erreur
    assert m["indicateurs"]["vivant"]["taux"] == 1.0
    assert m["indicateurs"]["latence"]["n"] == 0


def test_ancien_csv_alerte_deduite_de_la_decision(ancien_csv):
    lignes = Journal(str(ancien_csv)).lire()
    assert [l["niveau_alerte"] for l in lignes] == ["critique", "objet", None]
    ind = indicateurs(lignes)
    assert ind["objets"]["taux"] == 1.0           # pas un faux 0 % faute de colonne « alerte »
    assert ind["fausses_alertes"]["taux"] == 0.0


def test_objets_poses_enregistres_en_liste(tmp_path):
    j = Journal(str(tmp_path / "essais.csv"))
    j.ajouter({"id": "a", "horodatage": "2026-11-01T10:00:00", "scenario": "S5", "verite": "objet",
               "objets": ["clés de voiture"], "objets_poses": ["clés", "téléphone"], "mode": "manuel",
               "alerte": "objet", "vivant_rgb": False})
    (l,) = j.lire()
    assert l["objets_poses"] == "clés, téléphone"
    assert l["niveau_alerte"] == "objet"


# ---- Indicateurs clés ----------------------------------------------------------------
def test_indicateurs_vides_jamais_zero():
    ind = indicateurs([])
    assert ind["vivant"]["taux"] is None and ind["objets"]["taux"] is None
    assert ind["fausses_alertes"]["taux"] is None
    assert ind["latence"]["moyenne"] is None and ind["latence"]["conforme"] is None


def test_vivant_meilleure_approche_disponible():
    # RGB rate, thermique voit : A2 = VP ; sans thermique on retombe sur A1
    lignes = [essai("vivant", rgb=False, th=True), essai("vivant", rgb=True, th=False)]
    v = indicateurs(lignes)["vivant"]
    assert (v["n"], v["detectes"], v["taux"], v["approche"]) == (2, 2, 1.0, "A2")
    v = indicateurs([essai("vivant", rgb=False), essai("vivant", rgb=True)])["vivant"]
    assert (v["taux"], v["approche"]) == (0.5, "A1")
    assert indicateurs([essai("vivant", rgb=True, th=False), essai("vivant", rgb=True)])["vivant"]["approche"] == "A1/A2"


def test_objets_et_fausses_alertes():
    lignes = [essai("objet", alerte="objet"), essai("objet", alerte=""), essai("objet", alerte="critique"),
              essai("vide", alerte=""), essai("vide", alerte="critique"), essai("vide", alerte="objet"),
              essai("vide", alerte="")]
    ind = indicateurs(lignes)
    assert (ind["objets"]["detectes"], ind["objets"]["n"], ind["objets"]["taux"]) == (1, 3, 0.333)
    assert (ind["fausses_alertes"]["alertes"], ind["fausses_alertes"]["n"]) == (2, 4)
    assert ind["fausses_alertes"]["taux"] == 0.5


def test_latence_essais_auto_uniquement_et_objectif_ncap():
    lignes = [essai("objet", latence=9.2), essai("vide", latence=12.4),
              essai("objet", mode="manuel", latence=40), essai("objet")]
    lat = indicateurs(lignes)["latence"]
    assert (lat["n"], lat["moyenne"], lat["pire"], lat["conforme"]) == (2, 10.8, 12.4, True)
    lat = indicateurs([essai("objet", latence=9.0), essai("objet", latence=15.6)])["latence"]
    assert lat["conforme"] is False


# ---- Détection par objet -------------------------------------------------------------
@pytest.mark.parametrize("pose, detecte, attendu", [
    ("clés", ["clés de voiture"], True),          # synonyme
    ("carte bancaire", ["carte"], True),
    ("sac", ["sac à main"], True),                # famille
    ("sac", ["sac à dos", "ordinateur"], True),
    ("téléphone", ["ordinateur"], False),
    ("poupon", ["personne"], True),
    ("portefeuille", [], False),
])
def test_retrouve(pose, detecte, attendu):
    assert retrouve(pose, detecte) is attendu


def test_detection_par_objet():
    lignes = [
        essai("objet", alerte="objet", poses="téléphone", objets="téléphone"),
        essai("objet", alerte="objet", poses="téléphone", objets="objet non identifié"),
        essai("objet", alerte="", poses="clés, téléphone", objets="clés de voiture"),
        essai("vide", alerte="objet", poses="veste", objets="objet non identifié"),
        essai("vide", alerte="", poses="veste"),
        essai("objet", alerte="objet", poses="autre", objets="objet non identifié"),
        essai("objet", alerte="objet", objets="sac"),                     # sans objet posé : ignoré
    ]
    par = {(a["objet"], a["categorie"]): a for a in detection_par_objet(lignes)}
    tel = par[("téléphone", "valeur")]
    assert (tel["n"], tel["identifies"], tel["signales"]) == (3, 1, 2)
    assert tel["taux"] == 0.333 and tel["taux_signale"] == 0.667
    assert par[("clés", "valeur")]["taux"] == 1.0
    veste = par[("veste", "anodin")]
    assert (veste["n"], veste["taux_signale"]) == (2, 0.5)
    autre = par[("autre", "valeur")]
    assert autre["identifiable"] is False and autre["taux"] is None and autre["taux_signale"] == 1.0
    ordre = [(a["categorie"], a["objet"]) for a in detection_par_objet(lignes)]
    assert ordre[0] == ("valeur", "téléphone") and ordre[-1] == ("anodin", "veste")


def test_metriques_exposent_thermique_mesuree():
    assert metriques([essai("vivant", rgb=True)])["thermique_mesuree"] is False
    assert metriques([essai("vivant", rgb=True, th=False)])["thermique_mesuree"] is True
