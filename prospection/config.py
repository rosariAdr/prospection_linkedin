"""Chargement du fichier de configuration profil — SOURCE UNIQUE DE VÉRITÉ.

Avant la v1.0, la grille de scoring était recopiée dans trois fichiers et les seuils dans deux.
La dérive était inévitable : c'est comme ça que la blacklist a disparu des règles appliquées et
qu'une organisation blacklistée est ressortie en tête de classement (03-09-2026).

Désormais : un seul YAML par profil, lu par les scripts ET cité par les docs.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

try:
    import yaml
except ImportError:  # message utile plutôt qu'une stacktrace
    raise SystemExit("PyYAML est requis : pip install -r requirements.txt")

from .cles import norm

__all__ = ["Config", "charger", "CheminConfigIntrouvable"]

CHEMINS_PAR_DEFAUT = ("data/config.yaml", "data/config-adrian.yaml")

CLES_OBLIGATOIRES = ("profil", "scoring", "search_plan")


class CheminConfigIntrouvable(FileNotFoundError):
    pass


@dataclass
class Config:
    brut: dict[str, Any]
    chemin: str = ""
    _blacklist: set[str] = field(default_factory=set, repr=False)
    _observation: set[str] = field(default_factory=set, repr=False)

    def __post_init__(self) -> None:
        bl = self.brut.get("blacklist") or {}
        self._blacklist = {norm(x) for x in (bl.get("organisations") or [])}
        self._observation = {norm(x) for x in (bl.get("en_observation") or [])}

    # --- profil -------------------------------------------------------------
    @property
    def profil(self) -> dict[str, Any]:
        return self.brut["profil"]

    @property
    def nom(self) -> str:
        return self.profil.get("nom", "")

    # --- seuils -------------------------------------------------------------
    @property
    def seuil_conservation(self) -> float:
        return float(self.brut["scoring"]["seuil_conservation"])

    @property
    def seuil_redaction(self) -> float:
        """Strictement supérieur : un score ÉGAL au seuil ne déclenche pas la rédaction."""
        return float(self.brut["scoring"]["seuil_redaction"])

    def rediger_messages(self, score: float) -> bool:
        return float(score) > self.seuil_redaction

    def conserver(self, score: float) -> bool:
        return float(score) >= self.seuil_conservation

    # --- F4 -----------------------------------------------------------------
    def est_blacklistee(self, organisation: object) -> bool:
        n = norm(organisation)
        return any(b and b in n for b in self._blacklist)

    def est_en_observation(self, organisation: object) -> bool:
        n = norm(organisation)
        return any(o and o in n for o in self._observation)

    @property
    def competences_exclues(self) -> list[str]:
        return (self.brut.get("blacklist") or {}).get("competences_exclues") or []

    # --- search plan --------------------------------------------------------
    @property
    def mots_cles(self) -> list[str]:
        """Tous les mots-clés actifs, à plat, dans l'ordre des lots."""
        lots = self.brut["search_plan"].get("lots") or {}
        out: list[str] = []
        for nom_lot in sorted(lots):
            out += list(lots[nom_lot] or [])
        return out

    def lots(self, nb_agents: int = 3) -> list[list[str]]:
        """Répartit les mots-clés en `nb_agents` paquets d'égale taille."""
        kws = self.mots_cles
        if nb_agents < 1:
            raise ValueError("nb_agents doit valoir au moins 1")
        taille = -(-len(kws) // nb_agents)  # arrondi supérieur
        return [kws[i : i + taille] for i in range(0, len(kws), taille)]

    @property
    def noyau_prioritaire(self) -> list[str]:
        return self.brut["search_plan"].get("noyau_prioritaire") or []

    @property
    def mots_cles_retires(self) -> list[str]:
        return self.brut["search_plan"].get("retires") or []


def charger(chemin: str | None = None, racine: str = ".") -> Config:
    """Charge la config. Sans argument, cherche les chemins par défaut sous `racine`."""
    candidats = [chemin] if chemin else [os.path.join(racine, c) for c in CHEMINS_PAR_DEFAUT]
    for c in candidats:
        if c and os.path.exists(c):
            with open(c, encoding="utf-8") as fh:
                brut = yaml.safe_load(fh) or {}
            manquantes = [k for k in CLES_OBLIGATOIRES if k not in brut]
            if manquantes:
                raise ValueError(f"{c} : sections manquantes {manquantes}")
            return Config(brut=brut, chemin=c)
    raise CheminConfigIntrouvable(
        "Aucune configuration trouvée. Copiez templates/config-profil.example.yaml "
        "vers data/config.yaml et remplissez-le."
    )
