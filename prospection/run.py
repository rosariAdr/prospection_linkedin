"""Orchestration d'un run, en deux temps.

Le scoring et la rédaction sont faits par des agents entre les deux commandes : ce sont les
seules étapes qui demandent du jugement, tout le reste est déterministe et scripté.

    python -m prospection.run prepare   --run 23-09-2026 --jours 21
    …  (les agents scorent <dossier du run>/a_scorer.json → scored_*.json)  …
    python -m prospection.run finaliser --run 23-09-2026

`prepare`   : lit les JSON des agents de scraping, filtre par date, déduplique contre
              l'historique, écrit `a_scorer.json` et le rendement par mot-clé, et signale un
              run incomplet (mots-clés non traités qu'aucune reprise n'a couverts).
`finaliser` : relit les `scored_*.json`, passe les garde-fous, construit le classeur et
              exporte les CSV d'archive.

Emplacement des données (`emplacements.py`) : mode local par défaut (`data/` et `runs/` sous la
racine), ou mode partagé avec `--donnees <dossier>` (avant ou après la sous-commande) ou la
variable PROSPECTION_DONNEES : un dossier sur un Drive, commun à plusieurs PC. Chaque commande
annonce son mode en première ligne. En mode partagé :
  - l'identifiant de run est strict : JJ-MM-AAAA, ou JJ-MM-AAAA-n avec n ≥ 2 ;
  - la config est `<donnees>/config.yaml`, pour tous les postes : `--config` est refusé ;
  - `lots --run`, `prepare` et `finaliser` prennent le verrou du dossier, `finaliser` le libère ;
    `lots --run` et `prepare` refusent un run déjà finalisé ou préparé sur un autre poste ;
  - un run n'écrit que ses propres fichiers : son dossier de run, `historique/DELTA_<run>.csv`
    et `classeurs/prospection_<run>.xlsx` ; aucun export MASTER.csv ni SUIVI_LEADS.csv ;
  - un fichier illisible ou une copie en conflit dans une zone critique bloque : jamais de
    repli silencieux.

Codes de sortie : 0 succès · 1 rien à traiter · 2 refus (garde-fou, emplacement, fichier
illisible, contrôle bloquant) · 3 verrou ou run tenu par un autre poste.
"""
from __future__ import annotations

import argparse
import csv
import fnmatch
import glob
import json
import os
import re
import socket
import sys
import zipfile
from datetime import datetime, timezone
from typing import Any, Callable

# config d'abord : sans PyYAML, sa garde dit « PyYAML est requis : pip install … » au lieu d'une
# trace Python. Pas d'`import yaml` ici : `cfg_mod.yaml` sert pour YAMLError.
from . import __version__, config as cfg_mod, verrou
from openpyxl.utils.exceptions import InvalidFileException
from .cles import norm
from .dedup import Historique, charger_candidats, dedupliquer, nom_ignore, rendement_par_mot_cle
from .emplacements import (
    DonneesMigrees,
    DossierDonneesDansLeDepot,
    DossierDonneesIntrouvable,
    DossierDonneesNonInitialise,
    Emplacements,
    resoudre,
)
from .verify import controler
from .workbook import COLS, COLS_LEADS, construire, lire_historique_csv, run_du_fichier

RACINE_RUNS = "runs"
PROPRIETAIRE = "proprietaire.json"  # mode partagé : le poste qui a préparé le run
# JSON d'un dossier de run qui ne viennent pas des agents de scraping
NON_BRUTS = ("a_scorer", "scored_", "rapport")
NON_BRUTS_PARTAGE = NON_BRUTS + ("proprietaire",)

# identifiant de run partagé : JJ-MM-AAAA, ou JJ-MM-AAAA-n avec n ≥ 2 (sans zéro en tête)
_RUN = re.compile(r"(\d{2}-\d{2}-\d{4})(?:-([2-9]|[1-9]\d+))?")
_CLASSEUR = re.compile(r"prospection_(.+)\.xlsx", re.IGNORECASE)
# copie en conflit d'un Drive : « config (1).yaml », « DELTA_x (2).csv », « verrou (1).json »
_CONFLIT = re.compile(r".+ \(\d+\)(\.[^.\s]+)?")

ERREURS_EMPLACEMENT = (
    DossierDonneesIntrouvable, DossierDonneesNonInitialise, DossierDonneesDansLeDepot,
    DonneesMigrees,
)
# ce qui peut sortir de la lecture d'un fichier de données : absent hors connexion, encodage,
# JSON ou CSV invalides, classeur qui n'est pas un zip, structure inattendue
ERREURS_LECTURE = (
    OSError, ValueError, KeyError, TypeError, AttributeError, csv.Error, zipfile.BadZipFile,
    InvalidFileException,
)


class Refus(RuntimeError):
    """Contrôle bloquant : message sur stderr, rien d'écrit, code de sortie `code`."""

    code = 2


class FichierIllisible(Refus):
    """Mode partagé : un fichier de données ne se lit pas. On le nomme, et on s'arrête."""

    def __init__(self, chemin: str, exc: BaseException) -> None:
        super().__init__(
            f"fichier illisible : {chemin} ({type(exc).__name__} : {exc}). Sur un Drive, le "
            "rendre « disponible hors connexion » ou rétablir la connexion ; sinon le réparer. "
            "Aucun repli silencieux : rien n'a été écrit."
        )
        self.chemin = chemin


class RunAilleurs(Refus):
    """Mode partagé : le run a été préparé sur un autre poste (`proprietaire.json`)."""

    code = 3


# --- outils ------------------------------------------------------------------------------------

