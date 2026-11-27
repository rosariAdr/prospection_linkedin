"""Contrôle d'un poste : ce PC peut-il lancer un run ? (`python -m prospection.run poste`)

Une ligne par contrôle, de niveau `OK`, `AVERTISSEMENT` ou `BLOQUANT`. Code 0 sans bloquant,
2 sinon. Les contrôles :

- Python ≥ 3.10, `openpyxl` et `yaml` importables ;
- le mode (local ou partagé) et, en mode partagé, le dossier de données : existence, garde hors
  dépôt, marqueur, droit d'écriture ;
- sous Windows, une variable `PROSPECTION_DONNEES` posée pour l'utilisateur mais pas encore vue
  par ce processus (il faut redémarrer l'application et les terminaux) ;
- le marqueur de migration dans le `data/` local ;
- la config (chargeable ; `--config` refusé en mode partagé, comme pour les autres commandes)
  et les copies en conflit (`config (1).yaml`…) ;
- l'historique : fichiers reconnus, lignes, clés recalculées depuis les JSON bruts, fichiers
  illisibles ;
- le verrou de run et, avec `--run` en mode partagé, le run lui-même : identifiant, déjà
  finalisé, préparé sur un autre poste ;
- le classeur le plus récent ;
- le code : branche, commit, âge du dernier `fetch`, retard sur l'amont. Git n'est JAMAIS
  bloquant : une CI tourne à HEAD détaché, sans amont, parfois sans git.

Confidentialité : la racine des données est affichée UNE fois (ligne `données`), puis on n'emploie
que des chemins relatifs. Le nom du profil n'est jamais affiché (« profil chargé »), même quand
la config est invalide : une erreur YAML ne cite que son numéro de ligne. Le nom du fichier de
config n'est affiché que s'il vaut `config.yaml` (`data/config.yaml` en mode local). La sortie nomme quand
même le poste et des chemins : on ne la colle jamais dans une PR ou une issue.
"""
from __future__ import annotations

import argparse
import csv
import glob
import importlib
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime

from . import verrou as verrou_mod
from .dedup import Historique, nom_ignore
from .emplacements import (
    MARQUEUR, MARQUEUR_MIGRATION, VARIABLE, DonneesMigrees, DossierDonneesDansLeDepot,
    DossierDonneesIntrouvable, DossierDonneesNonInitialise, Emplacements, resoudre,
)

__all__ = [
    "OK", "AVERTISSEMENT", "BLOQUANT", "Resultat", "verifier", "cmd_poste", "copie_en_conflit",
    "cle_classeur",
]

OK = "OK"
AVERTISSEMENT = "AVERTISSEMENT"
BLOQUANT = "BLOQUANT"

# JSON d'un dossier de run qui ne sont pas des JSON bruts d'agent
NON_BRUTS = ("a_scorer", "scored_", "rapport", "proprietaire")

# copie en conflit d'un Drive : « verrou (1).json », « config (2).yaml », « historique (1) »
_CONFLIT = re.compile(r".+ \(\d+\)(\.[^.\s]+)?")
# classeur d'un run : prospection_JJ-MM-AAAA.xlsx, ou prospection_JJ-MM-AAAA-n.xlsx (n ≥ 2, sans
# zéro en tête) : le même format que l'identifiant de run de `run.cle_run`, sinon « -02 » serait
# un classeur pour `poste` et `initialiser-donnees`, mais jamais une base pour `finaliser`
_CLASSEUR = re.compile(r"prospection_(\d{2}-\d{2}-\d{4})(?:-([2-9]|[1-9]\d+))?\.xlsx", re.IGNORECASE)
UN_JOUR = 24 * 3600
# seuls noms de config affichés : tout autre nom pourrait nommer le profil (`config-<prénom>.yaml`)
NOMS_CONFIG_AFFICHABLES = ("config.yaml", "data/config.yaml")
PROPRIETAIRE = "proprietaire.json"  # comme run.PROPRIETAIRE : le poste qui a préparé le run


