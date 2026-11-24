"""Collecte d'images brutes dans la voiture, pour enrichir le jeu d'entraînement (v2).

Une « rafale » prend N images sur chaque caméra RGB, à intervalle régulier, pendant qu'on
déplace l'objet / la poupée entre deux prises. Les images quasi identiques à la précédente
de la même caméra sont écartées : 4 caméras qui filment une scène immobile produiraient
sinon des dizaines de doublons qui gonflent le dataset sans rien apprendre au modèle (et
faussent le test si un doublon tombe dans le split test).

    data/collecte/<session>/<etiquette>/<horodatage>_<camera>.jpg
    data/collecte/<session>/manifeste.csv   une ligne par image (caméra, étiquette, variante…)

Une session = une journée de prises. Garder une session entière dans le même split
(train OU test) dans Roboflow : c'est la seule façon d'avoir un test honnête.
"""
from __future__ import annotations

import csv
import os
import re
import threading
import time
import unicodedata
from datetime import datetime

import cv2
import numpy as np

CHAMPS = ["fichier", "horodatage", "camera", "position", "etiquette", "variante", "commentaire"]


def slug(texte: str) -> str:
    t = unicodedata.normalize("NFKD", texte or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")[:40] or "sans-etiquette"


def signature(frame) -> np.ndarray:
    """Vignette 64x36 en niveaux de gris : assez pour repérer un doublon, insensible au bruit."""
    g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    return cv2.resize(g, (64, 36), interpolation=cv2.INTER_AREA).astype(np.float32)


def difference(a: np.ndarray, b: np.ndarray) -> float:
    """Écart moyen absolu entre deux signatures (0-255)."""
    return float(np.abs(a - b).mean())


class Collecteur:
    def __init__(self, dossier, sources, seuil_doublon=4.0, horloge=time.time, attendre=None):
        self.dossier = dossier
        self.sources = sources            # caméras RGB (objets .id, .label, .derniere())
        self.seuil = seuil_doublon
        self._dernieres: dict[str, np.ndarray] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._horloge = horloge
        self._attendre = attendre or self._stop.wait   # « Arrêter » interrompt l'attente
        self.etat = {"en_cours": False, "etiquette": "", "prise": 0, "prises": 0,
                     "gardees": 0, "doublons": 0, "session": "", "total_session": 0, "erreur": ""}

    @property
    def session(self):
        return datetime.fromtimestamp(self._horloge()).strftime("%Y%m%d")

    def _manifeste(self):
        return os.path.join(self.dossier, self.session, "manifeste.csv")

    def total_session(self) -> int:
        p = self._manifeste()
        if not os.path.exists(p):
            return 0
        with open(p, encoding="utf-8") as fh:
            return max(0, sum(1 for _ in fh) - 1)

    def prise(self, etiquette, variante="", commentaire="") -> tuple[int, int]:
        """Une image par caméra. Renvoie (gardées, doublons écartés)."""
        d = os.path.join(self.dossier, self.session, slug(etiquette))
        os.makedirs(d, exist_ok=True)
        hd = datetime.fromtimestamp(self._horloge())
        horo = hd.strftime("%H%M%S") + f"{hd.microsecond // 1000:03d}"
        gardees, doublons, lignes = 0, 0, []
        for s in self.sources:
            f = s.derniere()
            if f is None:
                continue
            sig = signature(f)
            prec = self._dernieres.get(s.id)
            if prec is not None and difference(sig, prec) < self.seuil:
                doublons += 1
                continue
            self._dernieres[s.id] = sig
            nom = f"{self.session}-{horo}_{s.id}.jpg"
            cv2.imwrite(os.path.join(d, nom), f, [cv2.IMWRITE_JPEG_QUALITY, 95])
            gardees += 1
            lignes.append({"fichier": f"{slug(etiquette)}/{nom}", "horodatage": hd.isoformat(timespec="seconds"),
                           "camera": s.id, "position": s.label, "etiquette": etiquette,
                           "variante": variante, "commentaire": commentaire})
        if lignes:
            p = self._manifeste()
            neuf = not os.path.exists(p)
            with open(p, "a", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=CHAMPS)
                if neuf:
                    w.writeheader()
                w.writerows(lignes)
        return gardees, doublons

    def rafale(self, etiquette, prises=10, intervalle_s=1.5, variante="", commentaire=""):
        """Bloquant : à lancer dans un thread (voir demarrer)."""
        with self._lock:
            self._stop.clear()
            self.etat.update(en_cours=True, etiquette=etiquette, prise=0, prises=prises,
                             gardees=0, doublons=0, session=self.session, erreur="")
            try:
                for i in range(prises):
                    if self._stop.is_set():
                        break
                    g, dbl = self.prise(etiquette, variante, commentaire)
                    self.etat.update(prise=i + 1, gardees=self.etat["gardees"] + g,
                                     doublons=self.etat["doublons"] + dbl)
                    if i < prises - 1:
                        self._attendre(intervalle_s)
            except Exception as e:  # noqa: BLE001 — disque plein, droits… : affiché dans le dashboard
                self.etat["erreur"] = str(e)
            finally:
                self.etat.update(en_cours=False, total_session=self.total_session())

    def demarrer(self, **kw):
        if self.etat["en_cours"]:
            return False
        self.etat["en_cours"] = True
        threading.Thread(target=self.rafale, kwargs=kw, daemon=True).start()
        return True

    def arreter(self):
        self._stop.set()

    def resume(self):
        return {**self.etat, "total_session": self.etat["total_session"] or self.total_session()}
