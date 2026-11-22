"""Clés de déduplication.

LinkedIn renvoie depuis août 2026 des liens raccourcis `lnkd.in/p/XXXX` dont le code change
à chaque capture : la déduplication par URL ne détecte plus rien. La clé qui fait foi est donc
une empreinte du CONTENU du post, calculée sur le texte brut au moment du harvest.

Cette empreinte est stockée en colonne `cle_contenu` du classeur, ce qui permet de dédupliquer
un run contre l'historique sans conserver le texte intégral de chaque post.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata

__all__ = ["norm", "cle_contenu", "cle_secours", "cle_url"]


def norm(s: object) -> str:
    """Normalise une chaîne : sans accents, sans casse, sans ponctuation ni espaces."""
    t = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", t.lower())


def cle_contenu(auteur: object, texte: object) -> str:
    """Clé principale : auteur + 90 premiers caractères normalisés du texte, hachés.

    Le hachage garde la clé courte et lisible en colonne, et évite de stocker du texte
    personnel supplémentaire dans le classeur.
    """
    brut = norm(auteur) + "|" + norm(texte)[:90]
    return hashlib.sha1(brut.encode()).hexdigest()[:16]


def cle_secours(texte: object) -> str:
    """Clé secondaire : le texte seul, pour rattraper un repost par un autre auteur."""
    return hashlib.sha1(norm(texte)[:120].encode()).hexdigest()[:16]


def cle_url(url: object) -> str:
    """URL normalisée (sans query string). Ne sert que de confirmation : un lien court
    `lnkd.in/p/XXXX` n'est PAS stable d'une capture à l'autre."""
    return str(url or "").split("?")[0].rstrip("/")