def cle_run(run: str) -> tuple[datetime, int] | None:
    """Clé d'ordre d'un identifiant de run partagé : (date, n), ou None hors format.

    `JJ-MM-AAAA` vaut n = 1, `JJ-MM-AAAA-n` exige n ≥ 2. La date est ANALYSÉE (`strptime`) :
    en ordre lexical, « 02-01-2030 » passerait avant « 15-12-2029 ».
    """
    m = _RUN.fullmatch(run or "")
    if not m:
        return None
    try:
        date = datetime.strptime(m.group(1), "%d-%m-%Y")
    except ValueError:
        return None
    return date, int(m.group(2) or 1)


def _valider_run(run: str) -> tuple[datetime, int]:
    k = cle_run(run)
    if k is None:
        raise Refus(
            f"identifiant de run invalide : « {run} ». En mode partagé : JJ-MM-AAAA, ou "
            "JJ-MM-AAAA-n avec n ≥ 2 pour un second run le même jour (ex. 23-09-2026, "
            "23-09-2026-2)."
        )
    return k


def copie_en_conflit(chemin: str) -> bool:
    """Vrai pour une copie en conflit d'un Drive (`config (1).yaml`), jamais pour un fichier de travail."""
    return not nom_ignore(chemin) and bool(_CONFLIT.fullmatch(os.path.basename(chemin)))


def _copies_en_conflit(dossier: str | None, motif: str = "*") -> list[str]:
    if not dossier or not os.path.isdir(dossier):
        return []
    return sorted(
        os.path.join(dossier, n) for n in os.listdir(dossier)
        if copie_en_conflit(n) and fnmatch.fnmatch(n.lower(), motif)
    )


def _emplacements(args: argparse.Namespace) -> Emplacements:
    return resoudre(args.racine, getattr(args, "donnees", None))


def _lire(chemin: str, lecture: Callable[..., Any], *a: Any, **kw: Any) -> Any:
    """Mode partagé : lit `chemin` avec `lecture`, ou lève FichierIllisible en le nommant."""
    try:
        return lecture(chemin, *a, **kw)
    except ERREURS_LECTURE as exc:
        raise FichierIllisible(chemin, exc) from exc


def _json(chemin: str) -> Any:
    # utf-8-sig : un JSON réenregistré par le Bloc-notes porte un BOM (comme le verrou)
    with open(chemin, encoding="utf-8-sig") as fh:
        return json.load(fh)


def _fichiers(dossier: str, motif: str) -> list[str]:
    # glob.escape : un chemin de Drive peut contenir des crochets
    return sorted(glob.glob(os.path.join(glob.escape(dossier), motif)))


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _charger_config(args: argparse.Namespace, emp: Emplacements) -> cfg_mod.Config:
    """Mode local : recherche d'aujourd'hui. Mode partagé : `<donnees>/config.yaml`, même s'il manque.

    En mode partagé, `--config` est refusé : la config est celle du dossier de données, la même
    pour tous les postes et celle que contrôle `poste`. Un `--config data/config.yaml` resté dans
    un prompt ou un historique de commandes ferait filtrer avec une blacklist périmée.
    """
    if emp.mode != "partage":
        return cfg_mod.charger(args.config, racine=args.racine)
    chemin = emp.config
    if args.config:
        raise Refus(
            f"--config ne s'emploie pas en mode partagé : la config est {chemin}, la même pour "
            "tous les postes (c'est elle que contrôle `poste`). Retirer --config ; pour changer "
            "la config, modifier ce fichier."
        )
    if not os.path.isfile(chemin):
        raise Refus(
            f"config introuvable : {chemin}. Le dossier de données doit contenir config.yaml : "
            "le préparer avec `python -m prospection.run initialiser-donnees --vers <dossier>`, "
            "depuis un PC qui a la config."
        )
    try:
        return cfg_mod.charger(chemin)
    except (cfg_mod.yaml.YAMLError, ValueError) as exc:
        raise Refus(f"config invalide : {chemin} ({exc})") from exc
    except OSError as exc:
        raise FichierIllisible(chemin, exc) from exc


# --- historique --------------------------------------------------------------------------------

def _dossier_run(run: str, runs: str = RACINE_RUNS) -> str:
    d = os.path.join(runs, run)
    os.makedirs(d, exist_ok=True)
    return d


def _historique(racine: str, run_courant: str) -> Historique:
    """Mode local : les sources d'aujourd'hui, inchangées."""
    h = Historique()
    n = 0
    for motif in ("data/*.xlsx", "*.xlsx"):
        for f in glob.glob(os.path.join(racine, motif)):
            n += h.ajouter_xlsx(f)
    for f in glob.glob(os.path.join(racine, "data", "*.csv")):
        n += h.ajouter_csv(f)
    for d in sorted(glob.glob(os.path.join(racine, RACINE_RUNS, "*"))):
        if os.path.basename(d) == run_courant:
            continue
        for f in glob.glob(os.path.join(d, "*.json")):
            if os.path.basename(f).startswith(NON_BRUTS):
                continue
            n += h.ajouter_run(f)
    print(f"historique : {n} lignes lues, {len(h.contenus)} clés de contenu, {len(h.auteurs)} auteurs")
    return h


def _classeurs(dossier: str) -> list[tuple[tuple[datetime, int], str]]:
    """Classeurs `prospection_<run>.xlsx` d'un dossier, triés par (date analysée, n)."""
    if not os.path.isdir(dossier):
        return []
    out = []
    for nom in os.listdir(dossier):
        m = _CLASSEUR.fullmatch(nom)
        k = cle_run(m.group(1)) if m and not nom_ignore(nom) else None
        if k is not None:
            out.append((k, os.path.join(dossier, nom)))
    return sorted(out)


def _base_calculee(emp: Emplacements, run: str) -> str | None:
    """Classeur de base d'un run partagé.

    Le classeur du run lui-même s'il existe (une refinalisation garde les labels saisis), sinon
    le plus récent STRICTEMENT avant le run, sinon None (classeur vide).
    """
    propre = os.path.join(emp.classeurs, f"prospection_{run}.xlsx")
    if os.path.exists(propre):
        return propre
    k = cle_run(run)
    avant = [c for kc, c in _classeurs(emp.classeurs) if k is not None and kc < k]
    return avant[-1] if avant else None


