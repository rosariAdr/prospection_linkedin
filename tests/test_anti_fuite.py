"""Garde anti-fuite : aucune donnée personnelle n'entre dans git (README, « Données personnelles »).

Les posts collectés contiennent des noms, des profils et des adresses de tiers. `data/` et `runs/`
sont exclus par le `.gitignore`, mais un `git add -f` passerait. Ce test fait échouer la porte, en
local comme en intégration continue, dès qu'un fichier interdit est suivi par git ou simplement
indexé. Le README et le CHANGELOG [1.0.0] annonçaient ce contrôle alors qu'il n'existait pas (PL-08).
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parent.parent
AUTORISES = {"data/README.md", "data/.gitkeep", "runs/.gitkeep"}
PREFIXES_INTERDITS = ("data/", "runs/", ".claude/worktrees/")
FICHIERS_INTERDITS = {".claude/settings.local.json"}
EXTENSIONS_INTERDITES = (".xlsx", ".xlsm", ".csv")


def fichiers_interdits(suivis: list[str]) -> list[str]:
    """Fichiers suivis qui ne doivent pas l'être : données, résultats de run, classeurs, exports,
    copies de travail et réglages locaux de Claude Code."""
    interdits = []
    for f in suivis:
        f = f.replace("\\", "/")
        if f in AUTORISES:
            continue
        if (
            f.startswith(PREFIXES_INTERDITS)
            or f in FICHIERS_INTERDITS
            or f.lower().endswith(EXTENSIONS_INTERDITES)
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