@dataclass(frozen=True)
class Resultat:
    niveau: str   # OK | AVERTISSEMENT | BLOQUANT
    libelle: str
    detail: str = ""

    def ligne(self) -> str:
        return f"{self.niveau:<13} {self.libelle} : {self.detail}"


# --- outils partagés (aussi utilisés par `migration`) ------------------------------------------

def copie_en_conflit(nom: str) -> bool:
    """Vrai pour une copie en conflit d'un Drive : `config (1).yaml`, `DELTA_x (2).csv`…

    Un fichier de travail (`~$…`, `….tmp`) n'en est jamais une.
    """
    return not nom_ignore(nom) and bool(_CONFLIT.fullmatch(os.path.basename(nom)))


def cle_classeur(nom: str) -> tuple[datetime, int] | None:
    """(date, n) d'un `prospection_JJ-MM-AAAA[-n].xlsx`, pour trier par DATE analysée.

    Jamais par ordre lexical : « 31-12-2029 » vient avant « 01-01-2030 ». None pour un autre
    nom, une date impossible, un n inférieur à 2 ou écrit avec un zéro en tête (« -02 »).
    """
    m = _CLASSEUR.fullmatch(os.path.basename(nom))
    if not m:
        return None
    try:
        date = datetime.strptime(m.group(1), "%d-%m-%Y")
    except ValueError:
        return None
    n = int(m.group(2)) if m.group(2) else 1
    if m.group(2) and n < 2:
        return None
    return date, n


# --- contrôles ---------------------------------------------------------------------------------

def verifier(
    racine: str = ".", donnees: str | None = None, run: str | None = None,
    config: str | None = None,
) -> list[Resultat]:
    """Tous les contrôles du poste, dans l'ordre d'affichage. N'écrit rien de durable.

    `donnees` et la variable `PROSPECTION_DONNEES` choisissent le mode comme `resoudre`.
    `run` ajoute le contrôle du verrou pour ce run (BLOQUANT s'il est tenu par un autre) et du
    run lui-même, et l'exclut des JSON bruts comptés. `config` remplace la recherche par défaut
    en mode local, comme l'option `--config` ; en mode partagé, il est BLOQUANT.
    """
    res: list[Resultat] = []
    res += _controle_python()
    emp = _controle_emplacement(racine, donnees, res)
    res += _controle_variable_windows()
    if emp is not None:
        base = _base_relative(emp, racine)
        res += _controle_config(emp, racine, config, base)
        res += _controle_historique(emp, run, base)
        res += _controle_conflits(emp, base)
        res += _controle_verrou(emp, run)
        res += _controle_run(emp, run, base)
        res += _controle_classeur(emp, base)
    res += _controle_git(racine)
    return res


def _controle_python() -> list[Resultat]:
    v = sys.version_info
    res = [Resultat(OK if v >= (3, 10) else BLOQUANT, "python",
                    f"{v.major}.{v.minor}.{v.micro}" + ("" if v >= (3, 10) else " : 3.10 minimum"))]
    for module in ("openpyxl", "yaml"):
        try:
            m = importlib.import_module(module)
        except Exception as e:  # absent, ou installation cassée
            res.append(Resultat(BLOQUANT, module, f"non importable ({type(e).__name__}) : "
                                "pip install -r requirements.txt"))
        else:
            res.append(Resultat(OK, module, str(getattr(m, "__version__", "importable"))))
    return res


def _dossier_vise(donnees: str | None) -> str | None:
    """Dossier partagé visé (absolu), "" pour un `--donnees` vide, None pour le mode local.

    Même priorité que `emplacements.resoudre`, pour l'affichage seulement : quand la résolution
    échoue, on sait quand même quel dossier était visé.
    """
    if donnees is not None:
        return os.path.abspath(donnees) if donnees.strip() else ""
    v = os.environ.get(VARIABLE, "")
    return os.path.abspath(v) if v.strip() else None


