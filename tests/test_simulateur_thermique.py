import numpy as np
import pytest

from care.cameras import fond_uniforme, masque_vivant, normaliser_brut
from care.detecteur import Detecteur, DetecteurDemo
from care.reference import Reference
from outils.simuler_thermique import ZONE_TABLEAU_DE_BORD, encoder, essai, scene_temperatures, source_thermique

PARAMS = {"seuil_celsius": 30.0, "seuil_8bit": 200, "pixels_chauds_min": 20}
RES = (80, 60)
AMBIANCES = [5, 22, 30, 45]


def verdict(scenario, ambiance, methode="contraste", mode="16bits", resolution=RES):
    return essai(source_thermique(PARAMS), scenario, ambiance, resolution, 1.0, 10, mode,
                 np.random.default_rng(1), methode)


def test_encodage_16_bits_redonne_la_temperature_au_banc():
    s = source_thermique(PARAMS)
    s.frame = encoder(np.full((60, 80), 34.0, np.float32), "16bits")
    m = s.mesure()
    assert m["mode"] == "radiométrique"
    assert m["tmax"] == pytest.approx(34.0, abs=0.02)


def test_meme_graine_meme_scene():
    a = scene_temperatures("S1", 22, RES, 1.0, np.random.default_rng(7))
    b = scene_temperatures("S1", 22, RES, 1.0, np.random.default_rng(7))
    assert a.shape == (60, 80)
    assert np.array_equal(a, b)


def test_methode_par_defaut_ne_demande_aucune_capture():
    s = source_thermique(PARAMS)
    s.frame = encoder(np.full((60, 80), 22.0, np.float32), "16bits")
    assert s.mesure()["methode"] == "contraste"


def test_seuil_fixe_habitacle_vide_chaud_declenche():
    assert verdict("S7", 45, "seuil fixe") is True


def test_limite_connue_contraste_auto_declenche_sur_habitacle_vide():
    """Comportement ACTUEL en 8 bits : le contraste auto amplifie le bruit d'un habitacle vide."""
    assert verdict("S7", 22, None, mode="8bits") is True


@pytest.mark.parametrize("methode", ["contraste", "référence"])
@pytest.mark.parametrize("ambiance", AMBIANCES)
def test_habitacle_vide_ne_declenche_rien(methode, ambiance):
    assert verdict("S7", ambiance, methode) is False


@pytest.mark.parametrize("methode", ["contraste", "référence"])
@pytest.mark.parametrize("ambiance", AMBIANCES)
def test_enfant_detecte(methode, ambiance):
    assert verdict("S1", ambiance, methode) is True


@pytest.mark.parametrize("methode", ["contraste", "référence"])
def test_enfant_sous_couverture_detecte_en_ambiance_temperee(methode):
    assert verdict("S2", 22, methode) is True


@pytest.mark.parametrize("methode", ["contraste", "référence"])
def test_gourde_brulante_ecartee(methode):
    assert verdict("S8", 22, methode) is False


@pytest.mark.parametrize("resolution", [(80, 60), (160, 120), (256, 192), (320, 240)])
def test_memes_reglages_a_toute_resolution(resolution):
    assert verdict("S1", 22, resolution=resolution) is True
    assert verdict("S7", 22, resolution=resolution) is False


def test_tableau_de_bord_chaud_declenche_sans_zones():
    assert verdict("S7t", 22, "contraste") is True


@pytest.mark.parametrize("ambiance", AMBIANCES)
def test_tableau_de_bord_chaud_ignore_avec_zones(ambiance):
    assert verdict("S7t", ambiance, "contraste + zones") is False


@pytest.mark.parametrize("resolution", [(80, 60), (160, 120), (256, 192), (320, 240)])
def test_bord_d_une_zone_ignoree_ne_declenche_pas(resolution):
    """256x192 : 20 % de la hauteur tombe entre deux pixels, le bord chaud débordait de la zone."""
    assert verdict("S7t", 22, "contraste + zones", resolution=resolution) is False


def test_zone_ignoree_est_exprimee_en_part_de_l_image():
    for w, h in ((80, 60), (320, 240)):
        temp = np.full((h, w), 22.0, np.float32)
        temp[:round(h * 0.2), :] = 34.0
        p = {"zones_ignorees": [ZONE_TABLEAU_DE_BORD]}
        assert fond_uniforme(temp, p)[0, 0] == pytest.approx(22.0)
        assert not masque_vivant(temp, fond_uniforme(temp, p), p).any()


def test_limite_connue_siege_encore_chaud_declenche():
    """Comportement ACTUEL : à inverser quand l'évolution dans le temps sera suivie."""
    assert verdict("S7s", 22) is True


def test_gourde_contre_un_enfant_ne_masque_pas_l_enfant():
    temp = np.full((60, 80), 22.0, np.float32)
    ref = temp.copy()
    temp[20:50, 25:50] = 30.0     # enfant
    temp[25:45, 50:55] = 55.0     # gourde collée à l'enfant
    assert masque_vivant(temp, ref, PARAMS).any()


def test_reference_rechauffement_uniforme_ignore():
    ref = np.full((60, 80), 22.0, np.float32)
    assert not masque_vivant(ref + 10, ref, PARAMS).any()


