"""Référence « habitacle vide » : une image par caméra, prise portes fermées, sans rien dedans.

Elle sert à deux choses :
1. Ignorer les faux positifs fixes : la boucle de ceinture prise pour un téléphone,
   la console pour un sac… Si le détecteur voit le même objet au même endroit sur la
   référence, on ne le compte pas.
2. Trouver les zones nouvelles : ce qui a changé par rapport à la référence est un
   objet apporté dans l'habitacle, même si le détecteur ne sait pas le nommer
   (clés, carte, petit objet). Ces zones sont ensuite zoomées pour tenter de les
   identifier.
"""
import json
import os
import threading
import time

import cv2
import numpy as np


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    if inter == 0:
        return 0.0
    aa = (a[2] - a[0]) * (a[3] - a[1])
    ab = (b[2] - b[0]) * (b[3] - b[1])
    return inter / float(aa + ab - inter)


def recouvrement(zone, boite):
    """Part de la zone couverte par la boîte (0..1)."""
    x1, y1 = max(zone[0], boite[0]), max(zone[1], boite[1])
    x2, y2 = min(zone[2], boite[2]), min(zone[3], boite[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    aire = max(1, (zone[2] - zone[0]) * (zone[3] - zone[1]))
    return inter / float(aire)


class Reference:
    def __init__(self, dossier, params):
        self.dossier = dossier
        self.p = params
        self._lock = threading.Lock()
        self.images = {}      # sid -> image BGR
        self.detections = {}  # sid -> [(nom, conf, [x1,y1,x2,y2])]
        self.horodatage = None
        os.makedirs(dossier, exist_ok=True)
        self._charger()

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

    def _sauver(self):
        for sid, img in self.images.items():
            cv2.imwrite(os.path.join(self.dossier, f"{sid}.jpg"), img)
        with open(self._meta(), "w", encoding="utf-8") as fh:
            json.dump({"horodatage": self.horodatage, "detections": self.detections}, fh, ensure_ascii=False)

    # ---- API ------------------------------------------------------------
    def capturer(self, sources, detecteur, n_images=5):
        """Prend plusieurs images par caméra ; les détections « fixes » sont l'union de toutes,
        avec un seuil abaissé, pour ne rater aucun faux positif récurrent."""
        with self._lock:
            self.images, self.detections = {}, {}
            for s in sources:
                dets_cam = []
                for i in range(n_images):
                    f = s.derniere()
                    if f is None:
                        break
                    if i == 0:
                        self.images[s.id] = f
                    if detecteur.pret:
                        for d in detecteur.detecter([f], facteur_conf=0.6)[0]:
                            if not any(x[0] == d["nom"] and iou(x[2], d["boite"]) > 0.6 for x in dets_cam):
                                dets_cam.append((d["nom"], round(d["conf"], 2), [int(v) for v in d["boite"]]))
                    time.sleep(0.15)
                if s.id in self.images:
                    self.detections[s.id] = dets_cam
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
            self.images, self.detections, self.horodatage = {}, {}, None

    def etat(self):
        return {
            "active": bool(self.images),
            "horodatage": self.horodatage,
            "cameras": sorted(self.images),
            "detections_fixes": {sid: len(d) for sid, d in self.detections.items()},
        }

    def a(self, sid):
        return sid in self.images

    # ---- traitement ----------------------------------------------------
    def est_fixe(self, sid, det):
        """Vrai si la même classe est vue au même endroit sur la référence."""
        for nom, _conf, boite in self.detections.get(sid, []):
            if nom == det["nom"] and iou(boite, det["boite"]) >= self.p["iou_fixe"]:
                return True
        return False

    def masque_changement(self, sid, frame):
        """Masque binaire des pixels qui diffèrent de la référence (None si pas de référence)."""
        ref = self.images.get(sid)
        if ref is None:
            return None
        if ref.shape[:2] != frame.shape[:2]:
            ref = cv2.resize(ref, (frame.shape[1], frame.shape[0]))
        g0 = cv2.GaussianBlur(cv2.cvtColor(ref, cv2.COLOR_BGR2GRAY), (7, 7), 0).astype(np.float32)
        g1 = cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (7, 7), 0).astype(np.float32)
        # compensation d'exposition : l'auto-exposition de la caméra bouge d'une prise à l'autre
        if g1.mean() > 1:
            g1 = g1 * (g0.mean() / g1.mean())
        diff = cv2.absdiff(g0, g1)
        masque = (diff > self.p["seuil_changement"]).astype(np.uint8)
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
        masque = cv2.morphologyEx(masque, cv2.MORPH_OPEN, k)
        masque = cv2.dilate(masque, k, iterations=2)
        return masque

    def zones(self, masque_moyen, forme):
        """Boîtes des zones nouvelles à partir d'un masque moyenné sur l'essai (0..1)."""
        if masque_moyen is None:
            return [], False
        h, w = forme[:2]
        m = (masque_moyen >= 0.5).astype(np.uint8)
        if m.mean() > self.p["part_max_image"]:
            # presque toute l'image a changé : lumière, caméra bougée… inutilisable
            return [], True
        cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        zones = []
        for c in cnts:
            x, y, bw, bh = cv2.boundingRect(c)
            if bw * bh < self.p["aire_min"]:
                continue
            if bw * bh > self.p["part_max_image"] * w * h:
                continue
            zones.append([int(x), int(y), int(x + bw), int(y + bh)])
        zones.sort(key=lambda z: -(z[2] - z[0]) * (z[3] - z[1]))
        return zones[: self.p["zones_max"]], False