def _historique_partage(emp: Emplacements, run: str) -> Historique:
    """Mode partagé : `historique/*.csv` reconnus (copies en conflit comprises), JSON bruts des
    autres runs, MASTER du classeur de base. Un fichier illisible bloque."""
    h = Historique()
    n = 0
    csvs = _fichiers(emp.historique, "*.csv")
    for f in csvs:
        n += _lire(f, h.ajouter_csv, stricte=True)
    for d in _fichiers(emp.runs, "*"):
        if os.path.basename(d) == run or not os.path.isdir(d):
            continue
        for f in _fichiers(d, "*.json"):
            if not os.path.basename(f).startswith(NON_BRUTS_PARTAGE):
                n += _lire(f, h.ajouter_run)
    base = _base_calculee(emp, run)
    if base:
        n += _lire(base, h.ajouter_xlsx)
    print(f"historique : {n} lignes lues, {len(h.contenus)} clés de contenu, {len(h.auteurs)} auteurs")
    print(f"  dont {h.cles_json} clé(s) recalculée(s) depuis {h.json_lus} JSON brut(s) d'anciens runs")
    print(f"  classeur de base : {base or 'aucun'}")
    if h.ignores:
        print("  ignoré(s) (fichier de travail, ou CSV sans colonne auteur) : "
              + ", ".join(os.path.basename(f) for f in h.ignores))
    conflits = [f for f in csvs if copie_en_conflit(f)]
    if conflits:
        print("AVERTISSEMENT : copie(s) en conflit lue(s) dans historique/ (union des clés, la plus "
              "prudente) : " + ", ".join(os.path.basename(f) for f in conflits)
              + ". Les fusionner avant de finaliser.", file=sys.stderr)
    if n == 0:
        print("AVERTISSEMENT : historique vide en mode partagé : aucune déduplication contre les "
              "runs passés. Le dossier de données a-t-il été initialisé avec initialiser-donnees ?",
              file=sys.stderr)
    return h


# --- verrou et propriétaire (mode partagé) -----------------------------------------------------

def _proprietaire_etranger(d: str) -> str | None:
    """Poste qui a préparé le run s'il n'est pas celui-ci, sinon None (ou pas de propriétaire)."""
    f = os.path.join(d, PROPRIETAIRE)
    if not os.path.exists(f):
        return None
    p = _lire(f, _json)
    poste = p.get("poste") if isinstance(p, dict) else None
    return None if poste and poste == socket.gethostname() else str(poste or "?")


def _controle_occupation(emp: Emplacements, run: str, d: str, forcer: bool) -> str | None:
    """Verrou et propriétaire, sans rien écrire. Renvoie le propriétaire étranger forcé, s'il y en a un."""
    if not forcer:
        occ = verrou.occupants(emp.racine_donnees, run)
        if occ:
            lignes = "\n".join(f"  {verrou.decrire(e)}" for e in occ)
            raise verrou.VerrouOccupe(
                f"verrou occupé : un autre run est en cours, ou le verrou est illisible.\n{lignes}\n"
                "Attendre la fin de ce run (et que le Drive soit à jour). S'il est abandonné : "
                "`python -m prospection.run verrou liberer --forcer`, ou relancer avec --forcer.",
                occ,
            )
    etranger = _proprietaire_etranger(d)
    if etranger is not None:
        if not forcer:
            raise RunAilleurs(
                f"le run {run} a été préparé sur le poste {etranger} : le finir sur ce poste, ou "
                "relancer avec --forcer pour le reprendre ici."
            )
        print(f"AVERTISSEMENT : run {run} repris au poste {etranger} (--forcer)", file=sys.stderr)
    return etranger


def _verrou_inecrivable(dossier: str, exc: OSError) -> str:
    return (f"impossible d'écrire le verrou dans {dossier} ({exc}) : dossier en lecture seule, ou "
            "fichier verrouillé par la synchronisation du Drive. Attendre que le Drive soit à "
            "jour, puis relancer.")


def _prendre(dossier: str, run: str, commande: str, ttl_heures: float = verrou.TTL_HEURES,
             forcer: bool = False) -> dict[str, Any]:
    """`verrou.prendre`, avec un message humain si le Drive refuse l'écriture du verrou."""
    try:
        return verrou.prendre(dossier, run, commande, ttl_heures, forcer)
    except OSError as exc:
        raise Refus(_verrou_inecrivable(dossier, exc)) from exc


def _controle_deja_finalise(emp: Emplacements, run: str, forcer: bool) -> None:
    """`historique/DELTA_<run>.csv` présent : le run est fini. Le reprendre mélangerait deux runs."""
    delta = os.path.join(emp.historique, f"DELTA_{run}.csv")
    if not os.path.exists(delta):
        return
    if not forcer:
        raise Refus(
            f"le run {run} est déjà finalisé ({delta} présent) : le reprendre mélangerait deux "
            "runs. Prendre un autre identifiant (JJ-MM-AAAA-n), ou relancer avec --forcer."
        )
    print(f"AVERTISSEMENT : run {run} déjà finalisé, repris (--forcer)", file=sys.stderr)


def _ecrire_proprietaire(d: str, etranger: str | None) -> None:
    f = os.path.join(d, PROPRIETAIRE)
    if os.path.exists(f) and etranger is None:
        return
    # écriture atomique : une écriture coupée ne laisse jamais un JSON tronqué, qui bloquerait le run
    tmp = f + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"poste": socket.gethostname(), "depuis": _maintenant()}, fh,
                      ensure_ascii=False, indent=1)
        os.replace(tmp, f)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


# --- prepare -----------------------------------------------------------------------------------

