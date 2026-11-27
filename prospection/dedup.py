"""Déduplication d'un run : contre l'historique, puis à l'intérieur du run.

Ordre des clés, du plus fiable au moins fiable :
    1. `cle_contenu` (auteur + texte)  — la seule qui résiste aux liens raccourcis
    2. `cle_secours` (texte seul)      — rattrape un repost par un autre auteur
    3. `url_post`                      — confirmation uniquement
    4. `auteur`                        — dernier recours, et seulement pour SIGNALER un
                                         doublon d'organisation, jamais pour écarter en silence

⚠️ Ne JAMAIS dédupliquer sur `post_extrait` : c'est une reformulation écrite au scoring, pas le
texte brut du post. La clé de contenu calculée dessus ne correspondra jamais à celle d'un harvest.

Un CSV d'historique (MASTER, DELTA) se reconnaît à sa colonne `auteur`, présente dans `COLS` et
absente de `COLS_LEADS` (voir `workbook.py`). Les fichiers de travail — verrou d'Excel `~$…`,
écriture inachevée `….tmp` — ne sont jamais lus.
"""
from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass, field
from typing import Any, Iterable

from .cles import cle_contenu, cle_secours, cle_url, norm

__all__ = [
    "COLONNE_HISTORIQUE", "Historique", "charger_candidats", "dedupliquer", "est_csv_historique",
    "nom_ignore", "RapportDedup",
]

# colonne qui distingue un CSV d'historique (MASTER, DELTA) d'un export SUIVI_LEADS
COLONNE_HISTORIQUE = "auteur"


def nom_ignore(chemin: str) -> bool:
    """Fichier de travail à ne jamais lire : verrou d'Excel (`~$…`) ou écriture inachevée (`….tmp`)."""
    nom = os.path.basename(chemin)
    return nom.startswith("~$") or nom.lower().endswith(".tmp")


def est_csv_historique(chemin: str) -> bool:
    """Vrai si le CSV est un historique au format `COLS` (MASTER, DELTA) : il a une colonne `auteur`.

    Seul l'en-tête est lu, en `utf-8-sig` (un BOM collerait au nom de la première colonne). Un
    fichier de travail (`~$…`, `….tmp`) n'en est jamais un. Un fichier illisible lève son
    exception : à l'appelant de bloquer.
    """
    if nom_ignore(chemin):
        return False
    with open(chemin, encoding="utf-8-sig", newline="") as fh:
        entete = next(csv.reader(fh), [])
    return COLONNE_HISTORIQUE in entete


@dataclass
class Historique:
    """Ensemble des clés déjà connues, chargé depuis les classeurs/CSV et les runs passés.

    `ignores` liste les fichiers écartés sans être lus (fichiers de travail, et en lecture
    stricte les CSV qui ne sont pas un historique), pour que l'appelant les signale.
    `cles_json` compte à part les clés de contenu recalculées depuis des JSON bruts (une par
    candidat), et `json_lus` le nombre de ces JSON.
    """

    contenus: set[str] = field(default_factory=set)
    secours: set[str] = field(default_factory=set)
    urls: set[str] = field(default_factory=set)
    auteurs: set[str] = field(default_factory=set)
    ignores: list[str] = field(default_factory=list)
    cles_json: int = 0
    json_lus: int = 0

    def connait(self, c: dict[str, Any]) -> str | None:
        """Renvoie le nom de la clé qui a matché, ou None."""
        if cle_contenu(c.get("auteur"), c.get("texte")) in self.contenus:
            return "cle_contenu"
        if cle_secours(c.get("texte")) in self.secours:
            return "cle_secours"
        u = cle_url(c.get("url_post"))
        if u and u in self.urls:
            return "url_post"
        return None

    def meme_organisation(self, c: dict[str, Any]) -> bool:
        return norm(c.get("auteur")) in self.auteurs

    # -- chargement ----------------------------------------------------------
    def ajouter_csv(self, chemin: str, stricte: bool = False) -> int:
        """Lit un CSV MASTER/DELTA. Utilise `cle_contenu` si la colonne existe.

        Lecture en `utf-8-sig` : un CSV réenregistré par Excel commence par un BOM, qui collerait
        au nom de la première colonne (`cle_contenu` ou `auteur` y seraient introuvables). Sans
        BOM, rien ne change. Un fichier de travail (`~$…`, `….tmp`) n'est jamais lu.

        `stricte` (mode partagé) : un CSV sans colonne `auteur` — un export SUIVI_LEADS, par
        exemple — n'est pas un historique : il n'est pas lu et rejoint `ignores`. Par défaut
        (mode local), tout CSV est lu comme aujourd'hui : SUIVI_LEADS y apporte ses `url_post`.
        Un fichier illisible lève son exception : jamais de repli silencieux.
        """
        if not os.path.exists(chemin):
            return 0
        if nom_ignore(chemin):
            self.ignores.append(chemin)
            return 0
        n = 0
        with open(chemin, encoding="utf-8-sig") as fh:
            lecteur = csv.DictReader(fh)
            if stricte and COLONNE_HISTORIQUE not in (lecteur.fieldnames or []):
                self.ignores.append(chemin)
                return 0
            for row in lecteur:
                n += 1
                if row.get("cle_contenu"):
                    self.contenus.add(row["cle_contenu"])
                if row.get("cle_secours"):
                    self.secours.add(row["cle_secours"])
                if row.get("url_post"):
                    self.urls.add(cle_url(row["url_post"]))
                if row.get("auteur"):
                    self.auteurs.add(norm(row["auteur"]))
        return n

    def ajouter_xlsx(self, chemin: str, onglet: str = "MASTER") -> int:
        if not os.path.exists(chemin):
            return 0
        if nom_ignore(chemin):  # `~$prospection_….xlsx` : le classeur est ouvert dans Excel
            self.ignores.append(chemin)
            return 0
        import openpyxl

        wb = openpyxl.load_workbook(chemin, read_only=True)
        if onglet not in wb.sheetnames:
            return 0
        ws = wb[onglet]
        lignes = ws.iter_rows(values_only=True)
        cols = [c for c in next(lignes, [])]
        idx = {c: i for i, c in enumerate(cols) if c}
        n = 0
        for r in lignes:
            n += 1
            for nom_col, cible in (("cle_contenu", self.contenus), ("cle_secours", self.secours)):
                i = idx.get(nom_col)
                if i is not None and r[i]:
                    cible.add(str(r[i]))
            i = idx.get("url_post")
            if i is not None and r[i]:
                self.urls.add(cle_url(r[i]))
            i = idx.get("auteur")
            if i is not None and r[i]:
                self.auteurs.add(norm(r[i]))
        return n

    def ajouter_run(self, chemin: str) -> int:
        """Ajoute les candidats bruts d'un run passé (JSON d'agent).

        Les clés sont recalculées sur le texte brut, avec la règle de clé en vigueur : elles
        sont comptées à part (`cles_json`), car elles rattrapent les clés périmées d'un DELTA.
        """
        if not os.path.exists(chemin):
            return 0
        if nom_ignore(chemin):
            self.ignores.append(chemin)
            return 0
        cands = charger_candidats([chemin])
        for c in cands:
            self.contenus.add(cle_contenu(c.get("auteur"), c.get("texte")))
            self.secours.add(cle_secours(c.get("texte")))
            if c.get("url_post"):
                self.urls.add(cle_url(c["url_post"]))
            self.auteurs.add(norm(c.get("auteur")))
        self.json_lus += 1
        self.cles_json += len(cands)
        return len(cands)


