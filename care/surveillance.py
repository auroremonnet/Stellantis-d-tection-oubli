"""Surveillance automatique : simuler l'oubli de bout en bout, sans bouton « Lancer ».

Scénario joué sur le banc :
    1. on arme la surveillance habitacle vide → la référence est capturée ;
    2. le conducteur monte, pose ses affaires (ou installe la poupée) ;
    3. il descend : dès qu'aucun adulte n'est vu pendant `delai_sortie_s`
       (ou immédiatement sur « verrouillage »), l'analyse complète est lancée ;
    4. verdict : alerte (critique ou objet) ou rien à signaler ;
    5. en cas d'alerte critique sans retour du conducteur : rappels (escalade).

Délais par défaut alignés sur le protocole Euro NCAP 2026 « Child Presence
Detection » : premier avertissement moins de 15 s après le verrouillage, escalade
dans les 90 s, puis rappel toutes les minutes pendant au moins 20 minutes.

Le module est en deux couches :
    MachineOubli : logique pure (aucune caméra, horloge injectable) → tests unitaires ;
    Superviseur  : boucle en tâche de fond qui branche la machine sur le matériel
                   au moyen de fonctions fournies par l'application.
"""
from __future__ import annotations

import contextlib
import enum
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


class Etat(str, enum.Enum):
    INACTIF = "inactif"      # surveillance désarmée
    VEILLE = "veille"        # armée, habitacle vide, on attend un occupant
    OCCUPE = "occupe"        # un adulte est à bord
    SORTIE = "sortie"        # plus d'adulte vu : compte à rebours avant analyse
    ANALYSE = "analyse"      # analyse complète en cours
    ALERTE = "alerte"        # oubli détecté, en attente du retour du conducteur


class Action(str, enum.Enum):
    """Ce que la machine demande à l'application de faire."""
    ANALYSER = "analyser"
    RAPPELER = "rappeler"    # escalade : renvoyer l'alerte
    ACQUITTER = "acquitter"  # le conducteur est revenu : l'alerte est levée


@dataclass(frozen=True)
class Parametres:
    confirmation_presence_s: float = 1.5   # présence continue avant de déclarer « occupé »
    delai_sortie_s: float = 8.0            # absence continue avant d'analyser
    delai_escalade_s: float = 90.0         # premier rappel après l'alerte
    periode_rappel_s: float = 60.0         # rappels suivants
    duree_rappels_s: float = 1200.0        # on arrête de rappeler après 20 min
    niveaux_escalade: tuple[str, ...] = ("critique",)

    @classmethod
    def depuis_config(cls, cfg: dict | None) -> Parametres:
        cfg = dict(cfg or {})
        if "niveaux_escalade" in cfg:
            cfg["niveaux_escalade"] = tuple(cfg["niveaux_escalade"])
        connus = cls.__dataclass_fields__
        return cls(**{k: v for k, v in cfg.items() if k in connus})


@dataclass
class Evenement:
    t: float          # horodatage mur (time.time) pour l'affichage
    type: str
    detail: str = ""

    def en_dict(self) -> dict:
        return {"t": round(self.t, 3), "heure": time.strftime("%H:%M:%S", time.localtime(self.t)),
                "type": self.type, "detail": self.detail}


@dataclass
class _Chrono:
    present_depuis: float | None = None
    absent_depuis: float | None = None
    dernier_adulte: float | None = None   # dernier instant où un adulte a été vu


