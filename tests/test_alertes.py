"""Envoi ntfy : priorité, cooldown, rappels, bouton d'acquittement, lien de suivi,
robustesse réseau (requests simulé)."""
import numpy as np
import pytest

import care.alertes as mod
from care.alertes import Alerteur
from care.decision import Alerte


class FauxRequests:
    def __init__(self, echec=False):
        self.appels, self.echec = [], echec

    def put(self, url, data, params, timeout, headers=None):
        if self.echec:
            raise ConnectionError("réseau coupé")
        self.appels.append({"url": url, "data": data, "params": params, "headers": headers})

        class R:
            def raise_for_status(self):
                pass
        return R()


@pytest.fixture
def faux(monkeypatch):
    f = FauxRequests()
    monkeypatch.setattr(mod, "requests", f)
    return f


def alerteur(**cfg) -> Alerteur:
    """Alerteur synchrone sur un topic configuré (le topic par défaut est volontairement
    refusé par le garde-fou : voir test_topic_non_configure_ne_part_pas)."""
    return Alerteur({"topic": "t-test", **cfg}, envoi_synchrone=True)


OBJET = Alerte("objet", "CARE · Objet oublié", "Clés oubliées", ("clés",))
CRITIQUE = Alerte("critique", "CARE · URGENT", "Bébé détecté", ("bébé",), priorite="urgent")


def test_envoi_avec_image_et_priorite(faux):
    a = alerteur()
    assert a.notifier(CRITIQUE, np.zeros((40, 60, 3), np.uint8))
    p = faux.appels[0]
    assert p["url"] == "https://ntfy.sh/t-test"
    assert p["params"]["priority"] == "urgent" and p["params"]["filename"] == "detection.jpg"
    assert p["data"][:2] == b"\xff\xd8"  # JPEG


def test_cooldown_par_element(faux):
    a = alerteur(cooldown_s=60)
    assert a.notifier(OBJET)
    assert not a.notifier(OBJET)                  # même objet, trop tôt
    assert a.notifier(OBJET, motif="rappel")      # l'escalade passe outre
    assert len(faux.appels) == 2
    assert faux.appels[1]["params"]["title"].startswith("RAPPEL")


def test_acquittement_sans_image_priorite_normale(faux):
    a = alerteur()
    a.notifier(CRITIQUE, np.zeros((10, 10, 3), np.uint8), motif="acquittement")
    p = faux.appels[0]["params"]
    assert p["priority"] == "default" and "filename" not in p and p["title"].startswith("Alerte levée")


def test_coupe(faux):
    assert not alerteur(actif=False).notifier(OBJET)
    assert faux.appels == []


def test_panne_reseau_ne_leve_pas(monkeypatch):
    monkeypatch.setattr(mod, "requests", FauxRequests(echec=True))
    a = alerteur()
    assert a.notifier(OBJET) is False
    assert "réseau coupé" in a.etat()["erreur"]


def test_compatible_test_alerte_py(faux):
    """test_alerte.py appelle encore envoyer(titre, message, image)."""
    a = Alerteur({"topic": "x"})
    assert a.envoyer("CARE · Test", "message", None)
    assert faux.appels[0]["params"]["priority"] == "high"


def test_regression_critique_jamais_bloque_par_le_cooldown(faux):
    """Une alerte critique levée à tort (ex. enfant pris pour le conducteur) puis
    redéclenchée doit repartir immédiatement."""
    a = alerteur(cooldown_s=60)
    assert a.notifier(CRITIQUE)
    assert a.notifier(CRITIQUE, motif="acquittement")
    assert a.notifier(CRITIQUE)
    assert a.notifier(CRITIQUE)                    # même sans acquittement


def test_acquittement_rearme_le_cooldown_des_objets(faux):
    a = alerteur(cooldown_s=60)
    assert a.notifier(OBJET)
    a.notifier(OBJET, motif="acquittement")
    assert a.notifier(OBJET)                       # nouveau cycle : l'objet peut réalerter


