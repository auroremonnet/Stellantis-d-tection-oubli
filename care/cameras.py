"""Acquisition des flux caméra.

Chaque caméra tourne dans son propre thread et garde en mémoire la dernière
image reçue : l'interface et l'analyse lisent toujours une image fraîche,
sans file d'attente qui prend du retard.
"""
import math
import os
import threading
import time

import cv2
import numpy as np

BACKEND = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY


class Source:
    """Caméra RGB réelle, lue en continu dans un thread."""

    def __init__(self, sid, index, label, resolution, peripherique="", probleme=""):
        # index : entier (caméra USB), URL (caméra IP) ou None (aucune caméra pour cette position)
        self.id, self.index, self.label = sid, index, label
        self.resolution = resolution
        self.peripherique, self.probleme = peripherique, probleme
        self.frame = None
        self.stamp = 0.0
        self.ok = False
        self.erreur = ""
        self._lock = threading.Lock()
        self._stop = False
        self._thread = threading.Thread(target=self._boucle, daemon=True)

    def demarrer(self):
        self._thread.start()
        return self

    def arreter(self):
        self._stop = True

    def _ouvrir(self):
        if isinstance(self.index, str):  # caméra IP : FFmpeg choisit le format
            return cv2.VideoCapture(self.index)
        cap = cv2.VideoCapture(self.index, BACKEND)
        # MJPG : indispensable pour faire passer plusieurs flux 720p sur un seul hub USB
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.resolution[0])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.resolution[1])
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    def _lire(self, cap):
        return cap.read()

    def _boucle(self):
        while not self._stop:
            if self.index is None:
                self.ok, self.erreur = False, self.probleme or "aucune caméra affectée"
                time.sleep(3)
                continue
            cap = self._ouvrir()
            if not cap.isOpened():
                self.ok, self.erreur = False, f"{self.index} introuvable"
                cap.release()
                time.sleep(3)
                continue
            echecs = 0
            while not self._stop:
                ok, f = self._lire(cap)
                if not ok or f is None:
                    echecs += 1
                    if echecs > 30:
                        self.ok, self.erreur = False, "flux interrompu"
                        break
                    time.sleep(0.05)
                    continue
                echecs = 0
                with self._lock:
                    self.frame, self.stamp = f, time.time()
                self.ok, self.erreur = True, ""
            cap.release()
            time.sleep(1)

    def derniere(self):
        with self._lock:
            return None if self.frame is None else self.frame.copy()

    def apercu(self):
        """Image affichable (BGR 8 bits) pour le dashboard."""
        return self.derniere()

    def etat(self):
        return {"id": self.id, "label": self.label, "index": self.index,
                "peripherique": self.peripherique, "probleme": self.probleme,
                "ok": self.ok and time.time() - self.stamp < 3, "erreur": self.erreur}


# Topdon TC001 (256x192) : le flux UVC fait 256x384 en YUYV. Moitié haute = image déjà
# colorisée par la caméra (gain automatique, inutilisable pour un seuil) ; moitié basse =
# températures brutes, 2 octets par pixel (petit-boutiste), T(°C) = brut / 64 - 273,15.
# Il faut lire le flux SANS conversion RGB d'OpenCV, sinon la moitié basse devient des rayures.
TC001_L, TC001_H = 256, 192


def decoder_tc001(f):
    """Températures (°C, 192x256) d'une image brute TC001, ou None si l'image a été convertie
    en couleur par le pilote (températures perdues)."""
    a = np.asarray(f)
    if a.dtype != np.uint8 or a.size != TC001_L * TC001_H * 2 * 2:
        return None
    if a.ndim == 3 and a.shape[2] == 3:
        return None
    brut = a.reshape(TC001_H * 2, TC001_L, 2)[TC001_H:]
    return (brut[..., 0].astype(np.float32) + brut[..., 1].astype(np.float32) * 256) / 64 - 273.15


def est_tc001(f):
    a = np.asarray(f)
    return a.size in (TC001_L * TC001_H * 4, TC001_L * TC001_H * 6) and a.dtype == np.uint8


