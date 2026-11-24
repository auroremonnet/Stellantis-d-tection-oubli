"""Règles « localiser → nommer → trancher » : fonctions pures, sans modèle."""
from care.detection.catalogue import FOND, Catalogue
from care.detection.identification import (
    ENTRAINE,
    YOLOE,
    ZONE,
    Candidat,
    Detection,
    Regles,
    dedoublonner,
    preparer_candidats,
    suivre,
    trancher,
    voter,
)

CAT, R = Catalogue(), Regles()
FORME = (480, 640, 3)


def p(**kw):
    """Probabilités du classifieur : ce qui n'est pas nommé va au fond."""
    return {**kw, FOND: max(0.0, 1.0 - sum(kw.values()))} if FOND not in kw else kw


def un(candidat, probas):
    dets, inconnues = trancher([candidat], [probas], CAT, R)
    return (dets[0] if dets else None), inconnues


def test_le_classifieur_sur_de_lui_nomme_l_objet_quel_que_soit_l_avis_du_detecteur():
    """Cas réel : YOLOE voyait un « portefeuille » là où il y a un téléphone posé de dos."""
    d, _ = un(Candidat([10, 10, 110, 60], YOLOE, 0.68, "portefeuille"), p(téléphone=0.98))
    assert d.cle == "téléphone" and d.categorie == "valeur" and not d.accord


def test_boucle_de_ceinture_prise_pour_des_cles_ecartee():
    d, inconnues = un(Candidat([10, 10, 40, 40], YOLOE, 0.56, "clés"), p(clés=0.05))
    assert d is None and inconnues == []


def test_accord_de_deux_modeles_abaisse_le_seuil():
    """Carte à moitié cachée : classifieur hésitant (0,31) mais modèle entraîné d'accord."""
    d, _ = un(Candidat([0, 0, 60, 40], ENTRAINE, 0.63, "carte bancaire"), p(**{"carte bancaire": 0.31}))
    assert d.cle == "carte bancaire" and d.accord
    assert un(Candidat([0, 0, 60, 40], YOLOE, 0.63, "clés"), p(**{"carte bancaire": 0.31}))[0] is None  # pas d'accord
    faible = Candidat([0, 0, 60, 40], YOLOE, 0.05, "carte bancaire")                  # indice trop peu confiant
    assert un(faible, p(**{"carte bancaire": 0.31}))[0] is None


def test_objet_en_tete_mais_sous_le_seuil_non_retenu():
    assert un(Candidat([0, 0, 60, 40], YOLOE, 0.04, None), {"téléphone": 0.45, "clés": 0.15, FOND: 0.40})[0] is None


def test_etre_vivant_jamais_annonce_par_le_classifieur_seul():
    probas = p(bébé=0.9)
    assert un(Candidat([0, 0, 200, 200], YOLOE, 0.2, "sac à dos"), probas)[0] is None
    assert un(Candidat([0, 0, 200, 200], ZONE), probas)[0] is None
    d, _ = un(Candidat([0, 0, 200, 200], YOLOE, 0.2, "enfant"), probas)     # le détecteur voyait aussi un vivant
    assert d.cle == "bébé" and d.categorie == "vivant"


def test_zone_nouvelle_non_reconnue_signalee_sauf_si_c_est_du_decor():
    zone = Candidat([100, 100, 180, 160], ZONE)
    assert un(zone, {"téléphone": 0.3, "clés": 0.3, FOND: 0.4})[1] == [zone.boite]   # ni nommée, ni décor
    assert un(zone, p(clés=0.05))[1] == []                                            # câble, ombre…
    d, inconnues = un(zone, p(lunettes=0.9))
    assert d.cle == "lunettes" and inconnues == []


def test_zone_inconnue_deja_expliquee_par_un_objet_ignoree():
    tel = Candidat([100, 100, 200, 160], YOLOE, 0.3, "téléphone")
    zone = Candidat([110, 105, 190, 150], ZONE)
    dets, inconnues = trancher([tel, zone], [p(téléphone=0.95), {"téléphone": 0.4, FOND: 0.3, "clés": 0.3}], CAT, R)
    assert [d.cle for d in dets] == ["téléphone"] and inconnues == []


