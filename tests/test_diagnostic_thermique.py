import json

import numpy as np
import pytest

import outils.diagnostic_thermique as diag
from care.config import charger_config, modifier_config_locale


def image_16_bits(temp=24.0, diviseur=100, forme=(120, 160)):
    return np.full(forme, round((temp + 273.15) * diviseur), np.uint16)


@pytest.mark.parametrize("diviseur", [100, 10, 64])
def test_analyse_retrouve_l_echelle_des_temperatures(diviseur):
    info = diag.analyser_image(image_16_bits(diviseur=diviseur))
    assert info["score"] == 3
    assert info["diviseur_kelvin"] == diviseur
    assert info["temp_mediane"] == pytest.approx(24.0, abs=0.2)
    assert info["resolution"] == "160x120"


def test_double_image_vue_comme_256x192_en_kelvins_sur_64():
    temp = image_16_bits(diviseur=64, forme=(192, 256))
    empilee = np.vstack([np.zeros((192, 256), np.uint16), temp])
    octets = np.dstack([(empilee & 0xFF).astype(np.uint8), (empilee >> 8).astype(np.uint8)])
    info = diag.analyser_image(diag.normaliser_brut(octets))
    assert info["resolution"] == "256x192"
    assert info["diviseur_kelvin"] == 64
    assert info["temp_mediane"] == pytest.approx(24.0, abs=0.2)


def test_analyse_16_bits_sans_echelle_connue():
    info = diag.analyser_image(np.full((60, 80), 8000, np.uint16))
    assert info["score"] == 2
    assert info["diviseur_kelvin"] is None


def test_analyse_gris_8_bits_et_couleur():
    assert diag.analyser_image(np.full((60, 80, 3), 90, np.uint8))["score"] == 1
    couleur = np.zeros((480, 640, 3), np.uint8)
    couleur[..., 2] = 200
    assert diag.analyser_image(couleur)["score"] == 0


class FausseCamera:
    """Une webcam à l'index 0, une thermique à l'index 3, lisible seulement en Y16."""

    def __init__(self, index):
        self.index, self.fourcc = index, None

    def isOpened(self):
        return self.index in (0, 3)

    def set(self, prop, valeur):
        if prop == diag.cv2.CAP_PROP_FOURCC:
            self.fourcc = valeur
        return True

    def get(self, prop):
        return {diag.cv2.CAP_PROP_FRAME_WIDTH: 160, diag.cv2.CAP_PROP_FRAME_HEIGHT: 120}.get(prop, 0)

    def read(self):
        if self.index == 0:
            f = np.zeros((480, 640, 3), np.uint8)
            f[..., 1] = 200
            return True, f
        if self.fourcc == diag.cv2.VideoWriter_fourcc(*"Y16 "):
            return True, image_16_bits()
        return True, np.full((120, 160, 3), 80, np.uint8)

    def release(self):
        pass


@pytest.fixture
def poste(monkeypatch, tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"thermique": {"delta_c": 2.5}, "alertes": {"actif": True}}),
                                          encoding="utf-8")
    (tmp_path / "config.local.json").write_text(json.dumps({"alertes": {"topic": "secret"}}), encoding="utf-8")
    monkeypatch.setattr(diag, "RACINE", tmp_path)
    monkeypatch.setattr(diag, "DOSSIER_BRUTES", tmp_path / "brutes")
    monkeypatch.setattr("care.cameras.cv2.VideoCapture", lambda index, backend: FausseCamera(index))
    return tmp_path


def lancer(argv, monkeypatch):
    monkeypatch.setattr("sys.argv", ["diagnostic", *argv])
    return diag.main()


def test_sonder_trouve_la_thermique_et_sa_resolution(poste, monkeypatch, capsys):
    assert lancer(["sonder"], monkeypatch) == 0
    sortie = capsys.readouterr().out
    assert "index 3, RÉSOLUTION 160x120" in sortie
    assert "températures lisibles" in sortie
    assert "secret" not in sortie


def test_sonder_sans_appliquer_ne_change_pas_la_config(poste, monkeypatch):
    lancer(["sonder"], monkeypatch)
    assert charger_config(str(poste)).get("camera_thermique") is None


def test_sonder_applique_sans_ecraser_le_topic(poste, monkeypatch):
    lancer(["sonder", "--appliquer"], monkeypatch)
    cfg = charger_config(str(poste))
    assert cfg["camera_thermique"] == {"index": 3, "active": True}
    assert cfg["thermique"]["flux"]["fourcc"] == "Y16 "
    assert cfg["thermique"]["diviseur_kelvin"] == 100
    assert cfg["thermique"]["delta_c"] == 2.5
    assert cfg["alertes"]["topic"] == "secret"


def test_sonder_sans_camera_le_dit_clairement(poste, monkeypatch, capsys):
    assert lancer(["sonder", "--index", "9"], monkeypatch) == 1
    assert "Aucune caméra" in capsys.readouterr().out


def test_zones_en_part_de_l_image():
    assert diag.en_fractions([(0, 0, 640, 96)], 640, 480) == [[0.0, 0.0, 1.0, 0.2]]


def test_config_locale_creee_si_absente(tmp_path):
    modifier_config_locale(str(tmp_path), {"thermique": {"methode": "reference"}})
    assert json.loads((tmp_path / "config.local.json").read_text(encoding="utf-8")) == {
        "thermique": {"methode": "reference"}}


def test_rejouer_donne_un_verdict_par_methode(poste, monkeypatch, capsys):
    from outils.simuler_thermique import encoder
    vide = np.full((60, 80), 22.0, np.float32)
    presence = vide.copy()
    presence[15:45, 25:55] = 33.0
    dossier = poste / "brutes"
    dossier.mkdir()
    np.save(dossier / "S7_vide.npy", np.stack([encoder(vide, "16bits")] * 3))
    np.save(dossier / "S1_poupee.npy", encoder(presence, "16bits"))  # une seule image, comme un essai du banc
    params = {"seuil_celsius": 30.0, "seuil_8bit": 200, "pixels_chauds_min": 20}

    assert diag.rejouer_fichier(dossier / "S7_vide.npy", params)["contraste"] is False
    l = diag.rejouer_fichier(dossier / "S1_poupee.npy", params)
    assert l["contraste"] is True and l["resolution"] == "80x60"
    l = diag.rejouer_fichier(dossier / "S1_poupee.npy", params, reference=vide)
    assert l["référence"] is True
