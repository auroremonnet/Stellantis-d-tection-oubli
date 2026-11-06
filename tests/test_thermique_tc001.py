import numpy as np

from care.cameras import SourceThermique, decoder_tc001, est_tc001

PARAMS = {"modele": "auto", "seuil_celsius": 30.0, "seuil_8bit": 200, "pixels_chauds_min": 20}


def trame_tc001(temp_c, forme=(384, 256, 2)):
    """Trame brute TC001 : moitié haute = image quelconque, moitié basse = températures."""
    brut = np.round((np.asarray(temp_c, np.float64) + 273.15) * 64).astype("<u2")
    haut = np.full((192, 256, 2), 128, np.uint8)
    bas = brut.view(np.uint8).reshape(192, 256, 2)
    return np.concatenate([haut, bas]).reshape(forme)


def test_habitacle_vide_puis_poupee_chauffee():
    temp = np.full((192, 256), 22.0)
    s = SourceThermique("thermal", 0, "TC001", PARAMS)
    m, _, tmax = s.masque_chaud(trame_tc001(temp))
    assert m.sum() == 0 and abs(tmax - 22.0) < 0.05 and "TC001" in s.mode
    temp[80:110, 100:140] = 34.0
    m, img, tmax = s.masque_chaud(trame_tc001(temp))
    assert m.sum() == 30 * 40 and abs(tmax - 34.0) < 0.05 and img.shape == (192, 256)


def test_flux_plat_windows():
    t = decoder_tc001(trame_tc001(np.full((192, 256), 25.0), forme=(1, 196608)))
    assert t.shape == (192, 256) and abs(t.mean() - 25.0) < 0.05


def test_flux_converti_en_couleur():
    f = np.zeros((384, 256, 3), np.uint8)
    assert est_tc001(f) and decoder_tc001(f) is None
    s = SourceThermique("thermal", 0, "TC001", PARAMS)
    m, img, tmax = s.masque_chaud(f)
    assert tmax is None and "perdues" in s.mode and img.shape == (192, 256)


def test_lepton_inchangee():
    s = SourceThermique("thermal", 0, "Lepton", PARAMS)
    f = np.full((60, 80), int((22 + 273.15) * 100), np.uint16)
    _, _, tmax = s.masque_chaud(f)
    assert abs(tmax - 22.0) < 0.05 and s.mode == "radiométrique"
