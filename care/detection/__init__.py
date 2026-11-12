"""Détection RGB du banc CARE : localiser → nommer → trancher.

    catalogue.py       vocabulaire (classes, mots du détecteur, descriptions du classifieur)
    moteurs.py         modèles et inférence (moteur « care » + moteurs historiques)
    clip_image.py      encodeur d'images MobileCLIP reconstruit depuis mobileclip_blt.ts
    classifieur.py     recadrage → probabilité par classe
    identification.py  règles pures : propositions + classifieur → détections
    changement.py      comparaison à la référence « habitacle vide »
    essai.py           analyse d'un essai multi-caméras
    rendu.py           images annotées, mosaïque
    geometrie.py       boîtes englobantes

Le reste du banc passe par la façade `care.detecteur.Detecteur`.
"""
