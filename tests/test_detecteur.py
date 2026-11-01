"""Fonctions pures du détecteur : fusion des moteurs et gabarit adulte."""
from care.detecteur import LIBELLES, est_adulte, fusionner


def det(nom, conf, boite, type_="valeur", source="yoloe"):
    return {"nom": nom, "type": type_, "conf": conf, "boite": boite, "source": source}


def lib(n):
    return LIBELLES.get(n, n)


def test_fusion_doublon_entre_moteurs_garde_le_modele_entraine():
    yoloe = det("credit card", 0.31, [100, 100, 200, 160])
    custom = det("card", 0.82, [104, 98, 205, 158], source="custom")
    assert fusionner([yoloe, custom], lib) == [custom]
    # même si YOLOE est plus « confiant » : les scores de deux modèles ne se comparent pas
    yoloe_sur = det("credit card", 0.95, [100, 100, 200, 160])
    assert fusionner([yoloe_sur, custom], lib) == [custom]


def test_fusion_yoloe_garde_ce_que_le_modele_entraine_ne_voit_pas():
    yoloe = det("keys", 0.5, [0, 0, 40, 40])
    custom = det("keys", 0.8, [300, 300, 340, 340], source="custom")
    assert len(fusionner([yoloe, custom], lib)) == 2


def test_fusion_garde_deux_objets_distincts():
    a = det("keys", 0.6, [0, 0, 50, 50])
    b = det("keys", 0.5, [300, 300, 350, 350])
    assert len(fusionner([a, b], lib)) == 2


def test_fusion_ne_melange_pas_deux_classes_au_meme_endroit():
    tel = det("cell phone", 0.7, [0, 0, 100, 100])
    port = det("wallet", 0.6, [0, 0, 100, 100])
    assert len(fusionner([tel, port], lib)) == 2


def test_bebe_yoloe_et_bebe_custom_fusionnes():
    a = det("baby", 0.4, [10, 10, 110, 150], "vivant")
    b = det("baby", 0.9, [12, 8, 108, 152], "vivant", source="custom")
    assert fusionner([a, b], lib) == [b]


def test_fusion_ne_touche_jamais_deux_detections_du_meme_moteur():
    """Régression : deux personnes côte à côte (IoU 0,55) vues par le même moteur."""
    p1 = det("person", 0.68, [0, 0, 100, 200], "vivant", source="custom")
    p2 = det("person", 0.42, [30, 0, 130, 200], "vivant", source="custom")
    assert len(fusionner([p1, p2], lib)) == 2


def test_adulte_selon_la_hauteur_de_boite():
    h = 720
    assert est_adulte(det("person", 0.9, [0, 100, 300, 600], "vivant"), h)       # 500 px ≥ 35 %
    assert not est_adulte(det("person", 0.9, [0, 400, 100, 560], "vivant"), h)   # enfant au loin
    assert not est_adulte(det("child", 0.9, [0, 0, 300, 700], "vivant"), h)      # jamais « child »
    assert not est_adulte(det("person", 0.9, [0, 0, 300, 700], "valeur"), h)
