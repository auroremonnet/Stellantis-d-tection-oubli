"""Vérifie les sons simultanés et la fenêtre temporelle d'un essai."""
import time
import unittest

import numpy as np

from care.audio import DetecteurAudio, extraire_sons


class AudioMelangeTests(unittest.TestCase):
    def test_aboiement_visible_quand_la_parole_domine(self):
        labels = [
            "Speech", "Male speech, man speaking", "Female speech, woman speaking",
            "Bark", "Meow", "Baby cry, infant cry", "Crying, sobbing",
        ]
        scores = np.array([0.95, 0.85, 0.75, 0.65, 0.1, 0.1, 0.1])
        cibles, generaux, hors_parole = extraire_sons(
            scores, {label: i for i, label in enumerate(labels)},
            dict(enumerate(labels)), top_k=3,
        )
        self.assertEqual(generaux[0]["label"], "Speech")
        self.assertEqual(hors_parole[0], {"label": "Bark", "score": 0.65})
        self.assertEqual(cibles["aboiement"], 0.65)

    def test_pic_bref_conserve_sans_contaminer_un_nouvel_essai(self):
        cfg = {"active": False, "maintien_s": 4, "seuil": 0.5, "top_k": 3}
        detecteur = DetecteurAudio(cfg)
        cfg["active"] = True
        detecteur.modele = object()
        detecteur._flux_ok = True
        instant = time.monotonic()
        detecteur._mesures.append((instant - 3, instant - 2, instant - 2,
                                   {"pleurs": 0.1, "aboiement": 0.7, "miaulement": 0.1},
                                   [{"label": "Bark", "score": 0.7}],
                                   [{"label": "Bark", "score": 0.7}]))
        detecteur._mesures.append((instant - 1.5, instant - 0.1, instant - 0.1,
                                   {"pleurs": 0.1, "aboiement": 0.1, "miaulement": 0.1},
                                   [{"label": "Speech", "score": 0.9}],
                                   [{"label": "Music", "score": 0.2}]))
        detecteur._derniers_sons["aboiement"] = instant - 2

        direct = detecteur.instantane()
        self.assertEqual(direct["aboiement_score"], 0.7)
        self.assertIn("aboiement", direct["sons_audio"])
        self.assertEqual(direct["son_general"], "Speech")
        self.assertEqual(direct["son_hors_parole"], "Bark")

        self.assertEqual(detecteur.instantane(depuis=instant - 1)["audio_statut"], "attente")


if __name__ == "__main__":
    unittest.main()
