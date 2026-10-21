"""Analyse d'un essai : détection RGB (YOLO), thermique (seuil de chaleur), fusion.

Chaque essai enregistre séparément le verdict RGB et le verdict thermique.
Les approches se calculent ensuite sur le même essai :
    A1 = RGB seul
    A2 = RGB OU thermique (fusion « OU », maximise le rappel)
=> comparaison appariée : même scène, mêmes conditions, deux approches.
"""
import random
import threading
import time

import cv2
import numpy as np

# Classes COCO utilisées
VIVANT = {0: "personne", 15: "chat", 16: "chien"}
VALEUR = {24: "sac à dos", 26: "sac à main", 28: "valise", 63: "ordinateur", 67: "téléphone"}
CLASSES = list(VIVANT) + list(VALEUR)


class Detecteur:
    def __init__(self, cfg):
        self.cfg = cfg
        self.model = None
        self.erreur = ""
        self._lock = threading.Lock()
        threading.Thread(target=self._charger, daemon=True).start()

    def _charger(self):
        try:
            from ultralytics import YOLO
            m = YOLO(self.cfg["modele"])
            m(np.zeros((360, 640, 3), np.uint8), verbose=False)  # préchauffage
            self.model = m
        except Exception as e:  # noqa: BLE001
            self.erreur = str(e)

    @property
    def pret(self):
        return self.model is not None

    def _inferer(self, frames):
        res = self.model(frames, classes=CLASSES, conf=self.cfg["confiance_min"], verbose=False)
        vus = [{int(c) for c in r.boxes.cls.tolist()} for r in res]
        return vus, [r.plot() for r in res]

    def analyser(self, rgb, thermique, verite=None):
        """rgb : liste de Source ; thermique : SourceThermique ou None."""
        if not self.pret:
            raise RuntimeError("Modèle pas encore chargé" + (f" : {self.erreur}" if self.erreur else ""))
        n = self.cfg["images_par_essai"]
        t0 = time.time()
        compte, annotees, par_cam = {}, [], {s.id: set() for s in rgb}
        hits_th, pix_max, tmax, img_th = 0, 0, None, None

        with self._lock:
            for _ in range(n):
                frames, ids = [], []
                for s in rgb:
                    f = s.derniere()
                    if f is not None:
                        frames.append(f)
                        ids.append(s.id)
                if frames:
                    vus, plots = self._inferer(frames)
                    for sid, v in zip(ids, vus):
                        par_cam[sid] |= {c for c in v if c in VIVANT}
                    for c in set().union(*vus):
                        compte[c] = compte.get(c, 0) + 1
                    annotees = plots
                if thermique is not None:
                    m = thermique.mesure()
                    if m is not None:
                        hits_th += int(m["chaud"])
                        pix_max = max(pix_max, m["pixels_chauds"])
                        if m["tmax"] is not None:
                            tmax = max(tmax or -999, m["tmax"])
                time.sleep(0.05)
            if thermique is not None:
                img_th = thermique.apercu()

        presents = {c for c, k in compte.items() if k / n >= self.cfg["ratio_presence"]}
        vivant_th = None if thermique is None else hits_th / n >= 0.5
        return {
            "vivant_rgb": any(c in VIVANT for c in presents),
            "vivant_thermique": vivant_th,
            "classes_vivant": sorted(VIVANT[c] for c in presents if c in VIVANT),
            "objets": sorted(VALEUR[c] for c in presents if c in VALEUR),
            "cameras_vivant": sorted(sid for sid, v in par_cam.items() if v),
            "pixels_chauds": pix_max if thermique is not None else None,
            "tmax": None if tmax is None else round(tmax, 1),
            "latence_s": round(time.time() - t0, 2),
            "images_rgb": annotees,
            "image_thermique": img_th,
        }


class DetecteurDemo(Detecteur):
    """Simule des détections réalistes : le RGB rate des présences, la thermique moins."""

    def _charger(self):
        self.model = "demo"

    def analyser(self, rgb, thermique, verite=None):
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
            "pixels_chauds": (140 if vivant_th else 3) if thermique is not None else None,
            "tmax": (35.1 if vivant_th else 22.8) if thermique is not None else None,
            "latence_s": round(time.time() - t0, 2),
            "images_rgb": images,
            "image_thermique": thermique.apercu() if thermique is not None else None,
        }


def mosaique(images, w=640, h=360):
    imgs = [cv2.resize(i, (w, h)) for i in images if i is not None]
    if not imgs:
        return None
    while len(imgs) < 4:
        imgs.append(np.zeros((h, w, 3), np.uint8))
    return np.vstack([np.hstack(imgs[:2]), np.hstack(imgs[2:4])])
