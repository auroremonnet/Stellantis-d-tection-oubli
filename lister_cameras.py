"""Affiche les index des caméras branchées, pour remplir config.json.

Une fenêtre s'ouvre par caméra : note quel index correspond à quelle position,
puis appuie sur une touche pour passer à la suivante.
"""
import os

import cv2

BACKEND = cv2.CAP_DSHOW if os.name == "nt" else cv2.CAP_ANY

for i in range(10):
    cap = cv2.VideoCapture(i, BACKEND)
    ok, f = cap.read()
    if ok:
        print(f"index {i} : {f.shape[1]}x{f.shape[0]}  {f.dtype}")
        cv2.imshow(f"index {i} - une touche pour continuer", f)
        cv2.waitKey(0)
        cv2.destroyAllWindows()
    cap.release()
