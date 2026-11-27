"""Initialisation d'un dossier de données partagé, et migration du `data/` local vers lui.

    python -m prospection.run initialiser-donnees --vers "G:\\…\\donnees" [--depuis data]
        [--runs runs] [--classeur FICHIER] [--gabarit]

Le dossier créé contient `config.yaml`, `historique/`, `runs/`, `classeurs/`, `LISEZMOI.md` et le
marqueur `.prospection-donnees`. Règles :

- la garde hors dépôt passe AVANT tout `mkdir`, sur le dossier visé et sur son ancêtre existant
  le plus proche : un dossier de données n'est jamais créé dans un arbre git. Si même la racine
  du lecteur manque (Google Drive pour ordinateur arrêté), le message le dit ;
- toutes les lectures (config, en-têtes des CSV, classeur) passent avant la première écriture :
  un CSV illisible arrête tout, sans rien avoir créé ;
- JAMAIS d'écrasement : un fichier déjà présent est signalé et laissé tel quel. La commande est
  sûre à relancer ;
- la config vient de `--depuis`, sous les noms de `config.CHEMINS_PAR_DEFAUT` ; le gabarit n'est
  copié qu'avec `--gabarit`, et annoncé en toutes lettres ;
- un CSV n'est migré que s'il est un historique (colonne `auteur`) : un export SUIVI_LEADS reste ;
- en fin de migration, `MIGRE_VERS_PARTAGE.txt` est déposé dans `--depuis` : le mode local s'y
  arrête (`DonneesMigrees`) au lieu de lire un `data/` périmé ;
- la commande AFFICHE la commande PowerShell qui pose la variable `PROSPECTION_DONNEES` (toute
  apostrophe du chemin doublée, typographique comprise), mais ne modifie elle-même aucune
  variable d'environnement.

Un `vers` relatif se lit depuis le répertoire courant (comme `--donnees`) ; `depuis`, `runs` et
`classeur` relatifs, depuis `racine`.
"""
from __future__ import annotations

import argparse
import csv
import filecmp
import glob
import json
import os
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .config import CHEMINS_PAR_DEFAUT
from .dedup import est_csv_historique, nom_ignore
from .emplacements import (
    MARQUEUR, MARQUEUR_MIGRATION, VARIABLE, DossierDonneesDansLeDepot, garde_hors_depot,
)
from .poste import cle_classeur

__all__ = [
    "InitialisationImpossible", "Recapitulatif", "initialiser", "commande_powershell",
    "cmd_initialiser", "NOM_GABARIT", "SOUS_DOSSIERS",
]

NOM_GABARIT = "config-profil.example.yaml"
SOUS_DOSSIERS = ("historique", "runs", "classeurs")
NOMS_CONFIG = tuple(os.path.basename(c) for c in CHEMINS_PAR_DEFAUT)  # config.yaml, puis l'ancien nom
# délimiteurs d'une chaîne PowerShell entre apostrophes : ' ‘ ’ ‚ ‛
APOSTROPHES_POWERSHELL = "'‘’‚‛"
# fichiers de --depuis qui ne sont pas des données : jamais signalés comme « non migrés »
RESTES_ATTENDUS = (MARQUEUR_MIGRATION, "README.md", ".gitkeep")