def _normaliser_candidat(c: dict[str, Any], mot_cle: str = "") -> dict[str, Any]:
    """Tolère les abréviations utilisées par les agents (a/pr/l/d/t)."""
    return {
        "auteur": c.get("auteur") or c.get("a") or "",
        "profil": c.get("profil") or c.get("pr") or "",
        "url_post": c.get("url_post") or c.get("link") or c.get("l") or "",
        "date_rel": c.get("date_rel") or c.get("d") or "",
        "texte": c.get("texte") or c.get("t") or "",
        "mot_cle": c.get("mot_cle") or mot_cle,
    }


def charger_candidats(chemins: Iterable[str]) -> list[dict[str, Any]]:
    """Lit les JSON produits par les agents, quelle que soit leur forme (voir §12 de la recette)."""
    out: list[dict[str, Any]] = []
    for f in chemins:
        if not os.path.exists(f):
            continue
        with open(f, encoding="utf-8") as fh:
            d = json.load(fh)
        if isinstance(d, dict) and "resultats" in d:
            for r in d["resultats"]:
                for c in r.get("candidats", []):
                    out.append(_normaliser_candidat(c, r.get("mot_cle", "")))
        elif isinstance(d, dict) and "candidats" in d:
            for c in d["candidats"]:
                out.append(_normaliser_candidat(c))
        elif isinstance(d, list):
            for c in d:
                out.append(_normaliser_candidat(c))
    return out


@dataclass
class RapportDedup:
    bruts: int = 0
    hors_fenetre: int = 0
    deja_connus: int = 0
    doublons_internes: int = 0
    nouveaux: int = 0
    meme_organisation: list[str] = field(default_factory=list)

    def resume(self) -> str:
        return (
            f"bruts={self.bruts} hors_fenetre={self.hors_fenetre} "
            f"deja_connus={self.deja_connus} doublons_internes={self.doublons_internes} "
            f"nouveaux={self.nouveaux}"
        )


def dedupliquer(
    candidats: list[dict[str, Any]],
    historique: Historique | None = None,
    jours_max: float | None = None,
) -> tuple[list[dict[str, Any]], RapportDedup]:
    """Filtre par date, puis écarte les doublons historiques et internes.

    Les doublons d'ORGANISATION ne sont pas écartés : ils sont signalés dans le rapport, pour
    que le scoring décide (garder les deux lignes, ne rédiger qu'une candidature).
    """
    from .dates import dans_fenetre

    hist = historique or Historique()
    rap = RapportDedup(bruts=len(candidats))
    vus: set[str] = set()
    gardes: list[dict[str, Any]] = []

    for c in candidats:
        if jours_max is not None and not dans_fenetre(c.get("date_rel"), jours_max):
            rap.hors_fenetre += 1
            continue
        if hist.connait(c):
            rap.deja_connus += 1
            continue
        k = cle_contenu(c.get("auteur"), c.get("texte"))
        if k in vus:
            rap.doublons_internes += 1
            continue
        vus.add(k)
        c["cle_contenu"] = k
        c["cle_secours"] = cle_secours(c.get("texte"))
        if hist.meme_organisation(c):
            c["deja_en_suivi"] = True
            rap.meme_organisation.append(c.get("auteur", ""))
        gardes.append(c)

    rap.nouveaux = len(gardes)
    return gardes, rap


def rendement_par_mot_cle(candidats: list[dict[str, Any]]) -> list[tuple[str, int]]:
    """Nombre de candidats bruts par mot-clé — sert à recomposer le noyau prioritaire."""
    from collections import Counter

    cnt = Counter(c.get("mot_cle") or "?" for c in candidats)
    return cnt.most_common()
