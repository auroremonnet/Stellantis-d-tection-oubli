"""Envoi ntfy : priorité, cooldown, rappels, robustesse réseau (requests simulé)."""
import numpy as np
import pytest

import care.alertes as mod
from care.alertes import Alerteur
from care.decision import Alerte


class FauxRequests:
    def __init__(self, echec=False):
        self.appels, self.echec = [], echec

    def put(self, url, data, params, timeout):
        if self.echec:
            raise ConnectionError("réseau coupé")
        self.appels.append({"url": url, "data": data, "params": params})

        class R:
            def raise_for_status(self):
                pass
        return R()


@pytest.fixture
def faux(monkeypatch):
    f = FauxRequests()
    monkeypatch.setattr(mod, "requests", f)
    return f


OBJET = Alerte("objet", "CARE · Objet oublié", "Clés oubliées", ("clés",))
CRITIQUE = Alerte("critique", "CARE · URGENT", "Bébé détecté", ("bébé",), priorite="urgent")


def test_envoi_avec_image_et_priorite(faux):
    a = Alerteur({"topic": "t-test"}, envoi_synchrone=True)
    assert a.notifier(CRITIQUE, np.zeros((40, 60, 3), np.uint8))
    p = faux.appels[0]
    assert p["url"] == "https://ntfy.sh/t-test"
    assert p["params"]["priority"] == "urgent" and p["params"]["filename"] == "detection.jpg"
    assert p["data"][:2] == b"\xff\xd8"  # JPEG


def test_cooldown_par_element(faux):
    a = Alerteur({"cooldown_s": 60}, envoi_synchrone=True)
    assert a.notifier(OBJET)
    assert not a.notifier(OBJET)                  # même objet, trop tôt
    assert a.notifier(OBJET, motif="rappel")      # l'escalade passe outre
    assert len(faux.appels) == 2
    assert faux.appels[1]["params"]["title"].startswith("RAPPEL")


def test_acquittement_sans_image_priorite_normale(faux):
    a = Alerteur({}, envoi_synchrone=True)
    a.notifier(CRITIQUE, np.zeros((10, 10, 3), np.uint8), motif="acquittement")
    p = faux.appels[0]["params"]
    assert p["priority"] == "default" and "filename" not in p and p["title"].startswith("Alerte levée")


def test_coupe(faux):
    assert not Alerteur({"actif": False}, envoi_synchrone=True).notifier(OBJET)
    assert faux.appels == []


def test_panne_reseau_ne_leve_pas(monkeypatch):
    monkeypatch.setattr(mod, "requests", FauxRequests(echec=True))
    a = Alerteur({}, envoi_synchrone=True)
    assert a.notifier(OBJET) is False
    assert "réseau coupé" in a.etat()["erreur"]


def test_compatible_test_alerte_py(faux):
    """test_alerte.py appelle encore envoyer(titre, message, image)."""
    a = Alerteur({"topic": "x"})
    assert a.envoyer("CARE · Test", "message", None)
    assert faux.appels[0]["params"]["priority"] == "high"
