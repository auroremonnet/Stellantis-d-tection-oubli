"""Relecture du journal d'événements (`evenements.jsonl`), derrière GET /api/evenements.

La logique est dans care/stockage.py et non dans app.py : app.py analyse sys.argv et ouvre
les caméras dès l'import, il n'est donc pas importable sous pytest.
"""
import json

import pytest

from care.stockage import derniers_evenements


def ecrire(chemin, evts):
    with open(chemin, "w", encoding="utf-8") as fh:
        for e in evts:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")
    return str(chemin)


@pytest.fixture
def journal(tmp_path):
    return tmp_path / "evenements.jsonl"


def evt(i, type_="veille"):
    return {"t": 1000.0 + i, "heure": f"11:39:{i:02d}", "type": type_,
            "detail": f"événement {i}", "source": "surveillance"}


def test_fichier_absent_renvoie_une_liste_vide(journal):
    assert derniers_evenements(str(journal)) == []


def test_les_n_derniers_du_plus_ancien_au_plus_recent(journal):
    ecrire(journal, [evt(i) for i in range(10)])
    out = derniers_evenements(str(journal), 3)
    assert [e["detail"] for e in out] == ["événement 7", "événement 8", "événement 9"]


def test_moins_d_evenements_que_demande(journal):
    ecrire(journal, [evt(0), evt(1, "alerte")])
    out = derniers_evenements(str(journal), 20)
    assert len(out) == 2 and out[1]["type"] == "alerte"


def test_n_nul_ou_negatif(journal):
    ecrire(journal, [evt(0)])
    assert derniers_evenements(str(journal), 0) == []
    assert derniers_evenements(str(journal), -5) == []


def test_ligne_illisible_ignoree(journal):
    """Écriture interrompue en plein milieu : la page de suivi doit continuer à s'afficher."""
    ecrire(journal, [evt(0)])
    with open(journal, "a", encoding="utf-8") as fh:
        fh.write('{"t": 1001.0, "type": "alert\n')      # ligne tronquée
        fh.write(json.dumps(evt(2, "alerte")) + "\n")
    out = derniers_evenements(str(journal), 10)
    assert [e["type"] for e in out] == ["veille", "alerte"]


def test_journal_volumineux_lu_par_la_fin(journal):
    """On ne lit que la fin du fichier : la première ligne du bloc peut être coupée."""
    ecrire(journal, [evt(i) for i in range(2000)])
    assert journal.stat().st_size > 4096
    out = derniers_evenements(str(journal), 5, taille_max=4096)
    assert [e["detail"] for e in out] == [f"événement {i}" for i in range(1995, 2000)]
    # aucune ligne tronquée n'est remontée
    assert all("type" in e and "heure" in e for e in out)


def test_une_seule_ligne_plus_longue_que_la_fenetre(journal):
    """Cas limite : le bloc lu ne contient aucun saut de ligne complet."""
    ecrire(journal, [{"type": "alerte", "detail": "x" * 5000}])
    assert derniers_evenements(str(journal), 5, taille_max=256) == []


def test_lignes_vides_ignorees(journal):
    ecrire(journal, [evt(0)])
    with open(journal, "a", encoding="utf-8") as fh:
        fh.write("\n\n")
    assert len(derniers_evenements(str(journal), 10)) == 1