def _controle_emplacement(racine: str, donnees: str | None, res: list[Resultat]) -> Emplacements | None:
    """Mode et dossier de données. Seule ligne qui affiche un chemin absolu : la racine."""
    vise = _dossier_vise(donnees)
    if vise is None:
        res.append(Resultat(OK, "données", f"local — {os.path.join(os.path.abspath(racine), 'data')}"))
        try:
            return resoudre(racine, donnees)
        except DonneesMigrees:
            res.append(Resultat(
                BLOQUANT, "migration",
                f"data/{MARQUEUR_MIGRATION} présent : les données ont migré vers un dossier "
                f"partagé. Passer --donnees <dossier>, ou poser {VARIABLE} puis redémarrer "
                "l'application et les terminaux",
            ))
            return None
    if not vise:
        res.append(Resultat(BLOQUANT, "données", "dossier de données vide : passer un chemin à "
                            "--donnees, ou retirer l'option pour le mode local"))
        return None
    res.append(Resultat(OK, "données", f"partagé — {vise}"))
    try:
        emp = resoudre(racine, donnees)
    except DossierDonneesIntrouvable:
        res.append(Resultat(BLOQUANT, "dossier de données", "introuvable : vérifier que le Drive "
                            "est monté, ou créer le dossier avec initialiser-donnees --vers <dossier>"))
        return None
    except DossierDonneesDansLeDepot:
        res.append(Resultat(OK, "dossier de données", "présent"))
        res.append(Resultat(BLOQUANT, "hors dépôt", "le dossier est dans le dépôt ou dans un arbre "
                            "git : les données n'entrent jamais dans git, choisir un dossier hors "
                            "de tout dépôt"))
        return None
    except DossierDonneesNonInitialise:
        res.append(Resultat(OK, "dossier de données", "présent"))
        res.append(Resultat(OK, "hors dépôt", "hors de tout arbre git"))
        res.append(Resultat(BLOQUANT, "marqueur", f"{MARQUEUR} absent : dossier non initialisé, "
                            "le préparer avec initialiser-donnees --vers <dossier>"))
        return None
    res.append(Resultat(OK, "dossier de données", "présent"))
    res.append(Resultat(OK, "hors dépôt", "hors de tout arbre git"))
    res.append(Resultat(OK, "marqueur", MARQUEUR))
    try:
        fd, tmp = tempfile.mkstemp(prefix=".poste-", suffix=".tmp", dir=emp.racine_donnees)
        os.close(fd)
        os.remove(tmp)
    except OSError as e:
        res.append(Resultat(BLOQUANT, "écriture", f"impossible d'écrire dans le dossier de données "
                            f"({_raison(e, emp.racine_donnees)})"))
    else:
        res.append(Resultat(OK, "écriture", "fichier temporaire créé puis supprimé"))
    return emp


def _variable_utilisateur() -> str | None:
    """Valeur de `HKCU\\Environment\\PROSPECTION_DONNEES` sous Windows ; None ailleurs ou si absente.

    Une variable « User » posée par `SetEnvironmentVariable` n'atteint que les processus lancés
    après elle : tant que l'application et les terminaux n'ont pas redémarré, ils ne la voient pas.
    """
    if sys.platform != "win32":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as cle:
            valeur, sorte = winreg.QueryValueEx(cle, VARIABLE)
        if sorte == winreg.REG_EXPAND_SZ:
            valeur = winreg.ExpandEnvironmentStrings(valeur)
    except Exception:  # clé absente (OSError), registre inaccessible : rien à comparer
        return None
    return str(valeur) if valeur is not None else None


def _meme_chemin(a: str, b: str) -> bool:
    return os.path.normcase(os.path.normpath(a.strip())) == os.path.normcase(os.path.normpath(b.strip()))


def _controle_variable_windows() -> list[Resultat]:
    posee = _variable_utilisateur()
    if posee is None or not posee.strip():
        return []
    processus = os.environ.get(VARIABLE, "")
    if processus.strip() and _meme_chemin(posee, processus):
        return [Resultat(OK, "variable", f"{VARIABLE} vue par ce processus")]
    # la valeur n'est pas affichée : c'est un chemin absolu, déjà donné par la ligne `données`
    return [Resultat(AVERTISSEMENT, "variable", f"{VARIABLE} posée pour l'utilisateur mais "
                     "différente de celle de ce processus : redémarrez l'application et les "
                     "terminaux")]


