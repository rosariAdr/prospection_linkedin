"""Emplacements des données : mode local ou mode partagé (plusieurs PC).

GitHub porte le code et chaque PC le clone. Les données, elles, ne vont jamais dans git :

- **mode local** (comportement historique) : `data/` et `runs/` sous la racine du dépôt ;
- **mode partagé** : un dossier hors du dépôt, synchronisé entre les PC (Google Drive pour
  ordinateur, par exemple), désigné par `--donnees` ou par la variable `PROSPECTION_DONNEES`.
  Il contient `config.yaml`, `historique/`, `runs/`, `classeurs/` et le marqueur
  `.prospection-donnees`, créés par `initialiser-donnees`.

Priorité : l'argument `donnees`, puis la variable (vide ou faite d'espaces = absente), puis le
mode local. Tout problème d'emplacement lève une exception nommée : on ne retombe jamais en
silence sur un autre dossier (principe « bruyant plutôt que silencieux »).
"""
from __future__ import annotations

import ntpath
import os
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

__all__ = [
    "MARQUEUR", "MARQUEUR_MIGRATION", "VARIABLE", "Emplacements", "resoudre", "garde_hors_depot",
    "DossierDonneesIntrouvable", "DossierDonneesNonInitialise", "DossierDonneesDansLeDepot",
    "DonneesMigrees",
]

MARQUEUR = ".prospection-donnees"          # créé par initialiser-donnees dans le dossier partagé (JSON {"version": 1})
MARQUEUR_MIGRATION = "MIGRE_VERS_PARTAGE.txt"  # déposé dans le data/ local après migration
VARIABLE = "PROSPECTION_DONNEES"


class DossierDonneesIntrouvable(FileNotFoundError):
    pass


class DossierDonneesNonInitialise(RuntimeError):
    """Le dossier existe mais ne porte pas le MARQUEUR."""


class DossierDonneesDansLeDepot(RuntimeError):
    """Le dossier de données est dans le dépôt, ou dans un autre arbre de travail git."""


class DonneesMigrees(RuntimeError):
    """Mode local alors que le data/ local porte MARQUEUR_MIGRATION."""


@dataclass(frozen=True)
class Emplacements:
    mode: str              # "local" | "partage"
    racine_donnees: str    # absolu. local : <racine>/data ; partage : le dossier
    config: str | None     # local : None (charger() garde sa recherche actuelle) ; partage : <donnees>/config.yaml (même s'il manque)
    runs: str              # local : <racine>/runs ; partage : <donnees>/runs
    historique: str | None # partage : <donnees>/historique ; local : None
    classeurs: str         # local : <racine>/data ; partage : <donnees>/classeurs
    verrou: str | None     # partage : <donnees>/verrou.json ; local : None

    def ligne_mode(self) -> str:
        libelle = "partagé" if self.mode == "partage" else "local"
        return f"données : {libelle} — {self.racine_donnees}"


def resoudre(racine: str = ".", donnees: str | None = None) -> Emplacements:
    """Emplacements des données pour la racine de dépôt `racine`.

    Un `donnees` relatif se lit depuis le répertoire courant, pas depuis `racine` : la ligne de
    commande le convertit en absolu avant le `chdir` de `--racine`.
    """
    racine_abs = os.path.abspath(racine)
    if donnees is not None:
        if not donnees.strip():
            # un `--donnees "$env:X"` sur une variable non posée : on ne bascule pas en silence
            raise DossierDonneesIntrouvable(
                "dossier de données vide : passer un chemin à --donnees, ou retirer l'option "
                "pour le mode local."
            )
        choisi = donnees
    else:
        choisi = os.environ.get(VARIABLE, "")
    if not choisi.strip():
        return _local(racine_abs)
    return _partage(os.path.abspath(choisi), racine_abs)


def _local(racine: str) -> Emplacements:
    data = os.path.join(racine, "data")
    migration = os.path.join(data, MARQUEUR_MIGRATION)
    if os.path.exists(migration):
        raise DonneesMigrees(
            f"les données ont migré vers un dossier partagé ({migration}) : le mode local lirait "
            "un data/ périmé. Passer --donnees <dossier>, ou poser la variable "
            f"{VARIABLE} puis redémarrer l'application et les terminaux (une variable « User » "
            "n'atteint que les processus lancés après elle)."
        )
    return Emplacements(
        mode="local", racine_donnees=data, config=None, runs=os.path.join(racine, "runs"),
        historique=None, classeurs=data, verrou=None,
    )