LISEZMOI = """\
# Dossier de données partagé — prospection LinkedIn

Ce dossier contient les DONNÉES d'un profil. Le code vit dans le dépôt git, cloné sur chaque PC ;
ces données n'entrent jamais dans git : elles contiennent des noms, des profils et des adresses
de tiers qui n'ont pas consenti à figurer dans un dépôt.

- `config.yaml` : configuration du profil, source unique de vérité.
- `historique/` : `DELTA_<run>.csv` écrits par `finaliser` (et le MASTER migré). Ajout seul.
- `runs/<run>/` : JSON bruts des agents de scraping, `a_scorer.json`, `scored_*.json`.
- `classeurs/` : `prospection_<run>.xlsx`. Les labels se saisissent dans le plus récent.
- `verrou.json` : verrou de run, pour qu'un seul poste travaille à la fois.
- `.prospection-donnees` : marqueur du dossier. Ne pas le supprimer.

Règles :

- Rendre ce dossier « Disponible hors connexion » dans Drive.
- Attendre que Drive soit « à jour » avant de changer de PC.
- Ne jamais supprimer une ligne du MASTER : la passer en `validation=NON` (une ligne supprimée
  revient depuis l'historique).
- Une copie en conflit (« (1) » dans le nom) bloque `finaliser` : la fusionner à la main avec
  l'original, puis la supprimer.
- Vérifier un PC avec `python -m prospection.run poste`.
"""


class InitialisationImpossible(RuntimeError):
    """Rien à migrer, source manquante ou illisible : rien n'a été créé."""


@dataclass
class Recapitulatif:
    vers: str                                 # dossier de données, absolu
    config: str = "absente"                   # copiée | gabarit | déjà présente | absente
    config_source: str | None = None          # fichier copié (config de --depuis, ou gabarit)
    csv: list[str] = field(default_factory=list)          # CSV d'historique copiés
    csv_ignores: list[str] = field(default_factory=list)  # CSV de --depuis non migrés
    json: int = 0                             # JSON de runs copiés
    runs: list[str] = field(default_factory=list)         # runs dont au moins un JSON a été trouvé
    classeur: str | None = None               # nom du classeur zéro
    deja_presents: list[str] = field(default_factory=list)  # chemins relatifs à `vers`, non écrasés
    differents: list[str] = field(default_factory=list)   # dont le contenu diffère de la source
    migration: str | None = None              # MIGRE_VERS_PARTAGE.txt déposé (absolu)
    restes: list[str] = field(default_factory=list)       # fichiers de --depuis laissés sur place
    journal: list[str] = field(default_factory=list)


def commande_powershell(chemin: str) -> str:
    """Commande qui pose la variable pour l'utilisateur, chemin entre apostrophes.

    PowerShell (5.1 comme 7) prend pour délimiteur d'une chaîne entre apostrophes l'apostrophe
    droite `'`, mais aussi ‘ ’ ‚ ‛ : un dossier nommé avec une correction automatique
    (« l’équipe ») casserait la commande. Chacune est donc doublée, par elle-même.
    """
    for q in APOSTROPHES_POWERSHELL:
        chemin = chemin.replace(q, q * 2)
    return f"[Environment]::SetEnvironmentVariable('{VARIABLE}', '{chemin}', 'User')"


def _ancetre_existant(chemin: str) -> str:
    p = chemin
    while not os.path.exists(p):
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    return p


def _depuis_racine(chemin: str, racine: str) -> str:
    return os.path.abspath(os.path.join(racine, chemin))