class MachineOubli:
    """Machine à états de la surveillance. Aucune entrée/sortie : on lui donne des
    observations, elle répond par des actions. Toutes les durées viennent de `horloge`."""

    def __init__(self, params: Parametres | None = None,
                 horloge: Callable[[], float] = time.monotonic,
                 horloge_mur: Callable[[], float] = time.time,
                 taille_historique: int = 50):
        self.p = params or Parametres()
        self._h = horloge
        self._mur = horloge_mur
        self.etat = Etat.INACTIF
        self.historique: deque[Evenement] = deque(maxlen=taille_historique)
        self.nb_evenements = 0
        self._c = _Chrono()
        self._depuis = self._h()
        self.niveau_alerte: str | None = None
        self._t_alerte: float | None = None
        self.rappels = 0
        self.derniere_latence_s: float | None = None
        self._t_sortie: float | None = None

    # ---- commandes ---------------------------------------------------------
    def armer(self) -> None:
        self._c = _Chrono()
        self._aller(Etat.VEILLE, "surveillance armée")

    def desarmer(self) -> None:
        self._reinit_alerte()
        self._aller(Etat.INACTIF, "surveillance désarmée")

    def verrouiller(self) -> list[Action]:
        """Verrouillage du véhicule (simulé) : on analyse tout de suite, comme le ferait
        une vraie voiture sur l'événement « portes verrouillées »."""
        if self.etat in (Etat.OCCUPE, Etat.SORTIE, Etat.VEILLE):
            self._t_sortie = self._h()
            self._aller(Etat.ANALYSE, "verrouillage du véhicule")
            return [Action.ANALYSER]
        return []

    def conclure_analyse(self, niveau: str | None, detail: str = "") -> None:
        """Résultat de l'analyse : niveau d'alerte ('critique', 'objet') ou None."""
        if self.etat is not Etat.ANALYSE:
            return
        now = self._h()
        self.derniere_latence_s = None if self._t_sortie is None else round(now - self._t_sortie, 2)
        if niveau:
            self.niveau_alerte, self._t_alerte, self.rappels = niveau, now, 0
            self._c.present_depuis = None
            self._aller(Etat.ALERTE, f"alerte {niveau}" + (f" : {detail}" if detail else ""))
        else:
            self._c = _Chrono()
            self._aller(Etat.VEILLE, "rien à signaler" + (f" : {detail}" if detail else ""))

    # ---- observations ------------------------------------------------------
    def observer(self, adulte_present: bool) -> list[Action]:
        """Une observation (≈ toutes les 0,5 s). Gère aussi les délais (escalade)."""
        now = self._h()
        c = self._c
        if adulte_present:
            c.dernier_adulte = now
            c.absent_depuis = None
            if c.present_depuis is None:
                c.present_depuis = now
        else:
            c.present_depuis = None
            if c.absent_depuis is None:
                c.absent_depuis = now
        presence_confirmee = (c.present_depuis is not None
                              and now - c.present_depuis >= self.p.confirmation_presence_s)

        if self.etat is Etat.VEILLE and presence_confirmee:
            self._aller(Etat.OCCUPE, "occupant à bord")
        elif self.etat is Etat.OCCUPE and not adulte_present:
            self._aller(Etat.SORTIE, "plus d'adulte détecté")
        elif self.etat is Etat.SORTIE:
            if adulte_present:
                self._aller(Etat.OCCUPE, "occupant revenu avant l'analyse")
            elif now - self._dernier_vu() >= self.p.delai_sortie_s:
                self._t_sortie = self._dernier_vu()
                self._aller(Etat.ANALYSE, f"habitacle vide depuis {self.p.delai_sortie_s:g} s")
                return [Action.ANALYSER]
        elif self.etat is Etat.ALERTE:
            if presence_confirmee:
                self._reinit_alerte()
                self._aller(Etat.OCCUPE, "conducteur revenu : alerte levée")
                return [Action.ACQUITTER]
            return self._escalade(now)
        return []

    # ---- état --------------------------------------------------------------
    def compte_a_rebours(self) -> float | None:
        if self.etat is Etat.SORTIE:
            return max(0.0, round(self.p.delai_sortie_s - (self._h() - self._dernier_vu()), 1))
        return None

    def instantane(self) -> dict[str, Any]:
        return {
            "etat": self.etat.value,
            "depuis_s": round(self._h() - self._depuis, 1),
            "compte_a_rebours_s": self.compte_a_rebours(),
            "niveau_alerte": self.niveau_alerte,
            "rappels": self.rappels,
            "latence_alerte_s": self.derniere_latence_s,
            "historique": [e.en_dict() for e in reversed(self.historique)],
        }

    # ---- interne -----------------------------------------------------------
    def _dernier_vu(self) -> float:
        """Départ du conducteur = dernier instant où un adulte a été vu (et non le premier
        échantillon « absent ») : la latence mesurée ne flatte pas le système."""
        c = self._c
        return c.dernier_adulte if c.dernier_adulte is not None else (c.absent_depuis or self._h())

    def _escalade(self, now: float) -> list[Action]:
        if self.niveau_alerte not in self.p.niveaux_escalade or self._t_alerte is None:
            return []
        ecoule = now - self._t_alerte
        if ecoule > self.p.duree_rappels_s:
            return []
        echeance = self.p.delai_escalade_s + self.rappels * self.p.periode_rappel_s
        if ecoule >= echeance:
            self.rappels += 1
            self._noter("rappel", f"escalade n°{self.rappels}")
            return [Action.RAPPELER]
        return []

    def _reinit_alerte(self) -> None:
        self.niveau_alerte, self._t_alerte, self.rappels = None, None, 0

    def _aller(self, etat: Etat, detail: str) -> None:
        self.etat = etat
        self._depuis = self._h()
        self._noter(etat.value, detail)

    def _noter(self, type_: str, detail: str) -> None:
        self.historique.append(Evenement(self._mur(), type_, detail))
        self.nb_evenements += 1

    def evenements_depuis(self, n: int) -> list[Evenement]:
        """Événements notés après le n-ième (bornés par la taille de l'historique)."""
        k = min(self.nb_evenements - n, len(self.historique))
        return list(self.historique)[-k:] if k > 0 else []


# ==========================================================================
@dataclass
class Branchements:
    """Fonctions fournies par l'application : le superviseur ne connaît ni les
    caméras, ni le modèle, ni ntfy. Remplaçables par des doublures dans les tests."""
    presence_adulte: Callable[[], bool]
    analyser: Callable[[dict], dict]                       # contexte -> résultat d'analyse
    decider: Callable[[dict], Any]                         # résultat -> Alerte | None
    notifier: Callable[[Any, dict, str], None] = lambda alerte, resultat, motif: None
    enregistrer: Callable[[dict, dict], None] = lambda resultat, contexte: None
    journaliser: Callable[[Evenement], None] = lambda evt: None


