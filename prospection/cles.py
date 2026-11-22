"""Clés de déduplication.

LinkedIn renvoie depuis août 2026 des liens raccourcis `lnkd.in/p/XXXX` dont le code change
à chaque capture : la déduplication par URL ne détecte plus rien. La clé qui fait foi est donc
une empreinte du CONTENU du post, calculée sur le texte brut au moment du harvest.

Cette empreinte est stockée en colonne `cle_contenu` du classeur, ce qui permet de dédupliquer
un run contre l'historique sans conserver le texte intégral de chaque post.

⚠️ Le texte harvesté est l'`innerText` de la carte ENTIÈRE : en-tête (auteur, titre, date
relative) puis corps du post. Les clés se calculent sur le corps seul (`corps_du_post`) : sinon
la clé change quand la date passe de « 3 j » à « 1 sem », et un titre long remplit à lui seul les
premiers caractères, si bien que deux annonces du même auteur se confondent.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata

from .dates import MOTIF_HORODATAGE

__all__ = ["norm", "corps_du_post", "cle_contenu", "cle_secours", "cle_url"]

# L'horodatage se cherche dans l'en-tête de carte, sur les 600 premiers caractères, comme
# `__dateOf` (scripts/harvester.js) et `extraire_du_texte_carte` (dates.py). `__dateOf` lit
# l'innerText brut et ce texte-ci est déjà compacté (espaces) : à la limite des 600 caractères,
# la date et la coupe peuvent donc différer.
_FENETRE_EN_TETE = 600


def norm(s: object) -> str:
    """Normalise une chaîne : sans accents, sans casse, sans ponctuation ni espaces."""
    t = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", t.lower())


def corps_du_post(texte: object) -> str:
    """Corps du post seul : ce qui suit le DERNIER horodatage (« 3 j • ») de l'en-tête.

    Sans horodatage — texte déjà propre, ou carte sans date lisible —, le texte est rendu tel
    quel.
    """
    t = str(texte or "")
    fin = None
    for m in MOTIF_HORODATAGE.finditer(t[:_FENETRE_EN_TETE]):
        fin = m.end()
    return t if fin is None else t[fin:]


def cle_contenu(auteur: object, texte: object) -> str:
    """Clé principale : auteur + 90 premiers caractères normalisés du corps, hachés.

    Le hachage garde la clé courte et lisible en colonne, et évite de stocker du texte
    personnel supplémentaire dans le classeur.
    """
    brut = norm(auteur) + "|" + norm(corps_du_post(texte))[:90]
    return hashlib.sha1(brut.encode()).hexdigest()[:16]


def cle_secours(texte: object) -> str:
    """Clé secondaire : le corps seul, pour rattraper un repost par un autre auteur."""
    return hashlib.sha1(norm(corps_du_post(texte))[:120].encode()).hexdigest()[:16]


def cle_url(url: object) -> str:
    """URL normalisée (sans query string). Ne sert que de confirmation : un lien court
    `lnkd.in/p/XXXX` n'est PAS stable d'une capture à l'autre."""
    return str(url or "").split("?")[0].rstrip("/")
