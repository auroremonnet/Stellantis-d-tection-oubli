"""Règle d'alerte unique (essai manuel et surveillance automatique)."""
from datetime import datetime

import pytest

from care.decision import accorder, decider

T = datetime(2026, 11, 1, 11, 42, 3)


def d(resultat, vide=True, **kw):
    return decider(resultat, habitacle_vide_attendu=vide, maintenant=T, **kw)


@pytest.mark.parametrize("vivant", ["enfant", "bébé", "chat", "chien"])
def test_vivant_a_proteger_toujours_critique(vivant):
    for vide in (True, False):
        a = d({"classes_vivant": [vivant], "objets": []}, vide=vide)
        assert a.niveau == "critique" and a.priorite == "urgent"


def test_personne_critique_seulement_si_habitacle_cense_vide():
    a = d({"classes_vivant": ["personne"], "objets": ["clés"]}, vide=True)
    assert a.niveau == "critique"
    assert a.message.startswith("Présence humaine détectée")  # jamais « Personne détectée »
    assert d({"classes_vivant": ["personne"], "objets": ["clés"]}, vide=False) is None


def test_thermique_seule_suffit_fusion_ou():
    a = d({"classes_vivant": [], "objets": [], "vivant_thermique": True})
    assert a.niveau == "critique" and "source de chaleur" in a.elements


def test_critique_prioritaire_sur_objet():
    a = d({"classes_vivant": ["bébé"], "objets": ["téléphone"]})
    assert a.niveau == "critique"


def test_objet_et_message_lisible():
    a = d({"classes_vivant": [], "objets": ["téléphone", "clés"]})
    assert a.niveau == "objet"
    assert a.message == "Téléphone et clés oubliés dans le véhicule à 11:42:03"


def test_filtre_des_objets_surveilles_et_objet_inconnu():
    r = {"classes_vivant": [], "objets": ["lunettes", "objet non identifié"]}
    assert d(r, objets_surveilles={"téléphone"}).elements == ("objet non identifié",)
    assert d(r, objets_surveilles={"téléphone"}, alerter_inconnu=False) is None
    assert d(r).elements == ("lunettes", "objet non identifié")


def test_accepte_les_chaines_du_journal_csv():
    a = d({"classes_vivant": "", "objets": "portefeuille, carte bancaire"})
    assert a.elements == ("portefeuille", "carte bancaire")


def test_rien_a_signaler():
    assert d({"classes_vivant": [], "objets": []}) is None


@pytest.mark.parametrize("noms, attendu", [
    (["téléphone"], "oublié"), (["valise"], "oubliée"), (["clés"], "oubliées"),
    (["téléphone", "portefeuille"], "oubliés"), (["clés", "carte bancaire"], "oubliées"),
    (["clés", "téléphone"], "oubliés"),
])
def test_accord(noms, attendu):
    assert accorder("oubli", noms) == attendu


def test_en_dict_serialisable():
    import json
    a = d({"classes_vivant": [], "objets": ["clés"]})
    assert json.loads(json.dumps(a.en_dict()))["elements"] == ["clés"]