def _base_relative(emp: Emplacements, racine: str) -> str:
    """Base des chemins affichés : le dossier partagé, ou la racine du dépôt en mode local."""
    return emp.racine_donnees if emp.mode == "partage" else os.path.abspath(racine)


def _rel(chemin: str, base: str) -> str:
    try:
        r = os.path.relpath(chemin, base)
    except ValueError:  # autre lecteur sous Windows
        r = os.path.basename(chemin)
    return r.replace(os.sep, "/")


def _raison(e: BaseException, base: str) -> str:
    """Cause d'une erreur, sans chemin absolu : la racine affichée une fois suffit."""
    if isinstance(e, OSError) and e.strerror:
        texte = e.strerror
    else:
        texte = str(e)
    for b in {base, os.path.abspath(base)}:
        texte = texte.replace(b + os.sep, "").replace(b, "<données>")
    return f"{type(e).__name__} : {texte}" if texte else type(e).__name__


def _controle_config(emp: Emplacements, racine: str, config: str | None, base: str) -> list[Resultat]:
    try:
        from . import config as cfg_mod
    except SystemExit:  # PyYAML absent : déjà signalé par le contrôle `yaml`
        return [Resultat(BLOQUANT, "config", "non chargeable sans PyYAML")]
    if emp.mode == "partage":
        chemin = emp.config
        if config:  # la même règle que prepare, lots et finaliser
            return [Resultat(BLOQUANT, "config", "--config ne s'emploie pas en mode partagé : la "
                             f"config est {_rel(chemin, base)} du dossier de données, la même pour "
                             "tous les postes. Retirer --config")]
        if not os.path.isfile(chemin):
            return [Resultat(BLOQUANT, "config", f"{_rel(chemin, base)} absent : le créer avec "
                             "initialiser-donnees (ou y copier la config du profil)")]
    else:
        chemin = config
    try:
        cfg = cfg_mod.charger(chemin, racine=racine)
    except cfg_mod.CheminConfigIntrouvable:
        return [Resultat(BLOQUANT, "config", "aucune configuration : copier "
                         "templates/config-profil.example.yaml vers data/config.yaml et la remplir")]
    except Exception as e:
        marque = getattr(e, "problem_mark", None)
        if marque is not None:
            # une erreur YAML cite les lignes fautives, qui peuvent contenir le nom du profil
            detail = f"YAML invalide (ligne {marque.line + 1})"
        elif isinstance(e, (ValueError, OSError)):
            detail = _raison(e, base)
        else:
            detail = type(e).__name__
        return [Resultat(BLOQUANT, "config", f"non chargeable : {detail}")]
    # jamais le nom du profil, ni un nom de fichier qui pourrait le porter (le second nom de
    # config.CHEMINS_PAR_DEFAUT contient un prénom) : cette sortie peut finir dans une capture
    rel = _rel(cfg.chemin, base)
    nom = rel if rel in NOMS_CONFIG_AFFICHABLES else "nom de fichier masqué"
    return [Resultat(OK, "config", f"profil chargé ({nom})")]


