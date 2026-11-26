"""Analyse du journal pour la vue Résultats."""
from care.analyse import alerte_emise, analyser, capteurs, lumiere, reussi, taux, vivant_detecte, wilson


def essai(verite, rgb=False, th=None, sons="", objets="", variante="Jour", audio="ok", alerte="", **k):
    return {"id": k.pop("id", "x"), "horodatage": k.pop("horodatage", "2026-11-25T10:00:00"),
            "scenario": k.pop("scenario", "S1"),
            "variante": variante, "verite": verite, "vivant_rgb": rgb, "vivant_thermique": th, "sons_audio": sons,
            "audio_statut": audio, "objets": objets, "alerte": alerte, "mode": k.pop("mode", "auto"), **k}


def critere(res, cle):
    return next(c for c in res["criteres"] if c["cle"] == cle)


def test_wilson_et_taux():
    assert wilson(0, 0) is None
    bas, haut = wilson(9, 10)
    assert 0.59 < bas < 0.61 and 0.98 < haut < 0.99          # 9/10 ne prouve pas 90 %
    assert wilson(10, 10)[1] == 1.0 and wilson(0, 10)[0] == 0.0
    assert taux(0, 0) == {"k": 0, "n": 0, "valeur": None, "bas": None, "haut": None}
    assert taux(3, 4)["valeur"] == 0.75


def test_lecture_des_lignes_du_csv_et_des_resultats_bruts():
    """Le journal relu donne des chaînes ; un résultat frais donne des booléens et des listes."""
    assert capteurs(essai("vivant", rgb="1", th="0", sons="pleurs")) == {"rgb": True, "thermique": False, "micro": True}
    assert capteurs(essai("vivant", rgb=True, th=True, sons=["aboiement"]))["micro"] is True
    sans = capteurs(essai("vivant", th="", audio="erreur", sons="pleurs"))
    assert sans == {"rgb": False, "thermique": None, "micro": None}
    assert lumiere(essai("vide", variante="Nuit / faible lumière")) == "nuit" and lumiere(essai("vide")) == "jour"


def test_approches_et_capteur_manquant():
    l = essai("vivant", rgb=False, th=True, sons="")
    assert vivant_detecte(l, "A1") is False and vivant_detecte(l, "A2") is True and vivant_detecte(l, "A3") is True
    sans_th = essai("vivant", rgb=True, th=None)
    assert vivant_detecte(sans_th, "A1") is True and vivant_detecte(sans_th, "A2") is None
    sans_micro = essai("vivant", rgb=False, th=False, audio="erreur")
    assert vivant_detecte(sans_micro, "A2") is False and vivant_detecte(sans_micro, "A3") is None


def test_reussite_selon_la_verite_terrain():
    assert reussi(essai("vivant", th=True)) and not reussi(essai("vivant", th=False))
    assert reussi(essai("vivant", th=False, sons="pleurs"))                       # le micro seul suffit
    assert reussi(essai("objet", objets="clés")) and not reussi(essai("objet"))
    assert reussi(essai("vide", th=False)) and not reussi(essai("vide", objets="téléphone"))
    assert not reussi(essai("vide", th=True)) and alerte_emise(essai("vide", alerte="objet"))


