"""Machine à états de la surveillance : horloge simulée, aucune caméra."""
import threading
import time

import pytest

from care.decision import Alerte
from care.surveillance import Action, Branchements, Etat, MachineOubli, Parametres, Superviseur


class Horloge:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def avancer(self, s):
        self.t += s


@pytest.fixture
def h():
    return Horloge()


@pytest.fixture
def m(h):
    machine = MachineOubli(Parametres(confirmation_presence_s=1.5, delai_sortie_s=8), horloge=h, horloge_mur=h)
    machine.armer()
    return machine


def observer_pendant(m, h, present, duree, pas=0.5):
    actions = []
    for _ in range(int(duree / pas)):
        h.avancer(pas)
        actions += m.observer(present)
    return actions


def monter(m, h):
    observer_pendant(m, h, True, 2.0)
    assert m.etat is Etat.OCCUPE


# ---- cycle nominal --------------------------------------------------------------
def test_inactif_tant_que_non_armee(h):
    m = MachineOubli(horloge=h, horloge_mur=h)
    assert m.etat is Etat.INACTIF
    assert m.observer(True) == [] and m.etat is Etat.INACTIF


def test_cycle_complet_avec_oubli(m, h):
    monter(m, h)
    assert observer_pendant(m, h, False, 7.5) == []          # compte à rebours en cours
    assert m.etat is Etat.SORTIE
    assert observer_pendant(m, h, False, 1.0) == [Action.ANALYSER]
    assert m.etat is Etat.ANALYSE
    h.avancer(3.0)                                            # durée de l'analyse
    m.conclure_analyse("objet", "clés")
    assert m.etat is Etat.ALERTE
    # départ = dernier instant où l'adulte était vu (t+2 s) ; analyse lancée à t+10 s,
    # l'horloge avance encore d'un pas (t+10,5 s), puis 3 s d'analyse : verdict à t+13,5 s
    assert m.derniere_latence_s == pytest.approx(11.5)


def test_rien_a_signaler_revient_en_veille(m, h):
    monter(m, h)
    observer_pendant(m, h, False, 9)
    m.conclure_analyse(None)
    assert m.etat is Etat.VEILLE
    monter(m, h)                                              # nouveau cycle possible


def test_presence_breve_ne_declare_pas_occupe(m, h):
    """Un faux positif isolé (reflet, veste) ne doit pas faire croire à un occupant."""
    observer_pendant(m, h, True, 1.0)
    observer_pendant(m, h, False, 0.5)
    observer_pendant(m, h, True, 1.0)
    assert m.etat is Etat.VEILLE


def test_retour_avant_fin_du_compte_a_rebours(m, h):
    monter(m, h)
    observer_pendant(m, h, False, 5)
    assert m.compte_a_rebours() == pytest.approx(3.0)
    observer_pendant(m, h, True, 0.5)
    assert m.etat is Etat.OCCUPE
    assert observer_pendant(m, h, False, 7.5) == []           # le délai repart de zéro


def test_verrouillage_declenche_l_analyse_immediatement(m, h):
    monter(m, h)
    assert m.verrouiller() == [Action.ANALYSER]
    assert m.etat is Etat.ANALYSE


def test_verrouillage_ignore_si_desarme(h):
    m = MachineOubli(horloge=h, horloge_mur=h)
    assert m.verrouiller() == [] and m.etat is Etat.INACTIF


def test_conclure_hors_analyse_est_sans_effet(m):
    m.conclure_analyse("critique")
    assert m.etat is Etat.VEILLE


# ---- alerte, acquittement, escalade (Euro NCAP) ---------------------------------
def _alerte(m, h, niveau):
    monter(m, h)
    m.verrouiller()
    m.conclure_analyse(niveau)
    assert m.etat is Etat.ALERTE


def test_retour_du_conducteur_leve_l_alerte(m, h):
    _alerte(m, h, "critique")
    assert observer_pendant(m, h, True, 2.0) == [Action.ACQUITTER]
    assert m.etat is Etat.OCCUPE and m.niveau_alerte is None


def test_escalade_critique_90s_puis_chaque_minute(m, h):
    _alerte(m, h, "critique")
    assert observer_pendant(m, h, False, 89) == []
    assert observer_pendant(m, h, False, 1.5) == [Action.RAPPELER]
    assert observer_pendant(m, h, False, 59) == []
    assert observer_pendant(m, h, False, 1.5) == [Action.RAPPELER]
    assert m.rappels == 2


def test_escalade_s_arrete_apres_20_minutes(m, h):
    _alerte(m, h, "critique")
    actions = observer_pendant(m, h, False, 1300, pas=1.0)
    # rappels à 90 s, 150 s, … tant que l'on reste sous 1200 s → 19 rappels
    assert actions.count(Action.RAPPELER) == 19


def test_pas_d_escalade_pour_un_objet(m, h):
    _alerte(m, h, "objet")
    assert observer_pendant(m, h, False, 300, pas=1.0) == []


