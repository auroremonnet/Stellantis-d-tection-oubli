"""Façade de la détection RGB + thermique, utilisée par le dashboard et les outils.

Le travail est fait dans le paquet `care.detection` (voir son __init__ pour le plan).
Ici : le chargement des modèles en arrière-plan, les verrous, et trois services :

    detecter(images)          détections d'images isolées (outils, capture de la référence)
    presence_adulte(sources)  « le conducteur est-il à bord ? » (surveillance, toutes les 0,5 s)
    analyser(rgb, thermique)  un essai complet → le résultat journalisé et affiché

Chaque essai enregistre séparément le verdict RGB et le verdict thermique :
    A1 = RGB seul
    A2 = RGB OU thermique (fusion « OU », maximise le rappel)
"""
import random
import threading
import time

import cv2

from .detection.catalogue import INCONNU
from .detection.essai import analyser_essai
from .detection.identification import est_adulte, fusionner
from .detection.moteurs import LIBELLES, MoteurCare, creer
from .detection.rendu import mosaique

__all__ = ["Detecteur", "DetecteurDemo", "INCONNU", "LIBELLES", "est_adulte", "fusionner", "mosaique"]


class Detecteur:
    def __init__(self, cfg):
        self.cfg = cfg
        d = cfg.get("detection", {})
        self._moteur = creer(cfg)
        self.moteur = self._moteur.nom
        self.modele = self._moteur.modele
        self.hauteur_adulte = d.get("hauteur_min_adulte", 0.35)
        self.imgsz_presence = d.get("imgsz_presence", 480)  # surveillance : plus petit = plus rapide
        self.alerte_inconnu = d.get("alerte_zone_inconnue", True)
        self.erreur = ""
        self._pret = False
        self._lock = threading.Lock()            # un essai à la fois
        self._lock_inference = threading.Lock()  # un appel aux modèles à la fois (surveillance + essai)
        threading.Thread(target=self._charger, daemon=True).start()

    def _charger(self):
        try:
            self._moteur.charger()
            self._pret = True
        except Exception as e:  # noqa: BLE001 — affiché dans le dashboard
            self.erreur = str(e)

    # ---- état (lu par /api/etat et /api/config) ----------------------------
    @property
    def pret(self):
        return self._pret

    @property
    def avertissement(self):
        return self._moteur.avertissement

    @property
    def custom(self):
        return self._moteur.custom

    @property
    def vocabulaire(self):
        """{"vivant": [libellés], "valeur": [libellés]} reconnus par le moteur courant."""
        m = self._moteur
        if isinstance(m, MoteurCare):
            return {"vivant": m.catalogue.cles("vivant"), "valeur": m.catalogue.cles("valeur")}
        if m.coco:
            from .detection.moteurs import COCO_VALEUR, COCO_VIVANT
            return {"vivant": list(COCO_VIVANT.values()), "valeur": list(COCO_VALEUR.values())}
        return {"vivant": [m.libelle(p) for p in m.prompts_vivant],
                "valeur": list(dict.fromkeys(m.libelle(p) for p in m.prompts_valeur))}

    def libelle(self, nom):
        return self._moteur.libelle(nom)

    # ---- services ------------------------------------------------------------
    def detecter(self, frames, facteur_conf=1.0):
        """Pour chaque image : liste de {nom, type, conf, boite, source}."""
        with self._lock_inference:
            observations = self._moteur.observer(frames, facteur_conf)
            conclusions = [self._moteur.conclure(f, [o]) for f, o in zip(frames, observations)]
        return [[{"nom": d.extra.get("nom", d.cle), "type": d.categorie, "conf": float(d.conf),
                  "boite": [int(v) for v in d.boite], "source": "+".join(d.sources)}
                 for d in c.detections] for c in conclusions]

    def presence_adulte(self, sources):
        """Vrai si un adulte est vu sur au moins une des caméras données (surveillance).
        Appelé toutes les 0,5 s : modèle de base seul, classe « personne » seule, image
        réduite — bien plus léger qu'une analyse complète, pour tenir le rythme sur CPU."""
        frames = [f for f in (s.derniere() for s in sources) if f is not None]
        if not frames or not self.pret:
            return False
        with self._lock_inference:
            boites = self._moteur.personnes(frames, self.imgsz_presence)
        return any(est_adulte({"nom": "personne", "type": "vivant", "boite": b}, f.shape[0], self.hauteur_adulte)
                   for f, bs in zip(frames, boites) for b in bs)

    def analyser(self, rgb, thermique, verite=None, reference=None):
        """rgb : liste de Source ; thermique : SourceThermique ou None ; reference : Reference ou None."""
        if not self.pret:
            raise RuntimeError("Modèle pas encore chargé" + (f" : {self.erreur}" if self.erreur else ""))
        with self._lock:
            return analyser_essai(self._moteur, self._lock_inference, rgb, thermique, reference,
                                  n_images=self.cfg["images_par_essai"], alerte_inconnu=self.alerte_inconnu)


class DetecteurDemo(Detecteur):
    """Simule des détections réalistes : le RGB rate des présences, la thermique moins."""

    def _charger(self):
        self._pret = True

    def detecter(self, frames, facteur_conf=1.0):
        return [[] for _ in frames]

    def presence_adulte(self, sources):
        """En démo, le conducteur est « à bord » quand la scène simulée le montre."""
        return any(getattr(s, "scene", "") == "conducteur" for s in sources)

    def analyser(self, rgb, thermique, verite=None, reference=None):
        t0 = time.time()
        time.sleep(1.2)
        r = random.random
        vivant_rgb = (verite == "vivant" and r() < 0.68) or (verite != "vivant" and r() < 0.06)
        vivant_th = None
        if thermique is not None:
            vivant_th = (verite == "vivant" and r() < 0.9) or (verite != "vivant" and r() < 0.12)
        objets = ["sac à main"] if verite == "objet" and r() < 0.8 else []
        images = []
        for s in rgb:
            f = s.derniere()
            if f is not None:
                if vivant_rgb:
                    cv2.rectangle(f, (250, 140), (400, 330), (60, 200, 60), 2)
                    cv2.putText(f, "personne 0.71", (250, 132), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                                (60, 200, 60), 1, cv2.LINE_AA)
                images.append(f)
        return {
            "vivant_rgb": vivant_rgb, "vivant_thermique": vivant_th,
            "classes_vivant": ["personne"] if vivant_rgb else [], "objets": objets,
            "cameras_vivant": [rgb[2].id] if vivant_rgb and len(rgb) > 2 else [],
            "detections": [],
            "zones_nouvelles": 1 if objets else 0, "reference_utilisee": False, "lumiere_changee": False,
            "pixels_chauds": (140 if vivant_th else 3) if thermique is not None else None,
            "tmax": (35.1 if vivant_th else 22.8) if thermique is not None else None,
            "latence_s": round(time.time() - t0, 2),
            "images_rgb": images,
            "image_thermique": thermique.apercu() if thermique is not None else None,
        }