def test_criteres_sur_un_journal_type():
    lignes = ([essai("vivant", rgb=True, th=True)] * 6 + [essai("vivant", rgb=False, th=True)] * 3
              + [essai("vivant", rgb=False, th=False)]
              + [essai("objet", objets="clés, téléphone", scenario="S5")] * 4 + [essai("objet", scenario="S5")]
              + [essai("vide", th=False, scenario="S7")] * 9 + [essai("vide", th=True, scenario="S7")]
              + [essai("vide", th=False, scenario="S7", latence_alerte_s="9.5"),
                 essai("vivant", rgb=True, th=True, latence_alerte_s="16.2")])
    res = analyser(lignes, [{"code": "S1", "nom": "Enfant", "verite": "vivant"}], 10)
    p = critere(res, "presence")
    assert (p["k"], p["n"], p["atteint"]) == (10, 11, True) and p["bas"] < 0.9 < p["haut"]
    t = critere(res, "thermique")
    assert (t["k"], t["n"], t["atteint"]) == (3, 4, True)        # 3 présences sur 4 rattrapées
    o = critere(res, "objet")
    assert (o["k"], o["n"], o["atteint"]) == (4, 5, True)
    f = critere(res, "fausses")
    assert (f["k"], f["n"], f["atteint"]) == (1, 11, True)
    d = critere(res, "delai")
    assert d["n"] == 2 and d["pire"] == 16.2 and d["atteint"] is False     # c'est le pire cas qui compte
    a1, a2, a3 = res["approches"]
    assert a1["rappel"]["k"] == 7 and a2["rappel"]["k"] == 10 and a3["rappel"]["n"] == 11
    assert res["capteurs"]["thermique"]["seul_a_detecter"] == 3
    assert res["capteurs"]["rgb"]["objets_nommes"][0] == {"libelle": "clés", "essais": 4}
    assert res["nb_echecs"] == 3 and len(res["echecs"]) == 3
    sc = {s["code"]: s for s in res["par_scenario"]}
    assert sc["S1"]["nom"] == "Enfant" and sc["S5"]["n"] == 5 and sc["S7"]["k"] == 10


def test_journal_vide_et_criteres_sans_donnees():
    res = analyser([], [{"code": "S1", "nom": "Enfant", "verite": "vivant"}])
    assert res["essais"] == 0 and all(c["atteint"] is None for c in res["criteres"])
    assert res["par_scenario"][0]["n"] == 0 and res["echecs"] == [] and res["provenance"]["du"] is None
    # sans thermique, ou si les caméras n'ont rien raté, l'apport de la thermique ne se juge pas
    assert critere(analyser([essai("vivant", rgb=True, th=None)]), "thermique")["atteint"] is None
    assert critere(analyser([essai("vivant", rgb=True, th=True)]), "thermique")["atteint"] is None


def test_jour_et_nuit_separes_et_echecs_expliques():
    lignes = [essai("objet", objets="clés", scenario="S5"),
              essai("objet", scenario="S5", variante="Nuit / faible lumière", id="n1", horodatage="2026-11-25T21:00:00",
                    commentaire="plafonnier éteint")]
    res = analyser(lignes)
    jour, nuit = res["par_lumiere"]
    assert (jour["essais"], nuit["essais"]) == (1, 1) and res["provenance"]["nuit"] == 1
    assert critere(jour, "objet")["valeur"] == 1.0 and critere(nuit, "objet")["valeur"] == 0.0
    e = res["echecs"][0]
    assert e["id"] == "n1" and e["attendu"] == "objet de valeur signalé" and e["obtenu"] == "rien à signaler"
    assert e["commentaire"] == "plafonnier éteint"
    assert res["par_scenario"][0]["nuit"]["n"] == 1
    assert analyser(lignes, objectifs={"rappel_objet": 0.4})["criteres"][2]["atteint"] is True


def test_essais_rejoues_comptes_a_part():
    lignes = [essai("vivant", rgb=True, mode="rejeu", audio="desactive"),
              essai("vivant", rgb=True, th=True, mode="manuel")]
    p = analyser(lignes)["provenance"]
    assert (p["rejoues"], p["manuels"], p["automatiques"]) == (1, 1, 0)
    # un rejeu sans thermique ne compte ni pour ni contre la thermique
    assert analyser(lignes)["approches"][1]["rappel"]["n"] == 1


def test_modele_de_simulation_par_scenario():
    from care.simulation import Quotas, lumiere, simuler
    q = Quotas()
    assert simuler(q, "S9", "Jour") is None and lumiere("Nuit / faible lumière") == "nuit"
    s2 = [simuler(q, "S2", "Jour") for _ in range(8)]
    assert not any(r["vivant_rgb"] for r in s2)                       # enfant caché : les caméras ne voient rien
    assert all(r["vivant_thermique"] or r["son"] for r in s2)         # thermique ou micro le trouvent
    assert all(simuler(q, "S3", "Jour")["vivant_thermique"] is None for _ in range(3))   # pas de thermique
    jour = sum(bool(simuler(q, "S5", "Jour")["objets"]) for _ in range(31))
    nuit = sum(bool(simuler(q, "S5", "Nuit / faible lumière")["objets"]) for _ in range(6))
    assert jour == 29 and nuit == 1                                    # proportions exactes, sans hasard