def initialiser(
    vers: str,
    depuis: str = "data",
    runs: str = "runs",
    classeur: str | None = None,
    gabarit: bool = False,
    racine: str = ".",
) -> Recapitulatif:
    """Crée (ou complète) le dossier de données partagé `vers` et y migre `depuis` et `runs`.

    Lève `DossierDonneesDansLeDepot` ou `InitialisationImpossible` sans rien avoir créé. Une
    erreur de copie en cours de route (`OSError`) laisse un dossier partiel, qu'une relance
    complète sans rien écraser.
    """
    racine = os.path.abspath(racine)
    cible = os.path.abspath(vers)
    # 1. garde hors dépôt, avant tout mkdir : sur l'ancêtre existant ET sur le chemin visé
    ancetre = _ancetre_existant(cible)
    if not os.path.exists(ancetre):  # même la racine du lecteur manque
        raise InitialisationImpossible(
            f"{ancetre} introuvable : lecteur non monté ? Démarrer Google Drive pour ordinateur "
            "(ou reconnecter le lecteur), attendre qu'il apparaisse dans l'Explorateur, puis "
            "relancer. Rien n'a été créé."
        )
    garde_hors_depot(ancetre, racine)
    garde_hors_depot(cible, racine)
    if not os.path.isdir(ancetre):  # `vers`, ou l'un de ses parents, est un fichier
        raise InitialisationImpossible(f"{ancetre} existe et n'est pas un dossier.")
    src = _depuis_racine(depuis, racine)
    src_runs = _depuis_racine(runs, racine)

    # 2. toutes les lectures, avant la première écriture
    config_src = next((os.path.join(src, n) for n in NOMS_CONFIG
                       if os.path.isfile(os.path.join(src, n))), None)
    a_copier_csv, csv_ignores = [], []
    for f in sorted(glob.glob(os.path.join(glob.escape(src), "*.csv"))):
        if nom_ignore(f):
            csv_ignores.append(os.path.basename(f))
            continue
        try:
            reconnu = est_csv_historique(f)
        except (OSError, ValueError, csv.Error) as e:  # UnicodeDecodeError est une ValueError
            raise InitialisationImpossible(
                f"CSV illisible : {f} ({type(e).__name__}). Rien n'a été créé : le rendre "
                "lisible (ou le retirer de la source), puis relancer."
            ) from e
        if reconnu:
            a_copier_csv.append(f)
        else:
            csv_ignores.append(os.path.basename(f))
    if classeur:
        classeur_src = _depuis_racine(classeur, racine)
        if not os.path.isfile(classeur_src):
            raise InitialisationImpossible(f"classeur introuvable : {classeur_src}")
    else:
        noms = os.listdir(src) if os.path.isdir(src) else []
        dates = [(cle_classeur(n), n) for n in noms
                 if cle_classeur(n) and os.path.isfile(os.path.join(src, n))]
        classeur_src = os.path.join(src, max(dates)[1]) if dates else None
    gabarit_src = _gabarit(racine) if gabarit and config_src is None else None
    if gabarit and config_src is None and gabarit_src is None:
        raise InitialisationImpossible(f"gabarit introuvable : templates/{NOM_GABARIT}")
    config_cible = os.path.join(cible, "config.yaml")
    if config_src is None and not gabarit and not a_copier_csv and not os.path.exists(config_cible):
        raise InitialisationImpossible(
            f"rien à migrer depuis {_affichable(src, racine)} : ni config, ni CSV d'historique. "
            "Passer --depuis <dossier>, ou --gabarit pour partir du gabarit."
        )
    jsons = []  # (run, fichier) : les JSON de runs/<run>/, structure gardée
    if os.path.isdir(src_runs):
        for d in sorted(os.listdir(src_runs)):
            dossier = os.path.join(src_runs, d)
            if os.path.isdir(dossier):
                motif = os.path.join(glob.escape(dossier), "*.json")
                jsons += [(d, f) for f in sorted(glob.glob(motif)) if not nom_ignore(f)]

    # 3. écritures, sans jamais écraser
    rec = Recapitulatif(vers=cible, csv_ignores=csv_ignores)
    for chemin in [cible] + [os.path.join(cible, s) for s in SOUS_DOSSIERS]:
        rel = os.path.relpath(chemin, cible).replace(os.sep, "/")
        if os.path.isdir(chemin):
            if chemin != cible:
                rec.journal.append(f"déjà présent : {rel}/")
        else:
            os.makedirs(chemin)
            rec.journal.append(f"créé : {rel}/" if chemin != cible else "créé : dossier de données")

    if config_src or gabarit_src:
        source = config_src or gabarit_src
        if _copier(source, config_cible, rec):
            rec.config = "copiée" if config_src else "gabarit"
            rec.config_source = _affichable(source, racine)
            if gabarit_src:
                rec.journal.append("GABARIT copié : à remplir avant tout run")
        else:
            rec.config = "déjà présente"
        if config_src and gabarit:
            rec.journal.append(f"gabarit non utilisé : la config de {_affichable(src, racine)} a priorité")
    elif os.path.exists(config_cible):
        rec.config = "déjà présente"
        rec.journal.append("déjà présent : config.yaml")
    else:
        rec.journal.append("config absente : copier la config du profil dans config.yaml avant "
                           "tout run (ou relancer avec --gabarit)")

    for f in a_copier_csv:
        if _copier(f, os.path.join(cible, "historique", os.path.basename(f)), rec):
            rec.csv.append(os.path.basename(f))
    for n in csv_ignores:
        rec.journal.append(f"ignoré (ni MASTER ni DELTA, ou fichier de travail) : {n}")

    for run, f in jsons:
        d = os.path.join(cible, "runs", run)
        os.makedirs(d, exist_ok=True)
        if run not in rec.runs:
            rec.runs.append(run)
        if _copier(f, os.path.join(d, os.path.basename(f)), rec):
            rec.json += 1

    if classeur_src:
        rec.classeur = os.path.basename(classeur_src)
        _copier(classeur_src, os.path.join(cible, "classeurs", rec.classeur), rec)
        if cle_classeur(rec.classeur) is None:
            rec.journal.append(f"classeur {rec.classeur} hors format prospection_JJ-MM-AAAA.xlsx "
                               ": finaliser ne le choisira pas comme base")

    # le marqueur de migration coupe le mode local : ce qui reste dans --depuis est nommé, pour
    # que la personne le copie à la main si un autre PC en a besoin (notes, anciens classeurs)
    if os.path.isdir(src):
        pris = {os.path.basename(f) for f in a_copier_csv} | set(csv_ignores) | set(NOMS_CONFIG)
        if classeur_src:
            pris.add(os.path.basename(classeur_src))
        for n in sorted(os.listdir(src)):
            if (n in pris or n in RESTES_ATTENDUS or nom_ignore(n)
                    or not os.path.isfile(os.path.join(src, n))):
                continue
            rec.restes.append(n)
            rec.journal.append(f"non migré (resté dans {_affichable(src, racine)}) : {n}")

    _ecrire_si_absent(os.path.join(cible, "LISEZMOI.md"), LISEZMOI, rec)
    # le marqueur en dernier dans le dossier partagé : un dossier à moitié copié n'est pas
    # « initialisé », et une relance le complète
    _ecrire_si_absent(os.path.join(cible, MARQUEUR), json.dumps({"version": 1}) + "\n", rec)

    if os.path.isdir(src):
        migre = os.path.join(src, MARQUEUR_MIGRATION)
        texte = (
            "Les données de ce dossier ont migré vers un dossier partagé.\n"
            f"Dossier cible : {cible}\n"
            f"Date : {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n"
            "Ce dossier n'est plus lu : en mode local, les commandes s'arrêtent. Passer\n"
            f"--donnees <dossier>, ou poser {VARIABLE} puis redémarrer l'application et les\n"
            "terminaux.\n"
        )
        if os.path.exists(migre):
            rec.journal.append(f"déjà présent : {MARQUEUR_MIGRATION} dans {_affichable(src, racine)}")
        else:
            _ecrire(migre, texte)
            rec.migration = migre
            rec.journal.append(f"déposé : {MARQUEUR_MIGRATION} dans {_affichable(src, racine)}")
    return rec