def _controle_historique(emp: Emplacements, run: str | None, base: str) -> list[Resultat]:
    """Fichiers d'historique reconnus, lignes, clés recalculées depuis les JSON bruts."""
    partage = emp.mode == "partage"
    dossier_csv = emp.historique if partage else emp.racine_donnees
    h = Historique()
    reconnus = lignes = 0
    illisibles: list[tuple[str, BaseException]] = []
    for f in sorted(glob.glob(os.path.join(glob.escape(dossier_csv), "*.csv"))):
        avant = len(h.ignores)
        try:
            n = h.ajouter_csv(f, stricte=True)
        except (OSError, ValueError, csv.Error) as e:  # UnicodeDecodeError est une ValueError
            illisibles.append((f, e))
            continue
        if len(h.ignores) == avant:
            reconnus += 1
            lignes += n
    for d in sorted(glob.glob(os.path.join(glob.escape(emp.runs), "*"))):
        if not os.path.isdir(d) or os.path.basename(d) == run:
            continue
        for f in sorted(glob.glob(os.path.join(glob.escape(d), "*.json"))):
            if os.path.basename(f).startswith(NON_BRUTS):
                continue
            try:
                h.ajouter_run(f)
            except (OSError, ValueError, AttributeError, TypeError, KeyError) as e:
                illisibles.append((f, e))

    res = [
        Resultat(BLOQUANT, "historique", f"fichier illisible : {_rel(f, base)} ({_raison(e, base)}). "
                 "Hors connexion ? Rendre le dossier « Disponible hors connexion » dans Drive")
        for f, e in illisibles
    ]
    res.append(Resultat(OK, "historique", f"{reconnus} fichier(s) reconnu(s), {lignes} ligne(s)"))
    res.append(Resultat(OK, "clés JSON", f"{h.cles_json} clé(s) recalculée(s) depuis "
                        f"{h.json_lus} JSON brut(s)"))
    if reconnus and not h.json_lus:
        # un DELTA (ou un MASTER migré) porte les clés calculées à son époque, sur la carte entière
        res.append(Resultat(AVERTISSEMENT, "historique", "DELTA présents sans aucun JSON brut : clés "
                            "de contenu antérieures au correctif #3 non recalculées : doublons "
                            "possibles sur les runs récents"))
    if partage and not lignes and not h.cles_json:
        res.append(Resultat(AVERTISSEMENT, "historique", "vide : tout post sera compté comme "
                            "nouveau. Migrer l'historique avec initialiser-donnees"))
    if partage and h.ignores:
        res.append(Resultat(AVERTISSEMENT, "historique", "ignoré(s), ni MASTER ni DELTA ou fichier "
                            "de travail : " + ", ".join(_rel(f, base) for f in h.ignores)))
    return res


def _controle_conflits(emp: Emplacements, base: str) -> list[Resultat]:
    """Copies en conflit : BLOQUANT dans historique/, classeurs/ et sur la config ; ailleurs, avertir."""
    def cle(c: str) -> str:
        return os.path.normcase(os.path.abspath(c))

    zones = {cle(z) for z in (emp.historique, emp.classeurs) if z}
    racine = cle(emp.racine_donnees)
    racines = [emp.racine_donnees]
    if not cle(emp.runs).startswith(racine + os.sep):  # mode local : runs/ est à côté de data/
        racines.append(emp.runs)
    critiques: list[str] = []
    autres: list[str] = []
    for r in racines:
        for dossier, sous, fichiers in os.walk(r):
            sous.sort()
            for n in sorted(sous + fichiers):
                if not copie_en_conflit(n):
                    continue
                c = os.path.join(dossier, n)
                parent = cle(dossier)
                if parent in zones or (parent == racine and n.lower().startswith("config")):
                    critiques.append(c)
                else:
                    autres.append(c)
    res = []
    if critiques:
        res.append(Resultat(BLOQUANT, "copies en conflit", ", ".join(_rel(c, base) for c in critiques)
                            + " : fusionner à la main avec l'original, puis supprimer la copie"))
    else:
        res.append(Resultat(OK, "copies en conflit", "aucune dans historique/, classeurs/ ni sur la config"))
    if autres:
        res.append(Resultat(AVERTISSEMENT, "copies en conflit", ", ".join(_rel(c, base) for c in autres)
                            + " : à fusionner"))
    return res


