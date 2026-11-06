import numpy as np

from care.cameras import SourceThermique, decoder_tc001, decoder_trame, est_tc001

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


# --- Caméra du banc (« UVC Camera », USB 2BDF:0102) : flux 256x392, comptes bruts en haut ---

def trame_banc(comptes, forme=(392, 256, 2)):
    """Lignes 0-191 : comptes bruts 16 bits ; 192-195 : métadonnées ; 196-387 : image YUYV
    (chrominance 128) ; 388-391 : métadonnées. Disposition relevée sur la vraie caméra."""
    t = np.zeros((392, 256, 2), np.uint8)
    t[:192] = np.asarray(comptes, "<u2").view(np.uint8).reshape(192, 256, 2)
    t[192, :4, 0] = [202, 141, 0, 41]
    t[196:388, :, 0], t[196:388, :, 1] = 90, 128
    return t.reshape(forme)


def habitacle_vide(rng):
    return 5050 + rng.normal(0, 12, (192, 256))   # bruit mesuré sur la caméra : ~10-35 comptes


def test_banc_habitacle_vide_aucun_pixel_chaud():
    rng = np.random.default_rng(0)
    s = SourceThermique("thermal", 0, "banc", PARAMS)
    m, img, tmax = s.masque_chaud(trame_banc(habitacle_vide(rng)))
    assert m.sum() == 0 and tmax is None and "relatif" in s.mode
    assert img.shape == (192, 256) and img.mean() < 40     # habitacle vide : image sombre


def test_banc_enfant_detecte():
    rng = np.random.default_rng(1)
    c = habitacle_vide(rng)
    c[60:120, 90:150] += 350          # corps : ~300-400 comptes au-dessus du fond (mesuré)
    s = SourceThermique("thermal", 0, "banc", PARAMS)
    m, _, _ = s.masque_chaud(trame_banc(c))
    assert abs(int(m.sum()) - 60 * 60) < 60
    assert m[60:120, 90:150].all() and not m[:50].any()


def test_banc_suit_la_derive_du_capteur():
    """Les comptes dérivent avec la température de la caméra : le fond est relatif."""
    rng = np.random.default_rng(2)
    s = SourceThermique("thermal", 0, "banc", PARAMS)
    m, _, _ = s.masque_chaud(trame_banc(habitacle_vide(rng) + 800))
    assert m.sum() == 0


def test_banc_flux_plat_msmf():
    rng = np.random.default_rng(3)
    s = SourceThermique("thermal", 0, "banc", PARAMS)
    m, _, _ = s.masque_chaud(trame_banc(habitacle_vide(rng), forme=(1, 200704)))
    assert m.sum() == 0 and "relatif" in s.mode


def test_banc_converti_par_directshow_pas_d_alerte():
    """DirectShow convertit en couleur : l'ancien code y voyait ~47 000 pixels chauds."""
    f = np.full((392, 256, 3), 255, np.uint8)
    s = SourceThermique("thermal", 0, "banc", PARAMS)
    m, img, tmax = s.masque_chaud(f)
    assert m.sum() == 0 and tmax is None and "perdues" in s.mode and img.shape == (192, 256)


def test_mode_par_defaut_644x384_pas_d_alerte():
    s = SourceThermique("thermal", 0, "banc", {**PARAMS, "modele": "tc001"})
    m, _, _ = s.masque_chaud(np.full((384, 644, 3), 255, np.uint8))
    assert m.sum() == 0 and "illisible" in s.mode


def test_disposition_tc001_inchangee():
    d = decoder_trame(trame_tc001(np.full((192, 256), 25.0)))
    assert d is not None and abs(d[0].mean() / 64 - 273.15 - 25.0) < 0.05


def test_correspondance_directshow_msmf():
    from care.peripheriques import index_msmf
    dshow = [{"index": 0, "nom": "UVC Camera"}, {"index": 1, "nom": "USB Camera"},
             {"index": 2, "nom": "USB Camera"}, {"index": 4, "nom": "1080p FHD Camera"}]
    msmf = [{"index": 0, "nom": "1080p FHD Camera"}, {"index": 1, "nom": "UVC Camera"},
            {"index": 2, "nom": "USB Camera"}, {"index": 3, "nom": "USB Camera"}]
    assert index_msmf(0, dshow, msmf) == 1     # relevé sur le banc
    assert index_msmf(2, dshow, msmf) == 3
    assert index_msmf(9, dshow, msmf) is None
    assert index_msmf(0, dshow, []) is None    # Media Foundation indisponible


def test_ouverture_msmf_avec_index_converti(monkeypatch):
    import care.cameras as cameras
    vus = {}

    class FausseCap:
        def __init__(self, index, backend):
            vus.update(index=index, backend=backend, props={})

        def set(self, prop, val):
            vus["props"][prop] = val

    monkeypatch.setattr(cameras.cv2, "VideoCapture", FausseCap)
    monkeypatch.setattr(cameras.os, "name", "nt")
    monkeypatch.setattr(cameras.peripheriques, "index_msmf", lambda i: {0: 1}.get(i))
    p = {**PARAMS, "backend": "msmf", "resolution": [256, 392]}
    SourceThermique("thermal", 0, "banc", p)._ouvrir()
    cv2 = cameras.cv2
    assert vus["index"] == 1 and vus["backend"] == cv2.CAP_MSMF
    assert vus["props"][cv2.CAP_PROP_CONVERT_RGB] == 0 and vus["props"][cv2.CAP_PROP_FRAME_HEIGHT] == 392
    assert not SourceThermique("thermal", 7, "banc", p)._ouvrir().isOpened()