def cmd_prepare(args: argparse.Namespace) -> int:
    emp = _emplacements(args)
    print(emp.ligne_mode())
    partage = emp.mode == "partage"
    if partage:
        _valider_run(args.run)
    cfg = _charger_config(args, emp)
    d = os.path.join(emp.runs, args.run)
    etranger = None
    if partage:
        etranger = _controle_occupation(emp, args.run, d, args.forcer)
        _controle_deja_finalise(emp, args.run, args.forcer)
    else:
        _dossier_run(args.run, emp.runs)
    print(f"dossier du run : {d}")
    print(f"config : {os.path.abspath(cfg.chemin)}")
    exclus = NON_BRUTS_PARTAGE if partage else NON_BRUTS
    jsons = [f for f in _fichiers(d, "*.json") if not os.path.basename(f).startswith(exclus)]
    # `~$A.json` (fichier de travail d'Office) n'est pas un JSON d'agent : ignoré, mais nommé
    travail = [f for f in jsons if nom_ignore(f)]
    if travail:
        print("  ignoré(s) (fichier de travail) : " + ", ".join(os.path.basename(f) for f in travail))
    bruts_fichiers = [f for f in jsons if not nom_ignore(f)]
    if not bruts_fichiers:
        print(f"Aucun JSON d'agent dans {d}/ — rien à préparer.", file=sys.stderr)
        return 1

    if partage:
        candidats = [c for f in bruts_fichiers for c in _lire(f, lambda x: charger_candidats([x]))]
        hist = _historique_partage(emp, args.run)
    else:
        candidats = charger_candidats(bruts_fichiers)
        hist = _historique(args.racine, args.run)
    gardes, rap = dedupliquer(candidats, hist, jours_max=args.jours)
    rendement = rendement_par_mot_cle(candidats)
    non_traites = _mots_cles_non_traites(bruts_fichiers)

    if partage:  # toutes les lectures sont faites : place aux écritures, verrou d'abord
        _prendre(emp.racine_donnees, args.run, "prepare", forcer=args.forcer)
        _ecrire_proprietaire(d, etranger)
    sortie = os.path.join(d, "a_scorer.json")
    with open(sortie, "w", encoding="utf-8") as fh:
        json.dump(gardes, fh, ensure_ascii=False, indent=1)

    # comparaison normalisée : un agent qui change la casse ou les accents d'un mot-clé ne doit
    # pas le faire passer pour « sans résultat »
    vus = {norm(k) for k, _ in rendement} | {norm(k) for k in non_traites}
    rapport = {
        "run": args.run, "version": __version__, "fichiers": [os.path.basename(f) for f in bruts_fichiers],
        "jours_max": args.jours, "bruts": rap.bruts, "hors_fenetre": rap.hors_fenetre,
        "deja_connus": rap.deja_connus, "doublons_internes": rap.doublons_internes,
        "nouveaux": rap.nouveaux, "meme_organisation": rap.meme_organisation,
        "rendement_par_mot_cle": rendement,
        "run_incomplet": bool(non_traites),
        "mots_cles_non_traites": non_traites,
        # un mot-clé jamais cherché n'est pas « sans résultat » : on ne le retire pas du plan
        "mots_cles_sans_resultat": [k for k in cfg.mots_cles if norm(k) not in vus],
    }
    with open(os.path.join(d, "rapport_prepare.json"), "w", encoding="utf-8") as fh:
        json.dump(rapport, fh, ensure_ascii=False, indent=1)

    print(rap.resume(), "->", sortie)
    if rap.meme_organisation:
        print("organisations déjà en suivi (à signaler au scoring) :", ", ".join(rap.meme_organisation))
    sans = rapport["mots_cles_sans_resultat"]
    if sans:
        print(f"{len(sans)} mot(s)-clé(s) sans résultat : {', '.join(sans)}")
    print("\nrendement par mot-clé :")
    for k, v in rendement:
        print(f"  {v:4d}  {k}")
    if non_traites:
        print(
            f"\nRUN INCOMPLET : {len(non_traites)} mot(s)-clé(s) non traité(s) : "
            f"{', '.join(non_traites)}. Reprendre le run au premier d'entre eux, jamais depuis "
            "le début ; ce ne sont pas des mots-clés « sans résultat ».",
            file=sys.stderr,
        )
    return 0


def _mots_cles_non_traites(fichiers: list[str]) -> list[str]:
    """Mots-clés qu'un agent déclare non traités et qu'aucun autre lot du run n'a repris.

    Un agent interrompu liste ses mots-clés restants dans `mots_cles_non_traites` (§12 de la
    recette de scraping). Une reprise les traite dans un autre JSON du même run : ils figurent
    alors dans ses `mots_cles_traites` et sortent de la liste. Les mots-clés se comparent
    normalisés (casse, accents) ; le libellé rendu est celui du premier agent qui l'a écrit.
    """
    traites: set[str] = set()
    restants: dict[str, str] = {}  # clé normalisée -> libellé
    for f in fichiers:
        with open(f, encoding="utf-8") as fh:
            d = json.load(fh)
        if not isinstance(d, dict):
            continue
        traites.update(norm(k) for k in _liste(d.get("mots_cles_traites")))
        for k in _liste(d.get("mots_cles_non_traites")):
            restants.setdefault(norm(k), k)
    return [k for n, k in restants.items() if n not in traites]


def _liste(v: Any) -> list[str]:
    """Liste de mots-clés d'un JSON d'agent : une chaîne seule compte pour un mot-clé."""
    if isinstance(v, str):
        return [v] if v.strip() else []
    if isinstance(v, list):
        return [str(x) for x in v if str(x).strip()]
    return []


# --- finaliser ---------------------------------------------------------------------------------