def _controle_verrou(emp: Emplacements, run: str | None) -> list[Resultat]:
    if emp.mode != "partage":
        return [Resultat(OK, "verrou", "sans objet en mode local")]
    dossier = emp.racine_donnees
    try:
        lus = verrou_mod.etats(dossier)
        occ = verrou_mod.occupants(dossier, run) if run else []
    except OSError as e:
        return [Resultat(BLOQUANT if run else AVERTISSEMENT, "verrou",
                         f"illisible ({_raison(e, dossier)})")]
    if run:
        if occ:
            return [Resultat(BLOQUANT, "verrou", f"occupé pour le run {run} : "
                             + " ; ".join(verrou_mod.decrire(e) for e in occ))]
        etat = " ; ".join(verrou_mod.decrire(e) for e in lus) or "aucun verrou"
        return [Resultat(OK, "verrou", f"libre pour ce poste et le run {run} ({etat})")]
    if not lus:
        return [Resultat(OK, "verrou", "aucun verrou")]
    poste = socket.gethostname()
    out = []
    for e in lus:
        ailleurs = e.get("corrompu") or (e.get("etat") == "pris" and e.get("poste") != poste)
        out.append(Resultat(AVERTISSEMENT if ailleurs else OK, "verrou", verrou_mod.decrire(e)))
    return out


def _controle_run(emp: Emplacements, run: str | None, base: str) -> list[Resultat]:
    """Mode partagé, avec `--run` : ce que `lots` et `prepare` refuseraient, dit avant le scraping.

    Identifiant hors format, run déjà finalisé (`historique/DELTA_<run>.csv`), run préparé sur
    un autre poste (`runs/<run>/proprietaire.json`) : BLOQUANT.
    """
    if emp.mode != "partage" or not run:
        return []
    if cle_classeur(f"prospection_{run}.xlsx") is None:  # même format que run.cle_run
        return [Resultat(BLOQUANT, "run", f"identifiant de run invalide : « {run} » (JJ-MM-AAAA, "
                         "ou JJ-MM-AAAA-n avec n ≥ 2)")]
    delta = os.path.join(emp.historique, f"DELTA_{run}.csv")
    if os.path.exists(delta):
        return [Resultat(BLOQUANT, "run", f"run {run} déjà finalisé ({_rel(delta, base)} présent) : "
                         "prendre l'identifiant suivant (JJ-MM-AAAA-n)")]
    proprio = os.path.join(emp.runs, run, PROPRIETAIRE)
    if os.path.exists(proprio):
        try:
            with open(proprio, encoding="utf-8-sig") as fh:  # BOM du Bloc-notes
                p = json.load(fh)
        except (OSError, ValueError) as e:
            return [Resultat(BLOQUANT, "run", f"fichier illisible : {_rel(proprio, base)} "
                             f"({_raison(e, base)})")]
        poste = p.get("poste") if isinstance(p, dict) else None
        if not poste or poste != socket.gethostname():
            return [Resultat(BLOQUANT, "run", f"run {run} préparé sur le poste {poste or '?'} : le "
                             "finir sur ce poste-là, ou le reprendre ici avec --forcer")]
    return [Resultat(OK, "run", f"run {run} : ni finalisé, ni préparé sur un autre poste")]


def _controle_classeur(emp: Emplacements, base: str) -> list[Resultat]:
    partage = emp.mode == "partage"
    d = emp.classeurs
    noms = sorted(os.listdir(d)) if os.path.isdir(d) else []
    dates = [(cle_classeur(n), n) for n in noms if cle_classeur(n) is not None]
    res = []
    if not dates:
        res.append(Resultat(AVERTISSEMENT if partage else OK, "classeur",
                            "aucun : finaliser partira d'un classeur vide"))
    else:
        nom = max(dates)[1]
        chemin = os.path.join(d, nom)
        if zipfile.is_zipfile(chemin):
            res.append(Resultat(OK, "classeur", f"le plus récent : {_rel(chemin, base)}"))
        else:  # « en ligne uniquement » hors connexion, ou fichier abîmé
            res.append(Resultat(BLOQUANT if partage else AVERTISSEMENT, "classeur",
                                f"{_rel(chemin, base)} illisible : le rendre disponible hors "
                                "connexion, ou le réparer"))
    ouverts = [n for n in noms if n.startswith("~$")]
    if ouverts:
        res.append(Resultat(AVERTISSEMENT, "classeur", "ouvert dans Excel ("
                            + ", ".join(_rel(os.path.join(d, n), base) for n in ouverts)
                            + ") : le fermer avant finaliser"))
    return res