def _affichable(chemin: str, racine: str) -> str:
    """Chemin relatif à la racine du dépôt s'il est dedans (`data/config.yaml`), sinon absolu."""
    try:
        rel = os.path.relpath(chemin, racine)
    except ValueError:  # autre lecteur
        return chemin
    return chemin if rel == os.pardir or rel.startswith(os.pardir + os.sep) else rel.replace(os.sep, "/")


def _gabarit(racine: str) -> str | None:
    """Gabarit de config : celui du dépôt `racine`, sinon celui livré avec le code."""
    for base in (racine, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))):
        g = os.path.join(base, "templates", NOM_GABARIT)
        if os.path.isfile(g):
            return g
    return None


def _copier(src: str, dst: str, rec: Recapitulatif) -> bool:
    """Copie `src` vers `dst` sauf si `dst` existe déjà (jamais d'écrasement). True si copié.

    Copie dans `<dst>.tmp`, puis `os.replace` : une copie interrompue ne laisse qu'un `.tmp`,
    que tous les lecteurs ignorent et qu'une relance remplace.
    """
    rel = os.path.relpath(dst, rec.vers).replace(os.sep, "/")
    if os.path.lexists(dst):
        rec.deja_presents.append(rel)
        try:
            different = not filecmp.cmp(src, dst, shallow=False)
        except OSError:
            different = True
        if different:
            rec.differents.append(rel)
        rec.journal.append(f"déjà présent{' (contenu différent, non remplacé)' if different else ''} : {rel}")
        return False
    tmp = dst + ".tmp"
    try:
        shutil.copy2(src, tmp)
        os.replace(tmp, dst)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    rec.journal.append(f"copié : {rel}")
    return True