def test_historique_et_instantane(m, h):
    monter(m, h)
    snap = m.instantane()
    assert snap["etat"] == "occupe"
    assert [e["type"] for e in snap["historique"]][:2] == ["occupe", "veille"]  # plus récent d'abord


def test_parametres_depuis_config_ignore_les_cles_inconnues():
    p = Parametres.depuis_config({"delai_sortie_s": 3, "periode_s": 0.2, "niveaux_escalade": ["critique", "objet"]})
    assert p.delai_sortie_s == 3 and p.niveaux_escalade == ("critique", "objet")


def test_evenements_depuis_reste_juste_quand_l_historique_deborde(h):
    m = MachineOubli(horloge=h, horloge_mur=h, taille_historique=3)
    for _ in range(5):
        m.armer()
    assert m.nb_evenements == 5
    assert len(m.evenements_depuis(3)) == 2
    assert len(m.evenements_depuis(0)) == 3  # borné par l'historique


# ---- superviseur (thread) -----------------------------------------------------
def _attendre(condition, delai=5.0):
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        if condition():
            return True
        time.sleep(0.01)
    return False


def test_superviseur_bout_en_bout():
    scene = {"adulte": False}
    notifs, enregistres, journal = [], [], []
    alerte = Alerte("objet", "titre", "msg", ("clés",))
    b = Branchements(
        presence_adulte=lambda: scene["adulte"],
        analyser=lambda ctx: {"objets": ["clés"], "images_rgb": ["<image>"], "_brutes": {}},
        decider=lambda r: alerte if r["objets"] else None,
        notifier=lambda a, r, motif: notifs.append(motif),
        enregistrer=lambda r, ctx: enregistres.append((r, ctx)),
        journaliser=journal.append,
    )
    sup = Superviseur(MachineOubli(Parametres(confirmation_presence_s=0.05, delai_sortie_s=0.1)),
                      b, periode_s=0.01)
    sup.armer({"scenario": "S5", "verite": "objet"})
    try:
        scene["adulte"] = True
        assert _attendre(lambda: sup.machine.etat is Etat.OCCUPE)
        scene["adulte"] = False
        assert _attendre(lambda: sup.machine.etat is Etat.ALERTE)
        assert notifs == ["alerte"]
        assert enregistres[0][1]["scenario"] == "S5"
        snap = sup.instantane()
        assert snap["dernier_resultat"]["alerte"]["elements"] == ["clés"]
        assert "images_rgb" not in snap["dernier_resultat"] and "_brutes" not in snap["dernier_resultat"]
        scene["adulte"] = True
        assert _attendre(lambda: sup.machine.etat is Etat.OCCUPE)
        assert notifs == ["alerte", "acquittement"]
        types = [e.type for e in journal]
        assert types[:4] == ["veille", "occupe", "sortie", "analyse"]
        assert len(types) == len(set(map(id, journal)))  # chaque événement journalisé une seule fois
    finally:
        sup.desarmer()
    assert sup.machine.etat is Etat.INACTIF and not sup.actif


def test_verrouillage_execute_par_le_thread_de_surveillance():
    threads = []

    def analyser(ctx):
        threads.append(threading.current_thread().name)
        return {"objets": []}

    b = Branchements(presence_adulte=lambda: False, analyser=analyser, decider=lambda r: None)
    sup = Superviseur(MachineOubli(), b, periode_s=0.01)
    sup.armer()
    try:
        sup.verrouiller()
        assert _attendre(lambda: threads)
        assert threads == ["surveillance"]
        assert _attendre(lambda: sup.machine.etat is Etat.VEILLE)
    finally:
        sup.desarmer()


def test_analyse_en_echec_ne_bloque_pas_la_surveillance():
    def analyser(ctx):
        raise RuntimeError("caméra débranchée")

    b = Branchements(presence_adulte=lambda: False, analyser=analyser, decider=lambda r: None)
    sup = Superviseur(MachineOubli(), b, periode_s=0.01)
    sup.armer()
    try:
        sup.verrouiller()
        assert _attendre(lambda: "caméra débranchée" in sup.erreur)
        assert sup.machine.etat is Etat.VEILLE and sup.actif
    finally:
        sup.desarmer()


def test_desarmer_pendant_l_analyse_n_envoie_rien():
    notifs, go = [], threading.Event()

    def analyser(ctx):
        go.wait(2)
        return {"objets": ["clés"]}

    b = Branchements(presence_adulte=lambda: False, analyser=analyser,
                     decider=lambda r: Alerte("objet", "t", "m", ("clés",)),
                     notifier=lambda *a: notifs.append(a))
    sup = Superviseur(MachineOubli(), b, periode_s=0.01)
    sup.armer()
    sup.verrouiller()
    assert _attendre(lambda: sup.machine.etat is Etat.ANALYSE)
    threading.Timer(0.05, go.set).start()
    sup.desarmer()
    assert notifs == [] and sup.machine.etat is Etat.INACTIF