# --- code (git) : jamais BLOQUANT --------------------------------------------------------------

def _git(racine: str, *args: str) -> str | None:
    """Sortie d'une commande git dans `racine`, ou None (git absent, pas un dépôt, erreur)."""
    try:
        p = subprocess.run(
            ["git", "-C", racine, *args], capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout.strip() if p.returncode == 0 else None


def _age(secondes: float) -> str:
    j, reste = divmod(max(0, int(secondes)), UN_JOUR)
    h = reste // 3600
    return f"{j} j {h} h" if j else f"{h} h"


def _controle_git(racine: str) -> list[Resultat]:
    """Branche, commit, dernier fetch, retard sur l'amont. Simple information quand git manque."""
    if _git(racine, "--version") is None:
        return [Resultat(OK, "code", "git introuvable : contrôles du code sautés (information)")]
    if _git(racine, "rev-parse", "--is-inside-work-tree") != "true":
        return [Resultat(OK, "code", "pas un dépôt git : contrôles du code sautés (information)")]
    commit = _git(racine, "rev-parse", "--short", "HEAD")
    if commit is None:
        return [Resultat(OK, "code", "aucun commit (information)")]
    branche = _git(racine, "rev-parse", "--abbrev-ref", "HEAD") or "HEAD"
    res = []
    if branche == "HEAD":
        res.append(Resultat(OK, "code", f"HEAD détaché, commit {commit} (information)"))
    elif branche in ("main", "dev"):
        res.append(Resultat(OK, "code", f"branche {branche}, commit {commit}"))
    else:
        res.append(Resultat(AVERTISSEMENT, "code", f"branche {branche}, commit {commit} : les runs "
                            "se lancent depuis main ou dev"))

    commun = _git(racine, "rev-parse", "--git-common-dir")
    fetch = os.path.join(os.path.abspath(racine), commun, "FETCH_HEAD") if commun else None
    if fetch and os.path.isfile(fetch):
        age = time.time() - os.path.getmtime(fetch)
        if age > UN_JOUR:
            res.append(Resultat(AVERTISSEMENT, "dernier fetch", f"il y a {_age(age)} : "
                                "git pull --ff-only"))
        else:
            res.append(Resultat(OK, "dernier fetch", f"il y a {_age(age)}"))
    else:
        res.append(Resultat(OK, "dernier fetch", "aucun enregistré (information)"))

    amont = _git(racine, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if not amont:
        res.append(Resultat(OK, "amont", "aucun (information)"))
        return res
    retard = _git(racine, "rev-list", "--count", "HEAD..@{u}")
    if retard is not None and retard.isdigit() and int(retard) > 0:
        res.append(Resultat(AVERTISSEMENT, "amont", f"{retard} commit(s) de retard sur {amont} "
                            "(au dernier fetch) : git pull --ff-only"))
    else:
        res.append(Resultat(OK, "amont", f"à jour par rapport à {amont} (au dernier fetch)"))
    return res


# --- ligne de commande -------------------------------------------------------------------------

def cmd_poste(args: argparse.Namespace) -> int:
    """`poste [--run R]` : une ligne par contrôle ; code 0 sans bloquant, 2 sinon."""
    resultats = verifier(
        getattr(args, "racine", ".") or ".", getattr(args, "donnees", None),
        getattr(args, "run", None), getattr(args, "config", None),
    )
    for r in resultats:
        print(r.ligne())
    nb_b = sum(r.niveau == BLOQUANT for r in resultats)
    nb_a = sum(r.niveau == AVERTISSEMENT for r in resultats)
    print(f"\nbilan : {nb_b} bloquant(s), {nb_a} avertissement(s). Cette sortie nomme le poste et "
          "des chemins : ne jamais la coller dans une PR ou une issue.")
    return 2 if nb_b else 0