def test_topic_non_configure_ne_part_pas(faux):
    """Dépôt public : tant que le topic de config.json n'est pas remplacé (config.local.json
    ou CARE_NTFY_TOPIC), aucune notification ne doit partir."""
    a = Alerteur({}, envoi_synchrone=True)          # topic par défaut : « CHANGEMOI-... »
    assert a.notifier(CRITIQUE) is False
    assert a.envoyer("CARE · Test", "message") is False   # appel direct (test_alerte.py)
    assert faux.appels == []
    assert "CARE_NTFY_TOPIC" in a.etat()["erreur"] and "config.local.json" in a.etat()["erreur"]


# ---- bouton « Je m'en occupe » (action ntfy http) --------------------------------
BOUTON = ("http, Je m'en occupe, http://banc.lan:5000/api/surveillance/acquitter, "
          "method=POST, clear=true")


def _entetes(faux, i=0):
    return faux.appels[i]["headers"] or {}


def test_bouton_sur_l_alerte_critique_et_sur_le_rappel(faux):
    a = alerteur(url_banc="http://banc.lan:5000/")      # « / » final toléré
    assert a.notifier(CRITIQUE)
    assert _entetes(faux)["Actions"] == BOUTON
    assert a.notifier(CRITIQUE, motif="rappel")
    assert _entetes(faux, 1)["Actions"] == BOUTON


def test_bouton_absent_sans_url_banc(faux):
    a = alerteur()
    assert a.notifier(CRITIQUE)
    assert "Actions" not in _entetes(faux)


def test_pas_de_bouton_sur_une_alerte_objet_ni_sur_un_acquittement(faux):
    a = alerteur(url_banc="http://banc.lan:5000")
    assert a.notifier(OBJET)                                   # objet : rien à prendre en charge
    assert "Actions" not in _entetes(faux)
    assert a.notifier(CRITIQUE, motif="acquittement")          # déjà levée
    assert "Actions" not in _entetes(faux, 1)


def test_bouton_envoye_en_ascii(faux):
    """Le bouton part dans un en-tête HTTP : un accent le casserait (d'où le libellé ASCII)."""
    a = alerteur(url_banc="http://banc.lan:5000")
    a.notifier(CRITIQUE, motif="rappel")
    _entetes(faux)["Actions"].encode("ascii")


def test_acquittement_a_distance_titre_et_message(faux):
    a = alerteur(url_banc="http://banc.lan:5000")
    assert a.notifier(CRITIQUE, np.zeros((10, 10, 3), np.uint8), motif="acquittement_distant")
    p = faux.appels[0]["params"]
    assert p["title"] == "Alerte levée · pris en charge à distance"
    assert "rappels sont arrêtés" in p["message"]
    assert p["priority"] == "default" and "filename" not in p   # pas d'image
    assert "Actions" not in _entetes(faux)


def test_acquittement_a_distance_rearme_le_cooldown(faux):
    a = alerteur(cooldown_s=60)
    assert a.notifier(OBJET)
    a.notifier(OBJET, motif="acquittement_distant")
    assert a.notifier(OBJET)                                   # nouveau cycle possible


# ---- lien vers la page de suivi (en-tête ntfy « Click ») -------------------------
def test_clic_ouvre_la_page_de_suivi(faux):
    """Toucher la notification ouvre /suivi : l'état du banc et le bouton d'acquittement."""
    a = alerteur(url_banc="http://banc.lan:5000/")
    assert a.lien_suivi == "http://banc.lan:5000/suivi"
    for i, motif in enumerate(("alerte", "rappel", "acquittement_distant")):
        assert a.notifier(CRITIQUE, motif=motif)
        assert _entetes(faux, i)["Click"] == "http://banc.lan:5000/suivi"


def test_pas_de_clic_sans_url_banc(faux):
    a = alerteur()
    assert a.lien_suivi == ""
    assert a.notifier(CRITIQUE)
    assert "Click" not in _entetes(faux)
    assert faux.appels[0]["headers"] is None      # aucun en-tête inutile


def test_clic_et_bouton_cohabitent(faux):
    a = alerteur(url_banc="http://banc.lan:5000")
    a.notifier(CRITIQUE)
    h = _entetes(faux)
    assert h["Actions"] == BOUTON and h["Click"] == "http://banc.lan:5000/suivi"
