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


# --- Caméra du banc + méthode « reference » : comparaison à l'habitacle vide, en comptes bruts ---

def siege_au_soleil(rng):
    """Habitacle vide mais contrasté, comme relevé sur le banc : un siège 300 comptes au-dessus du reste."""
    scene = 5050 + rng.normal(0, 8, (192, 256))
    scene[40:192, 140:256] += 300
    return scene


def source_banc(methode="reference", **params):
    return SourceThermique("th", 0, "x", {**PARAMS, "modele": "tc001", "methode": methode, **params})


def avec_reference(scene_vide, **params):
    s = source_banc(**params)
    s.poser_reference(*s.champ(trame_banc(scene_vide)))
    return s


def test_banc_siege_chaud_declenche_sans_reference_mais_pas_avec():
    """Le contraste seul prend un siège chauffé par le soleil pour un occupant : c'est la raison
    d'être de la référence (constat fait sur les trames réelles du 06/11)."""
    rng = np.random.default_rng(3)
    vide = siege_au_soleil(rng)
    plus_tard = vide + 60 + rng.normal(0, 8, vide.shape)        # dérive du capteur entre-temps
    assert source_banc("contraste").analyser(trame_banc(plus_tard))["chaud"]
    m = avec_reference(vide).analyser(trame_banc(plus_tard))
    assert not m["chaud"] and m["methode"] == "référence" and m["unite"] == "comptes"
    assert m["ecart_max"] < 60                                   # la dérive globale est retirée


def test_banc_enfant_detecte_par_reference_meme_sur_le_siege_chaud():
    rng = np.random.default_rng(4)
    vide = siege_au_soleil(rng)
    scene = vide + 60 + rng.normal(0, 8, vide.shape)
    scene[90:130, 170:215] += 320                                # un corps, sur le siège déjà chaud
    m = avec_reference(vide).analyser(trame_banc(scene))
    assert m["chaud"] and m["pixels_chauds"] > 1000 and m["ecart_max"] > 250
    assert m["tmax"] is None                                     # pas de température en comptes bruts


def test_banc_petite_tache_chaude_ecartee():
    """Un point chaud de quelques pixels (voyant, reflet) n'est pas un corps."""
    rng = np.random.default_rng(5)
    vide = siege_au_soleil(rng)
    scene = vide + rng.normal(0, 8, vide.shape)
    scene[20:26, 20:26] += 600
    assert not avec_reference(vide).analyser(trame_banc(scene))["chaud"]


def test_banc_zone_ignoree_et_seuil_reglable():
    rng = np.random.default_rng(6)
    vide = siege_au_soleil(rng)
    scene = vide + rng.normal(0, 8, vide.shape)
    scene[0:60, 0:80] += 400                                     # vitre au soleil, en haut à gauche
    assert avec_reference(vide).analyser(trame_banc(scene))["chaud"]
    assert not avec_reference(vide, zones_ignorees=[[0, 0, 0.35, 0.35]]).analyser(trame_banc(scene))["chaud"]
    assert not avec_reference(vide, delta_comptes=500).analyser(trame_banc(scene))["chaud"]


def test_reference_d_une_autre_unite_ou_taille_ignoree():
    """Référence en °C (autre caméra) ou d'une autre taille : on repasse au contraste, sans planter."""
    rng = np.random.default_rng(7)
    s = source_banc()
    s.poser_reference(np.full((192, 256), 22.0, np.float32))     # des °C, pas des comptes
    assert s.analyser(trame_banc(habitacle_vide(rng)))["methode"] == "contraste"
    s.poser_reference(np.full((60, 80), 5000.0, np.float32), "comptes")
    assert s.analyser(trame_banc(habitacle_vide(rng)))["methode"] == "contraste"
    s.poser_reference(None)
    assert s.unite_reference is None


def test_reference_du_banc_capturee_et_relue(tmp_path):
    from care.reference import Reference
    rng = np.random.default_rng(8)
    s = source_banc()
    s.frame = trame_banc(siege_au_soleil(rng))
    ref = Reference(str(tmp_path), None)
    ref.lier_thermique(s)
    ref._capturer_thermique(2, pause_s=0)
    assert s.unite_reference == "comptes" and s.reference.shape == (192, 256) and ref.etat()["thermique"]
    relue = Reference(str(tmp_path), None)
    assert relue.unite_thermique == "comptes" and relue.thermique.shape == (192, 256)
    autre = source_banc()
    relue.lier_thermique(autre)                                  # au redémarrage, la caméra la retrouve
    assert autre.unite_reference == "comptes"
    ref.effacer()
    assert s.reference is None and Reference(str(tmp_path), None).thermique is None
