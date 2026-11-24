import numpy as np

import care.cameras as cameras
from care.cameras import Source, image_noire


def test_image_noire():
    assert image_noire(np.zeros((720, 1280, 3), np.uint8))
    assert not image_noire(np.full((720, 1280, 3), 120, np.uint8))
    sombre = np.zeros((480, 640, 3), np.uint8)
    sombre[200:260, 300:360] = 200  # scène sombre mais avec quelque chose de visible
    assert not image_noire(sombre)
    assert not image_noire(None)


def test_pastille_rouge_si_image_noire(monkeypatch):
    s = Source("rgb0", 1, "Avant gauche", (1280, 720))
    s.ok, s.stamp = True, cameras.time.time()
    s.frame = np.zeros((720, 1280, 3), np.uint8)
    e = s.etat()
    assert not e["ok"] and "noire" in e["erreur"]
    s.frame = np.full((720, 1280, 3), 110, np.uint8)
    assert s.etat()["ok"]


def test_mjpg_demande_apres_la_resolution(monkeypatch):
    """Sous DirectShow, fixer la résolution après le MJPG repasse en YUY2 : 4 flux 720p
    saturent alors le hub USB et les images arrivent noires."""
    appels = []

    class FausseCap:
        def __init__(self, *a):
            pass

        def set(self, prop, val):
            appels.append(prop)

    monkeypatch.setattr(cameras.cv2, "VideoCapture", FausseCap)
    Source("rgb0", 1, "Avant gauche", (1280, 720))._ouvrir()
    cv2 = cameras.cv2
    assert appels.index(cv2.CAP_PROP_FOURCC) > appels.index(cv2.CAP_PROP_FRAME_WIDTH)
    assert appels.index(cv2.CAP_PROP_FOURCC) > appels.index(cv2.CAP_PROP_FRAME_HEIGHT)