def _charger_scored(fichiers: list[str], partage: bool) -> list[dict[str, Any]]:
    posts: list[dict[str, Any]] = []
    for f in fichiers:
        x = _lire(f, _json) if partage else _json(f)
        posts += x["posts"] if isinstance(x, dict) and "posts" in x else x
    print(f"{len(fichiers)} fichier(s) de scoring, {len(posts)} lignes")
    return posts


def _filtrer(cfg: cfg_mod.Config, posts: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """F4, seuil de conservation, garde-fous. None si un garde-fou saute (déjà signalé)."""
    # F4 : filet de sécurité automatique — une organisation blacklistée ne passe jamais
    retires = [p for p in posts if cfg.est_blacklistee(p.get("auteur"))]
    posts = [p for p in posts if not cfg.est_blacklistee(p.get("auteur"))]
    for p in retires:
        print(f"  écarté (F4 blacklist) : {p.get('auteur')} (score {p.get('score_pertinence')})")

    sous_seuil = [p for p in posts if not cfg.conserver(p.get("score_pertinence") or 0)]
    posts = [p for p in posts if cfg.conserver(p.get("score_pertinence") or 0)]
    if sous_seuil:
        print(f"  {len(sous_seuil)} ligne(s) sous le seuil de conservation, retirées du livrable")

    anomalies = controler(posts, seuil_redaction=cfg.seuil_redaction)
    if anomalies:
        print("GARDE-FOUS EN ÉCHEC :", file=sys.stderr)
        for a in anomalies:
            print("  ⚠ ", a, file=sys.stderr)
        return None

    # l'avertissement F4 vient APRÈS les garde-fous : écrit dans `commentaire_scoring`, il
    # masquerait un score non tracé
    for p in posts:
        if cfg.est_en_observation(p.get("auteur")):
            p["commentaire_scoring"] = (
                "⚠ organisation EN OBSERVATION (F4) : dernière tentative avant blacklist. "
                + str(p.get("commentaire_scoring") or "")
            )
    return posts


def cmd_finaliser(args: argparse.Namespace) -> int:
    emp = _emplacements(args)
    print(emp.ligne_mode())
    if emp.mode == "partage":
        return _finaliser_partage(args, emp)
    cfg = cfg_mod.charger(args.config, racine=args.racine)
    d = _dossier_run(args.run, emp.runs)
    fichiers = _fichiers(d, "scored_*.json")
    if not fichiers:
        print(f"Aucun scored_*.json dans {d}/", file=sys.stderr)
        return 1

    posts = _filtrer(cfg, _charger_scored(fichiers, partage=False))
    if posts is None:
        return 2

    sortie = args.sortie or os.path.join(emp.classeurs, f"prospection_{args.run}.xlsx")
    os.makedirs(os.path.dirname(sortie) or ".", exist_ok=True)
    stats = construire(
        posts, run=args.run, sortie=sortie, base=args.base, seuil_redaction=cfg.seuil_redaction
    )
    print(" ".join(f"{k}={v}" for k, v in stats.items()), "->", sortie)

    if not args.sans_csv:
        _exporter_csv(sortie, args.run, emp.classeurs)
    return 0


def _onglet_csv(ws: Any, chemin: str) -> None:
    with open(chemin, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        for r in ws.iter_rows(values_only=True):
            w.writerow(["" if v is None else v for v in r])


def _exporter_csv(chemin_xlsx: str, run: str, dossier: str = "data") -> None:
    """Archive CSV (mode local) : c'est ce qui permet à une future session de reprendre sans le classeur."""
    import openpyxl

    wb = openpyxl.load_workbook(chemin_xlsx)
    for onglet, nom in (("MASTER", "MASTER"), ("SUIVI_LEADS", "SUIVI_LEADS"),
                        (f"DELTA_{run}", f"DELTA_{run}")):
        if onglet not in wb.sheetnames:
            continue
        cible = os.path.join(dossier, f"{nom}.csv")
        _onglet_csv(wb[onglet], cible)
        print("  csv ->", cible)


def _controle_excel(classeur: str) -> None:
    """Excel dépose `~$<nom>` à côté d'un classeur ouvert : on ne réécrit pas sous ses pieds."""
    dossier, nom = os.path.split(classeur)
    for verrou_excel in sorted({"~$" + nom, "~$" + nom[2:]}):
        if os.path.exists(os.path.join(dossier, verrou_excel)):
            raise Refus(
                f"{nom} est ouvert dans Excel ({verrou_excel} présent) : le fermer d'abord (et "
                "attendre que le Drive soit à jour), puis relancer."
            )


def _choisir_base(args: argparse.Namespace, emp: Emplacements, calculee: str | None) -> str | None:
    if not args.base:
        if calculee is None:
            print("AVERTISSEMENT : aucun classeur dans classeurs/ : classeur vide, le MASTER est "
                  "reconstruit depuis l'historique.", file=sys.stderr)
        return calculee
    base = os.path.abspath(args.base)
    if not os.path.isfile(base):
        raise Refus(f"--base introuvable : {base}")
    if calculee is None or os.path.normcase(base) != os.path.normcase(calculee):
        if os.path.normcase(os.path.dirname(base)) != os.path.normcase(emp.classeurs):
            raison = "hors de classeurs/"
        else:
            raison = f"différent de la base calculée ({calculee or 'aucune'})"
        if not args.forcer:
            raise Refus(f"--base {base} est {raison} : retirer --base, ou relancer avec --forcer "
                        "pour l'imposer.")
        print(f"AVERTISSEMENT : base imposée par --forcer ({raison}) : {base}", file=sys.stderr)
    return base


def _onglets(chemin: str) -> list[str]:
    import openpyxl

    wb = openpyxl.load_workbook(chemin, read_only=True)
    try:
        return list(wb.sheetnames)
    finally:
        wb.close()  # sous Windows, une poignée ouverte empêcherait le os.replace final


def _anterieurs(
    emp: Emplacements, run: str, cfg: cfg_mod.Config, onglets: list[str]
) -> list[dict[str, Any]]:
    """Lignes d'historique des runs STRICTEMENT antérieurs, dans l'ordre chronologique, filtrées F4.

    Un CSV sans run lisible dans son nom (MASTER migré, DELTA d'un run local au nom libre) vient
    d'avant le mode partagé : il passe en premier. Parmi eux, le MASTER d'abord (`MASTER.csv`,
    puis les autres CSV sans run dans le nom), les DELTA au nom libre ensuite : le MASTER porte
    les labels humains et l'ordre de référence, alors qu'un DELTA, exporté à la finalisation, n'a
    pas de label ; lu d'abord, il ferait écarter comme doublon la ligne labellisée du MASTER.
    Le DELTA du run courant n'est pas antérieur, un DELTA postérieur non plus.
    """
    k = cle_run(run)
    migres, dates = [], []
    for f in _fichiers(emp.historique, "*.csv"):
        if nom_ignore(f):
            continue
        r = run_du_fichier(f)
        kr = cle_run(r) if r else None
        if kr is None:
            migres.append(f)
        elif k is not None and kr < k:
            dates.append((kr, f))
    migres.sort(key=lambda f: (run_du_fichier(f) is not None,
                               os.path.basename(f).lower() != "master.csv", f))
    lignes: list[dict[str, Any]] = []
    ignores, sans_onglet, ecartees = [], [], 0
    for f in migres + [f for _, f in sorted(dates)]:
        lu = _lire(f, lire_historique_csv)
        if lu is None:
            ignores.append(os.path.basename(f))
            continue
        r = run_du_fichier(f)
        if r is not None and f"DELTA_{r}" not in onglets:
            sans_onglet.append(r)
        for ligne in lu:
            # F4 : une organisation blacklistée n'est jamais réinjectée
            if cfg.est_blacklistee(ligne.get("auteur")):
                ecartees += 1
            else:
                lignes.append(ligne)
    if ignores:
        print("  ignoré(s) dans historique/ (CSV sans colonne auteur) : " + ", ".join(ignores))
    if ecartees:
        print(f"  {ecartees} ligne(s) d'historique écartée(s) (F4 blacklist) : jamais réinjectées")
    for r in sans_onglet:
        print(f"AVERTISSEMENT : le classeur de base n'a pas d'onglet DELTA_{r} : les leads du run "
              f"{r} ne figurent pas dans SUIVI_LEADS. Ils n'y sont jamais réinjectés (ils y "
              "entreraient « À contacter » à tort).", file=sys.stderr)
    return lignes


def _delta_csv(classeur: str, run: str, cible: str) -> None:
    """Onglet DELTA_<run> du classeur, en CSV `COLS` utf-8 (le classeur peut s'appeler `….tmp`)."""
    import openpyxl

    with open(classeur, "rb") as fh:  # par un flux : openpyxl refuse l'extension .tmp
        wb = openpyxl.load_workbook(fh)
    _onglet_csv(wb[f"DELTA_{run}"], cible)


def _ecrire_finalisation(
    posts: list[dict[str, Any]], run: str, cible: str, cible_delta: str, base: str | None,
    seuil_redaction: float, anterieurs: list[dict[str, Any]],
) -> dict[str, int] | None:
    """Écritures atomiques : classeur puis DELTA, chacun par `….tmp` + `os.replace`.

    Le DELTA vient en dernier : sa présence marque un run finalisé. None si l'écriture est
    refusée (message déjà affiché) ; les temporaires sont toujours nettoyés. Une base disparue
    depuis sa lecture (renommage appliqué par le Drive, déplacement) lève FichierIllisible :
    jamais de repli sur un classeur vide.
    """
    tmp_x, tmp_d = cible + ".tmp", cible_delta + ".tmp"
    try:
        try:
            stats = construire(posts, run=run, sortie=tmp_x, base=base,
                               seuil_redaction=seuil_redaction, anterieurs=anterieurs)
        except FileNotFoundError as exc:
            if base and not os.path.exists(base):
                raise FichierIllisible(base, exc) from exc
            raise
        _delta_csv(tmp_x, run, tmp_d)
        os.replace(tmp_x, cible)
        os.replace(tmp_d, cible_delta)
    except PermissionError as exc:
        print(f"BLOQUANT : écriture refusée ({exc}) : un fichier est ouvert dans Excel, ou "
              "verrouillé par la synchronisation du Drive. Le fermer, attendre que le Drive soit "
              "à jour, puis relancer finaliser : le run n'est pas marqué finalisé.", file=sys.stderr)
        return None
    except OSError as exc:  # Drive démonté, disque plein… : pas de trace Python
        print(f"BLOQUANT : écriture impossible ({exc}). Vérifier que le Drive est monté et qu'il "
              "reste de la place, puis relancer finaliser : le run n'est pas marqué finalisé.",
              file=sys.stderr)
        return None
    finally:
        for t in (tmp_x, tmp_d):
            try:
                os.remove(t)
            except OSError:
                pass
    return stats


def _finaliser_partage(args: argparse.Namespace, emp: Emplacements) -> int:
    """`finaliser` en mode partagé : tous les contrôles et lectures, puis toutes les écritures."""
    run = args.run
    k = _valider_run(run)
    if args.sortie:
        raise Refus("--sortie ne s'emploie pas en mode partagé : un run n'écrit que ses propres "
                    "fichiers, dont classeurs/prospection_<run>.xlsx.")
    cfg = _charger_config(args, emp)
    d = os.path.join(emp.runs, run)
    fichiers = _fichiers(d, "scored_*.json")
    if not fichiers:
        print(f"Aucun scored_*.json dans {d}/", file=sys.stderr)
        return 1
    _controle_occupation(emp, run, d, args.forcer)

    # --- 1. contrôles bloquants ----------------------------------------------------------------
    conflits = (_copies_en_conflit(emp.historique) + _copies_en_conflit(emp.classeurs)
                + _copies_en_conflit(emp.racine_donnees, "config*.yaml"))
    if conflits:
        raise Refus("copie(s) en conflit du Drive : " + ", ".join(conflits) + ". Les fusionner à "
                    "la main (garder les deux contenus), retirer la copie, puis relancer.")
    posterieurs = [c for kc, c in _classeurs(emp.classeurs) if kc > k]
    if posterieurs:
        noms = ", ".join(os.path.basename(c) for c in posterieurs)
        if not args.forcer:
            raise Refus(f"classeur(s) postérieur(s) au run {run} dans classeurs/ : {noms}. On ne "
                        "finalise pas hors ordre ; relancer avec --forcer pour passer outre.")
        print(f"AVERTISSEMENT : finalisé hors ordre (--forcer), classeur(s) postérieur(s) : {noms}",
              file=sys.stderr)
    cible = os.path.join(emp.classeurs, f"prospection_{run}.xlsx")
    _controle_excel(cible)
    base = _choisir_base(args, emp, _base_calculee(emp, run))
    onglets: list[str] = []
    if base:
        _controle_excel(base)
        onglets = _lire(base, _onglets)  # illisible : jamais de repli sur un classeur vide
        print(f"classeur de base : {base}")

    # --- 2. lectures et filtres ----------------------------------------------------------------
    posts = _filtrer(cfg, _charger_scored(fichiers, partage=True))
    if posts is None:
        return 2
    anterieurs = _anterieurs(emp, run, cfg, onglets)

    # --- 3. écritures : le verrou d'abord, pris entre-temps il arrête tout ---------------------
    _prendre(emp.racine_donnees, run, "finaliser", forcer=args.forcer)
    os.makedirs(emp.classeurs, exist_ok=True)
    os.makedirs(emp.historique, exist_ok=True)
    cible_delta = os.path.join(emp.historique, f"DELTA_{run}.csv")
    stats = _ecrire_finalisation(posts, run, cible, cible_delta, base, cfg.seuil_redaction,
                                 anterieurs)
    if stats is None:
        return 2
    print(" ".join(f"{k}={v}" for k, v in stats.items()), "->", cible)
    print("  delta ->", cible_delta)
    print(f"réinjectées depuis l'historique : {stats['reinjectees']}")
    if stats["reinjectees"]:
        print(f"AVERTISSEMENT : {stats['reinjectees']} ligne(s) d'historique manquai(en)t au "
              "classeur de base et ont été réinjectée(s) au MASTER (ligne supprimée à la main ? "
              "classeur d'un autre poste pas encore synchronisé ?). Une ligne se passe en "
              "validation=NON, elle ne se supprime pas.", file=sys.stderr)
    # le run est finalisé (classeur et DELTA écrits) : un verrou qui ne se libère pas se signale,
    # sans défaire le run ni changer le code de sortie (1 voudrait dire « rien à traiter »)
    try:
        verrou.liberer(emp.racine_donnees, run)
        print("verrou libéré")
    except verrou.VerrouOccupe as exc:
        print(f"AVERTISSEMENT : run finalisé, mais verrou non libéré : {exc}", file=sys.stderr)
    except OSError as exc:  # verrou.json tenu par la synchronisation du Drive, un antivirus…
        print(f"AVERTISSEMENT : run finalisé (classeur et DELTA écrits), mais verrou non libéré : "
              f"écriture de {verrou.NOM} refusée ({exc}). Les autres postes restent bloqués "
              f"jusqu'à son expiration ({verrou.TTL_HEURES:g} h). Une fois le Drive à jour : "
              f"`python -m prospection.run verrou liberer --run {run}`.", file=sys.stderr)
    return 0


# --- lots, verrou ------------------------------------------------------------------------------

def cmd_lots(args: argparse.Namespace) -> int:
    """Imprime la répartition des mots-clés entre agents, prête à coller dans les prompts.

    Avec `--run` : crée le dossier du run et affiche les chemins absolus à donner aux agents. En
    mode partagé, valide l'identifiant, refuse un run déjà finalisé (code 2) ou préparé sur un
    autre poste (code 3), sauf `--forcer`, puis prend le verrou : sinon les agents écriraient
    dans le dossier d'un run fini, ou d'un autre poste, et le refus ne viendrait qu'à `prepare`.
    """
    emp = _emplacements(args)
    print(emp.ligne_mode())
    partage = emp.mode == "partage"
    forcer = getattr(args, "forcer", False)
    if partage and args.run is not None:
        _valider_run(args.run)
    cfg = _charger_config(args, emp)
    if args.run is not None:
        pris = None
        if partage:  # mêmes contrôles, dans le même ordre, que prepare
            _controle_occupation(emp, args.run, os.path.join(emp.runs, args.run), forcer)
            _controle_deja_finalise(emp, args.run, forcer)
            pris = _prendre(emp.racine_donnees, args.run, "lots", forcer=forcer)
        d = _dossier_run(args.run, emp.runs)
        print(f"dossier du run : {d}")
        print(f"config : {os.path.abspath(cfg.chemin)}")
        if pris:
            print("verrou :", verrou.decrire({**pris, "fichier": verrou.NOM}))
    for i, lot in enumerate(cfg.lots(args.agents)):
        print(f"\n--- lot {chr(65 + i)} ({len(lot)} mots-clés) ---")
        print(" · ".join(lot))
    return 0


def cmd_verrou(args: argparse.Namespace) -> int:
    """`verrou statut|prendre|liberer` : pour un run abandonné, ou pour forcer."""
    emp = _emplacements(args)
    print(emp.ligne_mode())
    if emp.mode != "partage":
        print("verrou : sans objet en mode local")
        return 0
    if args.run is not None:
        _valider_run(args.run)
    dossier = emp.racine_donnees
    if args.action == "statut":
        lus = verrou.etats(dossier)
        if not lus:
            print("verrou : aucun")
        for e in lus:
            print("verrou :", verrou.decrire(e))
        if args.run is not None:
            occ = verrou.occupants(dossier, args.run, args.ttl_heures)
            print(f"prise pour le run {args.run} : " + ("BLOQUÉE" if occ else "possible"))
        return 0
    if args.action == "prendre":
        if args.run is None:
            raise Refus("verrou prendre exige --run")
        pris = _prendre(dossier, args.run, "verrou prendre", args.ttl_heures, args.forcer)
        print("verrou :", verrou.decrire({**pris, "fichier": verrou.NOM}))
        return 0
    try:
        ecrits = verrou.liberer(dossier, args.run, args.forcer)
    except OSError as exc:
        raise Refus(_verrou_inecrivable(dossier, exc)) from exc
    print("verrou libéré : " + ", ".join(ecrits) if ecrits else "verrou : rien à libérer")
    return 0


# --- sous-commandes d'autres modules (import paresseux) ----------------------------------------

def _cmd_poste(args: argparse.Namespace) -> int:
    from .poste import cmd_poste

    return cmd_poste(args)


def _cmd_initialiser(args: argparse.Namespace) -> int:
    from .migration import cmd_initialiser

    return cmd_initialiser(args)


def main(argv: list[str] | None = None) -> int:
    # --donnees est acceptée avant ET après la sous-commande ; SUPPRESS : la valeur absente d'un
    # côté n'écrase pas celle donnée de l'autre
    commun = argparse.ArgumentParser(add_help=False)
    commun.add_argument("--donnees", default=argparse.SUPPRESS, metavar="DOSSIER",
                        help="dossier de données partagé (défaut : variable PROSPECTION_DONNEES, "
                             "sinon mode local)")
    ap = argparse.ArgumentParser(prog="prospection.run", description=__doc__, parents=[commun],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--racine", default=".", help="racine du dépôt (défaut : .)")
    ap.add_argument("--config", default=None, help="chemin du YAML de config")
    sub = ap.add_subparsers(dest="cmd", required=True)
    forcer = "mode partagé : passer outre un verrou, un propriétaire ou un contrôle d'ordre"

    p = sub.add_parser("prepare", parents=[commun], help="dédupliquer et préparer le lot à scorer")
    p.add_argument("--run", required=True, help="identifiant du run, ex. 23-09-2026")
    p.add_argument("--jours", type=float, default=None, help="fenêtre en jours (défaut : aucune)")
    p.add_argument("--forcer", action="store_true", help=forcer)
    p.set_defaults(func=cmd_prepare)

    p = sub.add_parser("finaliser", parents=[commun],
                       help="construire le classeur à partir des scored_*.json")
    p.add_argument("--run", required=True)
    p.add_argument("--base", default=None,
                   help="classeur existant à compléter (mode partagé : calculé s'il manque)")
    p.add_argument("--sortie", default=None, help="mode local seulement")
    p.add_argument("--sans-csv", action="store_true", help="mode local : pas d'archive CSV")
    p.add_argument("--forcer", action="store_true", help=forcer)
    p.set_defaults(func=cmd_finaliser)

    p = sub.add_parser("lots", parents=[commun], help="répartir les mots-clés entre agents")
    p.add_argument("--agents", type=int, default=3)
    p.add_argument("--run", default=None,
                   help="créer le dossier du run et afficher ses chemins (partagé : prend le verrou)")
    p.add_argument("--forcer", action="store_true",
                   help="mode partagé : passer outre le verrou, un propriétaire ou un run finalisé")
    p.set_defaults(func=cmd_lots)

    p = sub.add_parser("verrou", parents=[commun], help="verrou du dossier partagé")
    p.add_argument("action", choices=("statut", "prendre", "liberer"))
    p.add_argument("--run", default=None)
    p.add_argument("--forcer", action="store_true")
    p.add_argument("--ttl-heures", type=float, default=verrou.TTL_HEURES)
    p.set_defaults(func=cmd_verrou)

    p = sub.add_parser("poste", parents=[commun], help="contrôler que ce PC peut lancer un run")
    p.add_argument("--run", default=None)
    p.set_defaults(func=_cmd_poste)

    p = sub.add_parser("initialiser-donnees", parents=[commun],
                       help="créer le dossier de données partagé et y migrer data/ et runs/")
    p.add_argument("--vers", required=True, help="dossier de données à créer (hors du dépôt)")
    p.add_argument("--depuis", default="data")
    p.add_argument("--runs", default="runs")
    p.add_argument("--classeur", default=None)
    p.add_argument("--gabarit", action="store_true")
    p.set_defaults(func=_cmd_initialiser)

    args = ap.parse_args(argv)
    # chemins saisis par la personne : lus depuis le répertoire courant, donc rendus absolus
    # AVANT le chdir de --racine (une valeur vide reste vide : resoudre la refusera)
    donnees = getattr(args, "donnees", None)
    args.donnees = os.path.abspath(donnees) if donnees and donnees.strip() else donnees
    if getattr(args, "vers", None):
        args.vers = os.path.abspath(args.vers)
    if args.racine != ".":
        os.chdir(args.racine)
        args.racine = "."
    try:
        return args.func(args)
    except ERREURS_EMPLACEMENT as exc:
        print(f"ERREUR (emplacement des données) : {exc}", file=sys.stderr)
        return 2
    except verrou.VerrouOccupe as exc:
        print(f"OCCUPÉ : {exc}", file=sys.stderr)
        return 3
    except Refus as exc:
        print(f"BLOQUANT : {exc}", file=sys.stderr)
        return exc.code


if __name__ == "__main__":
    raise SystemExit(main())