def det(cle, conf, boite):
    return Detection(cle, "valeur", conf, boite)


def test_regression_objectifs_du_telephone_pris_pour_un_casque_audio():
    """Une petite boîte à l'intérieur d'un objet plus grand en est un morceau."""
    tel, lentilles = det("téléphone", 0.99, [100, 100, 220, 300]), det("casque audio", 0.91, [110, 110, 150, 150])
    assert dedoublonner([tel, lentilles]) == [tel]


def test_deux_boites_du_meme_objet_n_en_font_qu_un():
    a, b = det("clés", 0.9, [0, 0, 60, 40]), det("clés", 0.7, [10, 5, 70, 45])
    assert dedoublonner([a, b]) == [a]
    assert len(dedoublonner([a, det("clés", 0.7, [300, 300, 360, 340])])) == 2      # deux trousseaux
    voisins = [det("téléphone", 0.9, [0, 0, 100, 100]), det("portefeuille", 0.8, [25, 0, 125, 100])]
    assert len(dedoublonner(voisins)) == 2


def test_candidats_absurdes_ecartes_et_doublons_fusionnes():
    cands = [Candidat([0, 0, 640, 470], YOLOE, 0.9, "sac à dos"),          # toute l'image
             Candidat([0, 0, 300, 200], YOLOE, 0.05, "sac à dos"),         # grand et peu confiant
             Candidat([5, 5, 9, 9], YOLOE, 0.9, "clés"),                   # minuscule
             Candidat([100, 100, 160, 140], YOLOE, 0.4, "portefeuille"),
             Candidat([102, 101, 161, 142], ENTRAINE, 0.3, "carte bancaire")]
    gardes = preparer_candidats(cands, FORME, R)
    assert [(c.source, c.cle) for c in gardes] == [(ENTRAINE, "carte bancaire")]   # le modèle entraîné prime


def test_plafond_de_candidats():
    cands = [Candidat([i * 40, 0, i * 40 + 30, 30], YOLOE, 0.1 + i / 100, None) for i in range(15)]
    assert len(preparer_candidats(cands, FORME, Regles(candidats_max=6))) == 6


def test_suivi_ecarte_ce_qui_n_apparait_que_sur_une_image():
    stable = lambda: Candidat([10, 10, 60, 60], YOLOE, 0.3, "clés")  # noqa: E731
    reflet = Candidat([300, 300, 340, 340], YOLOE, 0.3, "montre")
    suivis = suivre([[stable()], [stable()], [stable(), reflet]], ratio=0.5)
    assert [c.cle for c in suivis] == ["clés"] and suivis[0].vues == 3


def test_vote_des_vivants_par_classe_et_non_par_boite():
    """Un enfant qui bouge change de boîte d'une image à l'autre : il reste présent."""
    obs = [[Candidat([0, 0, 100, 200], YOLOE, 0.6, "enfant")], [Candidat([200, 0, 300, 200], YOLOE, 0.7, "enfant")], []]
    assert [c.boite for c in voter(obs, 0.5)] == [[200, 0, 300, 200]]
    assert voter([[Candidat([0, 0, 9, 9], YOLOE, 0.6, "chat")], [], []], 0.5) == []
    assert voter([], 0.5) == [] and suivre([], 0.5) == []


def test_catalogue_surcharge_par_la_config():
    cat = Catalogue.depuis_config({"catalogue": {
        "parapluie": {"mots": ["umbrella"], "descriptions": ["an umbrella"]}, "montre": None}})
    assert cat.cle_du_mot("umbrella") == "parapluie" and cat.categorie("parapluie") == "valeur"
    assert "montre" not in cat.classes and "watch" not in cat.mots()
    assert cat.cle_du_mot("seat belt buckle") is None                      # décor
    assert cat.cle_entrainee("card") == "carte bancaire" and cat.cle_entrainee("inconnue") is None
    cles = [c for c, _ in cat.descriptions()]
    assert cles[-1] == FOND and "parapluie" in cles
