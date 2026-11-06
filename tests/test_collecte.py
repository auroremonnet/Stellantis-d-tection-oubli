import csv
import os

import numpy as np

from care.collecte import Collecteur, slug


class Cam:
    def __init__(self, sid, frame):
        self.id, self.label, self.frame = sid, f"Position {sid}", frame

    def derniere(self):
        return None if self.frame is None else self.frame.copy()


def scene(valeur):
    return np.full((72, 128, 3), valeur, np.uint8)


def test_slug():
    assert slug("Clés · console centrale") == "cles-console-centrale"
    assert slug("") == "sans-etiquette"


def test_rafale_ecarte_les_doublons_et_tient_le_manifeste(tmp_path):
    a, b = Cam("rgb0", scene(40)), Cam("rgb1", scene(90))
    c = Collecteur(str(tmp_path), [a, b, Cam("rgb2", None)], horloge=lambda: 1_790_000_000.0,
                   attendre=lambda s: None)
    assert c.prise("clés") == (2, 0)
    assert c.prise("clés") == (0, 2)          # rien n'a bougé : doublons
    a.frame = scene(140)                      # on a déplacé l'objet devant rgb0
    assert c.prise("clés") == (1, 1)
    man = os.path.join(tmp_path, c.session, "manifeste.csv")
    with open(man, encoding="utf-8") as fh:
        lignes = list(csv.DictReader(fh))
    assert [l["camera"] for l in lignes] == ["rgb0", "rgb1", "rgb0"]
    assert all(os.path.exists(os.path.join(tmp_path, c.session, l["fichier"])) for l in lignes)
    assert c.total_session() == 3


def test_rafale_complete(tmp_path):
    cam = Cam("rgb0", scene(10))
    c = Collecteur(str(tmp_path), [cam], attendre=lambda s: setattr(cam, "frame", scene(int(cam.frame[0, 0, 0]) + 30)))
    c.rafale("bébé siège auto", prises=4, intervalle_s=0)
    e = c.resume()
    assert e["en_cours"] is False and e["prise"] == 4 and e["gardees"] == 4 and e["total_session"] == 4