@dataclass
class Superviseur:
    """Fait tourner la MachineOubli dans un thread, au rythme de `periode_s`."""
    machine: MachineOubli
    branchements: Branchements
    periode_s: float = 0.5
    contexte: dict = field(default_factory=dict)
    erreur_boucle: str = ""      # observation impossible (caméra, modèle) — effacée au tour suivant réussi
    erreur_analyse: str = ""     # dernière analyse en échec — effacée à la prochaine analyse réussie
    dernier_resultat: dict | None = None
    _thread: threading.Thread | None = field(default=None, init=False, repr=False)
    _stop: threading.Event = field(default_factory=threading.Event, init=False, repr=False)
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)
    _derniere_alerte: Any = field(default=None, init=False, repr=False)
    _vu: int = field(default=0, init=False, repr=False)
    _en_attente: list = field(default_factory=list, init=False, repr=False)

    # ---- pilotage ----------------------------------------------------------
    def armer(self, contexte: dict | None = None) -> None:
        self.desarmer()
        with self._lock:
            self.contexte = dict(contexte or {})
            self.erreur_boucle = self.erreur_analyse = ""
            self.dernier_resultat, self._derniere_alerte = None, None
            self._en_attente = []
            self.machine.armer()
            self._publier()
        self._stop.clear()
        self._thread = threading.Thread(target=self._boucle, name="surveillance", daemon=True)
        self._thread.start()

    def desarmer(self) -> None:
        self._stop.set()
        t = self._thread
        if t is not None and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=5)
        self._thread = None
        with self._lock:
            if self.machine.etat is not Etat.INACTIF:
                self.machine.desarmer()
                self._publier()

    def verrouiller(self) -> None:
        """Les actions sont exécutées par le thread de surveillance, jamais par l'appelant
        (requête HTTP) : un seul exécutant, donc pas deux analyses en parallèle."""
        with self._lock:
            self._en_attente.extend(self.machine.verrouiller())
            self._publier()

    @property
    def erreur(self) -> str:
        return self.erreur_boucle or self.erreur_analyse

    @property
    def actif(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def instantane(self) -> dict:
        with self._lock:
            out = self.machine.instantane()
            dernier = None if self.dernier_resultat is None else {
                k: v for k, v in self.dernier_resultat.items()
                if not k.startswith(("_", "image"))}  # images et données internes : pas en JSON
        out.update({"actif": self.actif, "erreur": self.erreur,
                    "contexte": self.contexte, "dernier_resultat": dernier})
        return out

    # ---- boucle ------------------------------------------------------------
    def _boucle(self) -> None:
        while not self._stop.is_set():
            debut = time.monotonic()
            try:
                with self._lock:
                    actions, self._en_attente = self._en_attente, []
                if not actions:
                    present = bool(self.branchements.presence_adulte())
                    with self._lock:
                        actions = self.machine.observer(present)
                        self._publier()
                self.erreur_boucle = ""
                self._executer(actions)
            except Exception as e:  # noqa: BLE001 — une erreur ponctuelle ne doit pas tuer la boucle
                self.erreur_boucle = f"{type(e).__name__}: {e}"
            self._stop.wait(max(0.0, self.periode_s - (time.monotonic() - debut)))

    def _executer(self, actions: list[Action]) -> None:
        b = self.branchements
        for a in actions:
            if a is Action.ANALYSER:
                try:
                    resultat = b.analyser(self.contexte)
                except Exception as e:  # noqa: BLE001
                    with self._lock:
                        self.erreur_analyse = f"analyse impossible : {e}"
                        self.machine.conclure_analyse(None, "analyse en échec")
                        self._publier()
                    continue
                alerte = b.decider(resultat)
                self.erreur_analyse = ""
                with self._lock:
                    if self._stop.is_set() or self.machine.etat is not Etat.ANALYSE:
                        continue  # désarmé pendant l'analyse : on ne notifie rien
                    self.machine.conclure_analyse(getattr(alerte, "niveau", None),
                                                  getattr(alerte, "resume", ""))
                    resultat = {**resultat, "latence_alerte_s": self.machine.derniere_latence_s,
                                "alerte": None if alerte is None else alerte.en_dict()}
                    self.dernier_resultat = resultat
                    self._derniere_alerte = alerte
                    self._publier()
                if alerte is not None:
                    b.notifier(alerte, resultat, "alerte")
                b.enregistrer(resultat, self.contexte)
            elif a is Action.RAPPELER and self._derniere_alerte is not None:
                b.notifier(self._derniere_alerte, self.dernier_resultat or {}, "rappel")
            elif a is Action.ACQUITTER and self._derniere_alerte is not None:
                b.notifier(self._derniere_alerte, self.dernier_resultat or {}, "acquittement")
                self._derniere_alerte = None

    def _publier(self) -> None:
        """Transmet les nouveaux événements de la machine au journal (une seule fois chacun)."""
        for e in self.machine.evenements_depuis(self._vu):
            with contextlib.suppress(Exception):  # le journal est accessoire
                self.branchements.journaliser(e)
        self._vu = self.machine.nb_evenements