def test_taille_minimale_ne_depend_pas_de_la_resolution():
    for w, h in ((80, 60), (320, 240)):
        ref = np.full((h, w), 22.0, np.float32)
        temp = ref.copy()
        cote = round(0.03 * w)    # moins de 0,4 % de l'image, quelle que soit la résolution
        temp[10:10 + cote, 10:10 + cote] = 34.0
        assert not masque_vivant(temp, ref, PARAMS).any()
        cote = round(0.15 * w)    # largement au-dessus
        temp[10:10 + cote, 10:10 + cote] = 34.0
        assert masque_vivant(temp, ref, PARAMS).any()


def test_methode_reference_sans_reference_repasse_au_contraste():
    s = source_thermique({**PARAMS, "methode": "reference"})
    s.reference = np.full((120, 160), 22.0, np.float32)  # autre résolution : inutilisable
    s.frame = encoder(np.full((60, 80), 22.0, np.float32), "16bits")
    assert s.mesure()["methode"] == "contraste"


@pytest.mark.parametrize("diviseur", [100, 10, 64])
def test_diviseur_kelvin_configurable(diviseur):
    s = source_thermique({**PARAMS, "diviseur_kelvin": diviseur})
    s.frame = np.full((60, 80), round((34 + 273.15) * diviseur), np.uint16)
    assert s.mesure()["tmax"] == pytest.approx(34.0, abs=0.1)
    assert s.mesure()["mode"] == "radiométrique"


def test_echelle_fausse_annoncee_non_calibree():
    s = source_thermique(PARAMS)
    s.frame = np.full((60, 80), 8000, np.uint16)  # comptes bruts d'un capteur, pas des températures
    assert s.mesure()["mode"] == "16 bits non calibré"


def test_resolution_lue_sur_la_camera():
    s = source_thermique(PARAMS)
    s.frame = encoder(np.full((192, 256), 22.0, np.float32), "16bits")
    assert s.mesure()["resolution"] == "256x192"


def test_normaliser_16_bits_en_deux_canaux():
    brut = np.full((60, 80), 30715, np.uint16)
    deux_canaux = np.dstack([(brut & 0xFF).astype(np.uint8), (brut >> 8).astype(np.uint8)])
    assert np.array_equal(normaliser_brut(deux_canaux), brut)


def test_normaliser_tampon_a_plat():
    brut = np.arange(80 * 60, dtype=np.uint16).reshape(60, 80)
    assert np.array_equal(normaliser_brut(np.frombuffer(brut.tobytes(), np.uint8).reshape(1, -1), 80, 60), brut)
    assert np.array_equal(normaliser_brut(brut.reshape(1, -1), 80, 60), brut)


def test_normaliser_garde_les_temperatures_d_une_double_image():
    visible = np.zeros((192, 256), np.uint16)
    temperatures_brutes = np.full((192, 256), round((24 + 273.15) * 64), np.uint16)
    empilee = np.vstack([visible, temperatures_brutes])
    octets = np.dstack([(empilee & 0xFF).astype(np.uint8), (empilee >> 8).astype(np.uint8)])
    assert np.array_equal(normaliser_brut(octets), temperatures_brutes)


def test_normaliser_laisse_du_256x192_intact():
    f = np.full((192, 256), 30000, np.uint16)
    assert normaliser_brut(f) is f


def test_normaliser_laisse_une_image_normale_intacte():
    f = np.zeros((60, 80, 3), np.uint8)
    assert normaliser_brut(f, 80, 60) is f


def test_analyse_avec_la_thermique_seule_journalise_methode_et_resolution():
    det = DetecteurDemo({"images_par_essai": 2, "ratio_presence": 0.5, "detection": {}})
    s = source_thermique(PARAMS)
    temp = np.full((120, 160), 22.0, np.float32)
    temp[30:90, 50:110] = 33.0
    s.frame = encoder(temp, "16bits")
    r = Detecteur.analyser(det, [], s)
    assert r["vivant_thermique"] is True
    assert r["methode_thermique"] == "contraste"
    assert r["resolution_thermique"] == "160x120"
    assert np.array_equal(r["image_thermique_brute"], s.frame)


def test_reference_thermique_capturee_rechargee_puis_effacee(tmp_path):
    source = source_thermique(PARAMS)
    source.frame = encoder(np.full((60, 80), 22.0, np.float32), "16bits")
    ref = Reference(str(tmp_path), {})
    ref.lier_thermique(source)
    ref._capturer_thermique(1)
    assert source.reference == pytest.approx(22.0, abs=0.02)

    relue = Reference(str(tmp_path), {})
    assert relue.thermique == pytest.approx(22.0, abs=0.02)

    ref.effacer()
    assert source.reference is None
    assert Reference(str(tmp_path), {}).thermique is None


def test_camera_sans_temperature_ne_laisse_pas_de_reference_perimee(tmp_path):
    source = source_thermique(PARAMS)
    source.frame = encoder(np.full((60, 80), 22.0, np.float32), "16bits")
    ref = Reference(str(tmp_path), {})
    ref.lier_thermique(source)
    ref._capturer_thermique(1)

    source.frame = np.zeros((60, 80), np.uint8)
    ref._capturer_thermique(1)
    assert source.reference is None
    assert Reference(str(tmp_path), {}).thermique is None