def _partage(dossier: str, racine: str) -> Emplacements:
    # contrôles dans l'ordre de la spec : existence, garde hors dépôt, marqueur
    if not os.path.isdir(dossier):
        raise DossierDonneesIntrouvable(
            f"dossier de données introuvable : {dossier}. Vérifier le chemin et que le Drive est "
            "monté, ou créer le dossier avec `python -m prospection.run initialiser-donnees "
            "--vers <dossier>`."
        )
    garde_hors_depot(dossier, racine)
    if not os.path.isfile(os.path.join(dossier, MARQUEUR)):
        raise DossierDonneesNonInitialise(
            f"{dossier} n'est pas un dossier de données initialisé (marqueur {MARQUEUR} absent). "
            "Le préparer avec `python -m prospection.run initialiser-donnees --vers <dossier>`."
        )
    return Emplacements(
        mode="partage", racine_donnees=dossier, config=os.path.join(dossier, "config.yaml"),
        runs=os.path.join(dossier, "runs"), historique=os.path.join(dossier, "historique"),
        classeurs=os.path.join(dossier, "classeurs"), verrou=os.path.join(dossier, "verrou.json"),
    )


# --- garde hors dépôt --------------------------------------------------------------------------

def garde_hors_depot(chemin: str, racine: str) -> None:
    """Refuse un dossier de données situé dans le dépôt ou dans un arbre de travail git.

    Les posts collectés contiennent des données de tiers : un dossier de données sous un arbre
    git finirait tôt ou tard dans un commit. Le contrôle porte sur le chemin LITTÉRAL absolu et
    sur le chemin RÉSOLU (`Path.resolve()` suit les liens et les jonctions), dans les deux sens :
    un lien hors du dépôt qui pointe dedans est refusé, comme un lien du dépôt qui pointe dehors.

    Sans le binaire git ni `git check-ignore` : un ancêtre (le chemin compris) qui contient
    `.git`, fichier (copie de travail, sous-module) ou dossier, suffit à refuser.
    """
    racines = _variantes(racine)
    for c in _variantes(chemin):
        for r in racines:
            if _est_sous(c, r):
                raise DossierDonneesDansLeDepot(
                    f"le dossier de données {c} est dans le dépôt {r} : les données personnelles "
                    "n'entrent jamais dans git. Choisir un dossier hors du dépôt (sur le Drive, "
                    "par exemple)."
                )
        arbre = _arbre_git(c)
        if arbre is not None:
            raise DossierDonneesDansLeDepot(
                f"le dossier de données {c} est dans un arbre de travail git ({arbre} contient "
                ".git) : les données personnelles n'entrent jamais dans git. Choisir un dossier "
                "hors de tout dépôt."
            )


def _variantes(chemin: str) -> list[str]:
    """Chemin littéral absolu, puis chemin résolu s'il diffère."""
    litteral = os.path.abspath(chemin)
    out = [litteral]
    try:
        resolu = str(Path(litteral).resolve())
    except (OSError, RuntimeError):  # boucle de liens : le littéral reste contrôlé
        return out
    if os.path.normcase(resolu) != os.path.normcase(litteral):
        out.append(resolu)
    return out


def _est_sous(chemin: str, racine: str, chemins=os.path) -> bool:
    """True si `chemin` est `racine` ou l'un de ses descendants.

    `chemins` vaut `os.path` ; les tests passent `ntpath` ou `posixpath` pour vérifier la logique
    Windows sur n'importe quelle plateforme. La casse est neutralisée par `normcase` (sans effet
    sous POSIX). Deux lecteurs différents ne sont jamais l'un sous l'autre, et
    `is_relative_to` ne lève pas de `ValueError`.
    """
    pur = PureWindowsPath if chemins is ntpath else PurePosixPath
    c = pur(chemins.normcase(chemins.normpath(chemin)))
    r = pur(chemins.normcase(chemins.normpath(racine)))
    return c.is_relative_to(r)


def _arbre_git(chemin: str) -> str | None:
    """Premier ancêtre de `chemin` (lui compris) qui contient `.git`, ou None."""
    p = Path(chemin)
    for a in (p, *p.parents):
        if os.path.lexists(os.path.join(a, ".git")):
            return str(a)
    return None
