"""Garde anti-fuite : aucune donnée personnelle n'entre dans git (README, « Données personnelles »).

Les posts collectés contiennent des noms, des profils et des adresses de tiers. `data/` et `runs/`
sont exclus par le `.gitignore`, mais un `git add -f` passerait. Ce test fait échouer la porte, en
local comme en intégration continue, dès qu'un fichier interdit est suivi par git ou simplement
indexé. Le README et le CHANGELOG [1.0.0] annonçaient ce contrôle alors qu'il n'existait pas (PL-08).

Le mode partagé (données sur un Drive, plusieurs PC) ajoute ses propres noms : dossiers `runs/`,
`historique/` et `classeurs/` à n'importe quelle profondeur, verrou, marqueurs, config de profil
(seul un gabarit `templates/<nom>.example.yaml` passe) et exports PDF. Une copie du dossier de données posée par erreur dans le
dépôt est ainsi refusée, où qu'elle soit.
"""
from __future__ import annotations

import fnmatch
import shutil
import subprocess
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
AUTORISES = {"data/README.md", "data/.gitkeep", "runs/.gitkeep"}
PREFIXES_INTERDITS = ("data/", "runs/", ".claude/worktrees/")
FICHIERS_INTERDITS = {".claude/settings.local.json"}
EXTENSIONS_INTERDITES = (".xlsx", ".xlsm", ".csv", ".pdf")
# mode partagé : un segment de chemin, à n'importe quelle profondeur
SEGMENTS_INTERDITS = {"runs", "historique", "classeurs"}
NOMS_INTERDITS = {".prospection-donnees", "migre_vers_partage.txt"}
MOTIFS_INTERDITS = ("verrou*.json",)
# la config d'un profil n'a sa place que sous forme de gabarit : templates/<nom>.example.yaml.
# Une vraie config posée à côté du gabarit (templates/config.yaml) est refusée.
MOTIF_CONFIG = "config*.yaml"
MOTIF_GABARIT = "*.example.yaml"


def _est_gabarit(segments: list[str]) -> bool:
    return (len(segments) == 2 and segments[0] == "templates"
            and fnmatch.fnmatchcase(segments[1], MOTIF_GABARIT))


def fichiers_interdits(suivis: list[str]) -> list[str]:
    """Fichiers suivis qui ne doivent pas l'être : données, résultats de run, classeurs, exports,
    copies de travail et réglages locaux de Claude Code, fichiers du dossier de données partagé."""
    interdits = []
    for f in suivis:
        f = f.replace("\\", "/")
        if f in AUTORISES:
            continue
        segments = f.lower().split("/")
        nom = segments[-1]
        if (
            f.startswith(PREFIXES_INTERDITS)
            or f in FICHIERS_INTERDITS
            or f.lower().endswith(EXTENSIONS_INTERDITES)
            or SEGMENTS_INTERDITS.intersection(segments)
            or nom in NOMS_INTERDITS
            or any(fnmatch.fnmatchcase(nom, m) for m in MOTIFS_INTERDITS)
            or (fnmatch.fnmatchcase(nom, MOTIF_CONFIG) and not _est_gabarit(segments))
        ):
            interdits.append(f)
    return interdits


def test_les_fichiers_de_methode_passent():
    suivis = sorted(AUTORISES) + [
        "README.md",
        "prospection/run.py",
        "templates/config-profil.example.yaml",
        ".github/workflows/porte.yml",
        ".claude/settings.json",
        # le code du mode partagé porte ces mots sans être une donnée
        "prospection/emplacements.py",
        "prospection/verrou.py",
        "tests/conftest.py",
        "tests/test_verrou.py",
        "tests/test_donnees_partagees.py",
        "docs/10-run-recurrent.md",
        "templates/config-autre-profil.example.yaml",
    ]
    assert fichiers_interdits(suivis) == []


@pytest.mark.parametrize(
    "fichier",
    [
        "data/config.yaml",
        "data/MASTER.csv",
        "runs/24-09-2026/LOT_A.json",
        "export_leads.csv",
        "docs/prospection_24-09-2026.XLSX",
        ".claude/worktrees/copie/README.md",
        ".claude/settings.local.json",
    ],
)
def test_une_donnee_est_refusee(fichier):
    assert fichiers_interdits([fichier]) == [fichier]


@pytest.mark.parametrize(
    "fichier",
    [
        # un segment `runs`, `historique` ou `classeurs`, à n'importe quelle profondeur
        "donnees/runs/01-01-2030/LOT_A.json",
        "copie/historique/DELTA_01-01-2030.txt",
        "historique/notes.md",
        "sauvegarde/Classeurs/LISEZMOI.md",
        # verrou, copies en conflit comprises
        "verrou.json",
        "donnees/verrou (1).json",
        # marqueurs du dossier partagé et de la migration
        ".prospection-donnees",
        "donnees/.prospection-donnees",
        "MIGRE_VERS_PARTAGE.txt",
        # config de profil hors de templates/
        "config.yaml",
        "donnees/config (1).yaml",
        "docs/config-profil.yaml",
        # dans templates/, seul un gabarit `<nom>.example.yaml` passe : une vraie config posée à
        # côté du gabarit (la faute la plus probable) est refusée
        "templates/config.yaml",
        "templates/config-prenom.yaml",
        "templates/perso/config.yaml",
        "templates/perso/config-profil.example.yaml",
        # exports PDF
        "docs/fiche.pdf",
        "export.PDF",
    ],
)
def test_un_fichier_du_mode_partage_est_refuse(fichier):
    assert fichiers_interdits([fichier]) == [fichier]


def test_aucune_donnee_suivie_par_git():
    if shutil.which("git") is None or not (RACINE / ".git").exists():
        pytest.skip("hors d'un dépôt git (archive téléchargée) : rien à contrôler")
    sortie = subprocess.run(
        ["git", "ls-files", "-z"], cwd=RACINE, capture_output=True, check=True
    ).stdout.decode("utf-8")
    interdits = fichiers_interdits([f for f in sortie.split("\0") if f])
    assert interdits == [], (
        "données personnelles suivies par git — les retirer de l'index avec "
        f"`git rm --cached <fichier>` : {interdits}"
    )
