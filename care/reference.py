"""Référence « habitacle vide » : une image par caméra, prise sans rien dans la voiture.

Elle sert à deux choses (les calculs sont dans care/detection/changement.py) :
1. Écarter ce qui était déjà là : la boucle de ceinture prise pour des clés, l'équipement
   fixe de la console… Un objet détecté sur des pixels qui n'ont pas changé depuis la
   référence n'a pas été oublié.
2. Trouver ce qui est nouveau : une zone qui a changé est un objet apporté dans
   l'habitacle, même si aucun modèle ne sait le nommer.

La caméra thermique a sa propre référence (le champ thermique de l'habitacle vide), capturée
en même temps : c'est ce qui évite de prendre un siège chauffé par le soleil pour un occupant.
"""
import json
import os
import threading
import time

import cv2
import numpy as np

from .detection.changement import Comparaison, Reglages
from .detection.geometrie import iou, recouvrement  # noqa: F401 — réexportés (anciens imports)


class Reference:
    def __init__(self, dossier, params=None):
        self.dossier = dossier
        self.p = {"iou_fixe": 0.5, "part_deja_la": 0.15, **(params or {})}
        self.reglages = Reglages.depuis_config(self.p)
        self._lock = threading.Lock()
        self.images = {}      # sid -> image BGR
        self.detections = {}  # sid -> [(libellé, confiance, [x1, y1, x2, y2])]
        self.horodatage = None
        self.thermique = None        # champ de l'habitacle vide (°C ou comptes bruts)
        self.unite_thermique = None
        self._source_th = None
        os.makedirs(dossier, exist_ok=True)
        self._charger()
        self._charger_thermique()

    # ---- persistance --------------------------------------------------
    def _meta(self):
        return os.path.join(self.dossier, "reference.json")

    def _charger(self):
        if not os.path.exists(self._meta()):
            return
        try:
            with open(self._meta(), encoding="utf-8") as fh:
                meta = json.load(fh)
            self.horodatage = meta.get("horodatage")
            for sid, dets in meta.get("detections", {}).items():
                img = cv2.imread(os.path.join(self.dossier, f"{sid}.jpg"))
                if img is not None:
                    self.images[sid] = img
                    self.detections[sid] = [tuple(d) for d in dets]
        except Exception:  # noqa: BLE001 - une référence illisible n'empêche pas de démarrer
            self.images, self.detections, self.horodatage = {}, {}, None

    def _fichier_thermique(self):
        return os.path.join(self.dossier, "thermique.npy")  # pas de JPEG : il perdrait les mesures

    def _fichier_unite(self):
        return os.path.join(self.dossier, "thermique.json")

    def _charger_thermique(self):
        if not os.path.exists(self._fichier_thermique()):
            return
        try:
            self.thermique = np.load(self._fichier_thermique(), allow_pickle=False)
            with open(self._fichier_unite(), encoding="utf-8") as fh:
                self.unite_thermique = json.load(fh)["unite"]
        except (OSError, ValueError, KeyError):  # une référence illisible n'empêche pas de démarrer
            self.thermique, self.unite_thermique = None, None

    def _sauver(self):
        for sid, img in self.images.items():
            cv2.imwrite(os.path.join(self.dossier, f"{sid}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 95])
        with open(self._meta(), "w", encoding="utf-8") as fh:
            json.dump({"horodatage": self.horodatage, "detections": self.detections}, fh, ensure_ascii=False)

    # ---- thermique ------------------------------------------------------
    def lier_thermique(self, source):
        """Associe la caméra thermique : elle reçoit la référence à chaque changement."""
        self._source_th = source
        self._publier_thermique()

    def _publier_thermique(self):
        if self._source_th is not None:
            self._source_th.poser_reference(self.thermique, self.unite_thermique)

    def _capturer_thermique(self, n_images=5, pause_s=0.15):
        """Médiane de plusieurs images : le bruit du capteur n'entre pas dans la référence."""
        s = self._source_th
        if s is None:
            return
        champs, unite = [], None
        for _ in range(n_images):
            f = s.derniere()
            if f is not None:
                champ, u = s.champ(f)
                if champ is not None and (unite is None or (u == unite and champ.shape == champs[0].shape)):
                    champs.append(champ)
                    unite = u
            time.sleep(pause_s)
        self.thermique = np.median(champs, axis=0).astype(np.float32) if champs else None
        self.unite_thermique = unite if champs else None
        if self.thermique is not None:
            np.save(self._fichier_thermique(), self.thermique)
            with open(self._fichier_unite(), "w", encoding="utf-8") as fh:
                json.dump({"unite": self.unite_thermique}, fh, ensure_ascii=False)
        else:
            self._oublier_thermique()                 # jamais de référence périmée
        self._publier_thermique()

    def _oublier_thermique(self):
        for fichier in (self._fichier_thermique(), self._fichier_unite()):
            if os.path.exists(fichier):
                os.remove(fichier)

    # ---- API ------------------------------------------------------------
    def capturer(self, sources, detecteur):
        """Mémorise une image par caméra et ce que le détecteur y voit déjà (seuil abaissé,
        pour ne rater aucune fausse détection récurrente)."""
        with self._lock:
            self.images, self.detections = {}, {}
            for s in sources:
                f = s.derniere()
                if f is None:
                    continue
                self.images[s.id] = f
                self.detections[s.id] = [
                    (detecteur.libelle(d["nom"]), round(d["conf"], 2), [int(v) for v in d["boite"]])
                    for d in (detecteur.detecter([f], facteur_conf=0.6)[0] if detecteur.pret else [])]
            self._capturer_thermique()
            self.horodatage = time.strftime("%Y-%m-%dT%H:%M:%S")
            self._sauver()
        return self.etat()

    def effacer(self):
        with self._lock:
            for sid in list(self.images):
                p = os.path.join(self.dossier, f"{sid}.jpg")
                if os.path.exists(p):
                    os.remove(p)
            if os.path.exists(self._meta()):
                os.remove(self._meta())
            self._oublier_thermique()
            self.images, self.detections, self.horodatage = {}, {}, None
            self.thermique, self.unite_thermique = None, None
            self._publier_thermique()

    def etat(self):
        return {
            "active": bool(self.images),
            "horodatage": self.horodatage,
            "cameras": sorted(self.images),
            "thermique": self.thermique is not None,
            "detections_fixes": {sid: len(d) for sid, d in self.detections.items()},
        }

    def a(self, sid):
        return sid in self.images

    # ---- traitement ----------------------------------------------------
    def comparer(self, sid, image):
        """Comparaison de l'image à la référence de cette caméra (None s'il n'y en a pas)."""
        ref = self.images.get(sid)
        return None if ref is None else Comparaison(ref, image, self.reglages)

    def deja_la(self, sid, detection, comparaison=None):
        """Vrai si la détection existait déjà sur la référence.
        Avec une comparaison fiable, ce sont les pixels qui décident : rien n'a changé sous
        la boîte. Sinon (lumière changée, être vivant) : même libellé au même endroit que
        ce que le détecteur voyait déjà sur la référence."""
        if comparaison is not None:
            return comparaison.part_changee(detection.boite) < self.p["part_deja_la"]
        return any(nom == detection.cle and iou(boite, detection.boite) >= self.p["iou_fixe"]
                   for nom, _conf, boite in self.detections.get(sid, []))