def _ecrire(chemin: str, texte: str) -> None:
    tmp = chemin + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(texte)
        os.replace(tmp, chemin)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _ecrire_si_absent(chemin: str, texte: str, rec: Recapitulatif) -> bool:
    rel = os.path.relpath(chemin, rec.vers).replace(os.sep, "/")
    if os.path.lexists(chemin):
        rec.deja_presents.append(rel)
        rec.journal.append(f"déjà présent : {rel}")
        return False
    _ecrire(chemin, texte)
    rec.journal.append(f"créé : {rel}")
    return True


def cmd_initialiser(args: argparse.Namespace) -> int:
    """`initialiser-donnees --vers DOSSIER [--depuis data] [--runs runs] [--classeur F] [--gabarit]`."""
    vers = getattr(args, "vers", None)
    if not vers or not str(vers).strip():
        print("initialiser-donnees : --vers DOSSIER est obligatoire.", file=sys.stderr)
        return 2
    print(f"cible : {os.path.abspath(vers)}")
    try:
        rec = initialiser(
            vers, depuis=getattr(args, "depuis", None) or "data",
            runs=getattr(args, "runs", None) or "runs", classeur=getattr(args, "classeur", None),
            gabarit=bool(getattr(args, "gabarit", False)), racine=getattr(args, "racine", None) or ".",
        )
    except (DossierDonneesDansLeDepot, InitialisationImpossible) as e:
        print(f"initialiser-donnees : {e}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"initialiser-donnees : copie interrompue ({e}). Relancer la commande : elle "
              "complète le dossier sans rien écraser.", file=sys.stderr)
        return 2
    for ligne in rec.journal:
        print(f"  {ligne}")
    source = {"copiée": f"copiée depuis {rec.config_source}", "gabarit": "GABARIT (à remplir)",
              "déjà présente": "déjà présente", "absente": "ABSENTE"}[rec.config]
    print(
        f"\nrécapitulatif : config {source} · {len(rec.csv)} CSV d'historique · {rec.json} JSON "
        f"dans {len(rec.runs)} run(s) · classeur zéro : {rec.classeur or 'aucun'}"
        + (f" · {len(rec.deja_presents)} fichier(s) déjà présent(s), non remplacé(s)"
           if rec.deja_presents else "")
    )
    print(
        "\nPour que chaque commande trouve ce dossier, poser la variable (PowerShell) :\n"
        f"  {commande_powershell(rec.vers)}\n"
        "puis redémarrer Claude, les terminaux et GitKraken : une variable « User » n'atteint que "
        "les processus lancés après elle. À défaut, passer --donnees à chaque commande.\n"
        "Cette commande n'a modifié aucune variable d'environnement. Vérifier ensuite le poste "
        "avec `python -m prospection.run poste`."
    )
    return 0
