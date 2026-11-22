"""Lecture des dates relatives affichées par LinkedIn.

⚠️ Piège documenté (docs/04-recette-scraping.md §8) : un `match` naïf sur le texte de la carte
attrape le premier nombre venu — « 3 ans d'expérience », « +1 500 personnes formées » — et
écarte à tort des annonces fraîches. L'horodatage LinkedIn est TOUJOURS suivi du séparateur
« • », et c'est la DERNIÈRE occurrence de ce motif qui est la bonne.

Règle de sûreté : une date illisible ne fait jamais sortir un post du run.
"""
from __future__ import annotations

import re

__all__ = ["JOURS_PAR_UNITE", "parse_date_relative", "dans_fenetre", "MOTIF_HORODATAGE"]

MOTIF_HORODATAGE = re.compile(r"(\d+)\s*(min|h|j|sem|mois|an)s?\s*(?=•)")

JOURS_PAR_UNITE = {"min": 0.0, "h": 0.0, "j": 1.0, "sem": 7.0, "mois": 30.0, "an": 365.0}


def parse_date_relative(valeur: object) -> float | None:
    """Convertit « 3 j », « 2 sem », « 19 h » en nombre de jours.

    Renvoie None si la valeur est vide ou illisible — l'appelant doit alors CONSERVER le post.
    """
    txt = str(valeur or "").strip()
    if not txt:
        return None
    m = re.match(r"(\d+)\s*(min|h|j|sem|mois|an)", txt)
    if not m:
        return None
    return int(m.group(1)) * JOURS_PAR_UNITE[m.group(2)]


def dans_fenetre(valeur: object, jours_max: float) -> bool:
    """True si le post est dans la fenêtre. Date illisible ⇒ True (on garde)."""
    j = parse_date_relative(valeur)
    return True if j is None else j <= jours_max


def extraire_du_texte_carte(texte_carte: str) -> str:
    """Équivalent Python de `window.__dateOf` — utile pour retraiter un harvest ancien."""
    trouves = MOTIF_HORODATAGE.findall((texte_carte or "")[:600])
    if not trouves:
        return ""
    n, u = trouves[-1]
    return f"{n} {u}"