class SourceThermique(Source):
    """Caméra thermique. Gère la Topdon TC001 (radiométrique, 256x192) et la Lepton 80x60
    (PureThermal, Y16). `thermique.modele` dans config.json : "auto" (défaut), "tc001", "lepton"."""

    def __init__(self, sid, index, label, params, peripherique="", probleme=""):
        super().__init__(sid, index, label, (160, 120), peripherique, probleme)
        self.params = params
        self.modele = params.get("modele", "auto")
        self.mode = "?"

    def _ouvrir(self):
        backend = {"dshow": cv2.CAP_DSHOW, "msmf": cv2.CAP_MSMF, "v4l2": cv2.CAP_V4L2}.get(
            self.params.get("backend", ""), BACKEND)
        cap = cv2.VideoCapture(self.index, backend)
        if self.modele == "lepton":
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"Y16 "))
        cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)   # flux brut : indispensable pour les températures
        return cap

    @staticmethod
    def _echelle(temp):
        # échelle fixe 15-40 °C : un habitacle vide reste sombre au lieu d'amplifier le bruit
        return np.clip((temp - 15) * (255 / 25), 0, 255).astype(np.uint8)

    def masque_chaud(self, f):
        """Retourne (masque des pixels chauds, image 8 bits, température max ou None)."""
        p = self.params
        if self.modele in ("auto", "tc001") and est_tc001(f):
            temp = decoder_tc001(f)
            if temp is not None:
                self.mode = "radiométrique (TC001)"
                return temp > p["seuil_celsius"], self._echelle(temp), float(temp.max())
            # le pilote a converti en couleur : seule l'image colorisée (moitié haute) reste
            self.mode = "8 bits (TC001 converti, températures perdues)"
            g = cv2.cvtColor(np.asarray(f).reshape(TC001_H * 2, TC001_L, 3)[:TC001_H], cv2.COLOR_BGR2GRAY)
            return g > p["seuil_8bit"], g, None
        if f.dtype == np.uint16:
            self.mode = "radiométrique"
            temp = f.astype(np.float32) / 100.0 - 273.15  # Lepton, format TLinear (centi-Kelvin)
            return temp > p["seuil_celsius"], self._echelle(temp), float(temp.max())
        self.mode = "8 bits"
        g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) if f.ndim == 3 else f
        return g > p["seuil_8bit"], g, None

    def mesure(self):
        f = self.derniere()
        if f is None:
            return None
        masque, img, tmax = self.masque_chaud(f)
        return {"pixels_chauds": int(masque.sum()), "tmax": tmax, "mode": self.mode,
                "chaud": int(masque.sum()) >= self.params["pixels_chauds_min"], "img": img,
                "masque": masque}

    def apercu(self):
        m = self.mesure()
        if m is None:
            return None
        couleur = cv2.applyColorMap(cv2.resize(m["img"], (640, 480), interpolation=cv2.INTER_NEAREST),
                                    cv2.COLORMAP_INFERNO)
        contour = cv2.resize(m["masque"].astype(np.uint8) * 255, (640, 480),
                             interpolation=cv2.INTER_NEAREST)
        cnts, _ = cv2.findContours(contour, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(couleur, cnts, -1, (255, 255, 255), 2)
        return couleur

    def etat(self):
        e = super().etat()
        m = self.mesure() if e["ok"] else None
        e.update({"mode": self.mode,
                  "pixels_chauds": None if m is None else m["pixels_chauds"],
                  "tmax": None if m is None or m["tmax"] is None else round(m["tmax"], 1)})
        return e


# --------------------------------------------------------------------------
# Mode démo : flux synthétiques pour développer le dashboard sans matériel
# --------------------------------------------------------------------------

class SourceDemo(Source):
    def __init__(self, sid, index, label, resolution):
        super().__init__(sid, index, label, resolution)
        self.scene = "vide"  # mis à jour par l'application pendant un essai

    def _ouvrir(self):
        return _FauxCap()

    def _lire(self, cap):
        time.sleep(1 / 15)
        t = time.time()
        h, w = 360, 640
        img = np.full((h, w, 3), (52, 46, 42), np.uint8)
        # banquette
        cv2.rectangle(img, (40, 200), (600, 340), (78, 70, 64), -1)
        cv2.rectangle(img, (40, 120), (600, 210), (90, 82, 75), -1)
        if self.scene == "conducteur":  # adulte au premier plan (surveillance automatique)
            x = int(330 + 25 * math.sin(t * 0.6 + self.index))
            cv2.circle(img, (x, 95), 48, (150, 170, 205), -1)
            cv2.ellipse(img, (x, 260), (110, 120), 0, 0, 360, (95, 75, 60), -1)
        elif self.scene == "vivant":
            x = int(320 + 40 * math.sin(t * 0.8 + self.index))
            cv2.circle(img, (x, 190), 34, (150, 170, 205), -1)
            cv2.ellipse(img, (x, 270), (60, 50), 0, 0, 360, (120, 90, 160), -1)
        elif self.scene == "objet":
            cv2.rectangle(img, (260, 240), (380, 320), (40, 60, 110), -1)
        bruit = np.random.randint(0, 12, img.shape, np.uint8)
        img = cv2.add(img, bruit)
        cv2.putText(img, "DEMO", (w - 70, h - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (230, 230, 230), 1, cv2.LINE_AA)
        return True, img


class SourceThermiqueDemo(SourceThermique):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.scene = "vide"

    def _ouvrir(self):
        return _FauxCap()

    def _lire(self, cap):
        time.sleep(1 / 9)
        yy, xx = np.mgrid[0:60, 0:80]
        temp = np.full((60, 80), 22.0) + np.random.randn(60, 80) * 0.3
        if self.scene in ("vivant", "conducteur"):
            cx = 40 + 6 * math.sin(time.time() * 0.8)
            temp += 13 * np.exp(-(((xx - cx) / 9) ** 2 + ((yy - 32) / 12) ** 2))
        return True, ((temp + 273.15) * 100).astype(np.uint16)


class _FauxCap:
    def isOpened(self):
        return True

    def release(self):
        pass
