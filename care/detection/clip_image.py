"""Tour image de MobileCLIP-B, reconstruite à partir de `mobileclip_blt.ts`.

Ce fichier est déjà sur le banc : YOLOE s'en sert pour encoder ses mots-clés. Il contient
aussi les poids de l'encodeur d'IMAGES de MobileCLIP (ViT-B/16, 86 M de paramètres), mais
pas son code : la version TorchScript distribuée par Ultralytics n'exporte que le texte.
On réécrit donc ici le calcul (une soixantaine de lignes, d'après le code publié par Apple,
https://github.com/apple/ml-mobileclip) et on y charge les poids du fichier. Aucun
téléchargement ni dépendance de plus, et on obtient un classifieur « image ↔ description »
de très bon niveau, sans entraînement.

Vérifié contre l'implémentation de référence d'Apple : mêmes empreintes à 1e-5 près.
"""
from __future__ import annotations

import cv2
import numpy as np
import torch
import torch.nn.functional as F
from torch import nn

TAILLE = 224
PREFIXE = "image_encoder.model."


class _Bloc(nn.Module):
    """Bloc Transformer « pré-norme » (attention puis MLP, chacun avec connexion résiduelle)."""

    def __init__(self, dim: int, tetes: int):
        super().__init__()
        self.tetes = tetes
        self.norme1, self.norme2 = nn.LayerNorm(dim), nn.LayerNorm(dim)
        self.qkv, self.sortie = nn.Linear(dim, 3 * dim), nn.Linear(dim, dim)
        self.mlp1, self.mlp2 = nn.Linear(dim, 4 * dim), nn.Linear(4 * dim, dim)

    def forward(self, x):
        n, s, c = x.shape
        qkv = self.qkv(self.norme1(x)).reshape(n, s, 3, self.tetes, c // self.tetes).transpose(1, 3)
        a = F.scaled_dot_product_attention(qkv[:, :, 0], qkv[:, :, 1], qkv[:, :, 2])
        x = x + self.sortie(a.transpose(1, 2).reshape(n, s, c))
        return x + self.mlp2(F.gelu(self.mlp1(self.norme2(x))))


class TourImage(nn.Module):
    """ViT-B/16 à tige convolutive (4-2-2) de MobileCLIP-B → empreinte de 512 valeurs."""

    def __init__(self, dim: int = 768, couches: int = 12, tetes: int = 12, sortie: int = 512):
        super().__init__()
        self.conv1, self.bn1 = nn.Conv2d(3, dim // 4, 4, 4, padding=1, bias=False), nn.BatchNorm2d(dim // 4)
        self.conv2, self.bn2 = nn.Conv2d(dim // 4, dim // 4, 2, 2, bias=False), nn.BatchNorm2d(dim // 4)
        self.conv3 = nn.Conv2d(dim // 4, dim, 2, 2)
        self.jeton = nn.Parameter(torch.zeros(1, 1, dim))
        self.position = nn.Parameter(torch.zeros(1, (TAILLE // 16) ** 2, dim))
        self.blocs = nn.ModuleList(_Bloc(dim, tetes) for _ in range(couches))
        self.norme = nn.LayerNorm(dim)
        self.projection = nn.Parameter(torch.zeros(dim, sortie))

    def forward(self, x):
        x = F.gelu(self.bn1(self.conv1(x)))
        x = F.gelu(self.bn2(self.conv2(x)))
        x = self.conv3(x)
        cote = x.shape[-1]
        x = x.flatten(2).transpose(1, 2) + self._positions(cote)       # pas de position sur le jeton
        x = torch.cat([self.jeton.expand(x.shape[0], -1, -1), x], dim=1)
        for bloc in self.blocs:
            x = bloc(x)
        return self.norme(x)[:, 0] @ self.projection

    def _positions(self, cote: int):
        """Positions apprises pour une grille 14×14 ; ré-échantillonnées si l'image est plus petite."""
        n = int(self.position.shape[1] ** 0.5)
        if cote == n:
            return self.position
        grille = self.position.reshape(1, n, n, -1).permute(0, 3, 1, 2)
        grille = F.interpolate(grille, size=(cote, cote), mode="bicubic", align_corners=False)
        return grille.permute(0, 2, 3, 1).reshape(1, cote * cote, -1)

    @classmethod
    def depuis_torchscript(cls, etat: dict) -> TourImage:
        """Construit la tour à partir du `state_dict()` de mobileclip_blt.ts."""
        if PREFIXE + "cls_token" not in etat:
            raise ValueError("Ce fichier MobileCLIP ne contient pas l'encodeur d'images "
                             "(attendu : mobileclip_blt.ts).")
        g = lambda k: etat[PREFIXE + k]  # noqa: E731
        m = cls()
        with torch.no_grad():
            poids = {"jeton": g("cls_token"), "position": g("pos_embed.pos_embed.pos_embed")[0],
                     "projection": g("classifier.proj"),
                     "conv1.weight": g("patch_emb.0.block.conv.weight"),
                     "conv2.weight": g("patch_emb.1.block.conv.weight"),
                     "conv3.weight": g("patch_emb.2.block.conv.weight"),
                     "conv3.bias": g("patch_emb.2.block.conv.bias"),
                     "norme.weight": g("post_transformer_norm.weight"),
                     "norme.bias": g("post_transformer_norm.bias")}
            for i in (1, 2):
                for champ in ("weight", "bias", "running_mean", "running_var"):
                    poids[f"bn{i}.{champ}"] = g(f"patch_emb.{i - 1}.block.norm.{champ}")
            noms = {"norme1": "pre_norm_mha.0", "qkv": "pre_norm_mha.1.qkv_proj", "sortie": "pre_norm_mha.1.out_proj",
                    "norme2": "pre_norm_ffn.0", "mlp1": "pre_norm_ffn.1", "mlp2": "pre_norm_ffn.4"}
            for i in range(len(m.blocs)):
                for ici, la in noms.items():
                    for champ in ("weight", "bias"):
                        poids[f"blocs.{i}.{ici}.{champ}"] = g(f"transformer.{i}.{la}.{champ}")
            manquants, inattendus = m.load_state_dict({k: v.float() for k, v in poids.items()}, strict=False)
            manquants = [k for k in manquants if "num_batches_tracked" not in k]
            if manquants or inattendus:
                raise ValueError(f"Poids MobileCLIP incompatibles : {manquants or inattendus}")
        return m.eval()


def preparer(images_bgr, taille: int = TAILLE) -> torch.Tensor:
    """Images BGR (OpenCV) carrées → tenseur N×3×taille×taille dans [0, 1] (MobileCLIP ne centre pas)."""
    lot = np.stack([cv2.cvtColor(cv2.resize(i, (taille, taille), interpolation=cv2.INTER_AREA
                                            if i.shape[0] > taille else cv2.INTER_CUBIC), cv2.COLOR_BGR2RGB)
                    for i in images_bgr])
    return torch.from_numpy(lot).permute(0, 3, 1, 2).float().div_(255.0)
