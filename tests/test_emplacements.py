"""Tests de `prospection.emplacements` : mode local ou partagé, garde hors dépôt.

Tout se passe dans `tmp_path`, avec des dossiers fictifs : jamais le vrai dossier de données.
La fixture de `tests/conftest.py` retire `PROSPECTION_DONNEES` : chaque test la pose lui-même.
Les cas qui passent par la ligne de commande (`--donnees` après la sous-commande, conversion en
absolu avant le `chdir` de `--racine`) sont testés avec les sous-commandes.
"""
import dataclasses
import json
import ntpath
import os
import posixpath
import sys

import pytest

from prospection.emplacements import (
    MARQUEUR,
    MARQUEUR_MIGRATION,
    DonneesMigrees,
    DossierDonneesDansLeDepot,
    DossierDonneesIntrouvable,
    DossierDonneesNonInitialise,
    _est_sous,
    garde_hors_depot,
    resoudre,
)


@pytest.fixture()
def depot(tmp_path):
    """Faux dépôt : un `.git` (dossier) et un data/ vide."""
    d = tmp_path / "depot"
    (d / ".git").mkdir(parents=True)
    (d / "data").mkdir()
    return d


def _donnees(base, nom="donnees", marqueur=True):
    """Dossier de données partagé fictif, initialisé (marqueur) ou non."""
    d = base / nom
    d.mkdir(parents=True)
    if marqueur:
        (d / MARQUEUR).write_text(json.dumps({"version": 1}), encoding="utf-8")
    return d


# --- résolution --------------------------------------------------------------------------------

def test_sans_argument_ni_variable_le_mode_est_local(depot):
    e = resoudre(str(depot))
    data = str(depot / "data")
    assert (e.mode, e.racine_donnees, e.config, e.runs, e.historique, e.classeurs, e.verrou) == (
        "local", data, None, str(depot / "runs"), None, data, None
    )
    assert e.ligne_mode() == f"données : local — {data}"


def test_argument_donnees_mode_partage(depot, tmp_path):
    d = _donnees(tmp_path)
    e = resoudre(str(depot), str(d))
    assert e.mode == "partage"
    assert e.racine_donnees == str(d)
    assert e.config == str(d / "config.yaml")  # même s'il manque : charger() le signalera
    assert e.runs == str(d / "runs")
    assert e.historique == str(d / "historique")
    assert e.classeurs == str(d / "classeurs")
    assert e.verrou == str(d / "verrou.json")
    assert e.ligne_mode() == f"données : partagé — {d}"


def test_les_emplacements_sont_figes(depot):
    e = resoudre(str(depot))
    with pytest.raises(dataclasses.FrozenInstanceError):
        e.mode = "partage"


def test_priorite_argument_puis_variable_puis_local(depot, tmp_path, monkeypatch):
    par_argument = _donnees(tmp_path, "par_argument")
    par_variable = _donnees(tmp_path, "par_variable")
    monkeypatch.setenv("PROSPECTION_DONNEES", str(par_variable))
    assert resoudre(str(depot), str(par_argument)).racine_donnees == str(par_argument)
    assert resoudre(str(depot)).racine_donnees == str(par_variable)
    monkeypatch.delenv("PROSPECTION_DONNEES")
    assert resoudre(str(depot)).mode == "local"


@pytest.mark.parametrize("valeur", ["", "   ", "\t"])
def test_variable_vide_ou_d_espaces_vaut_absente(depot, monkeypatch, valeur):
    monkeypatch.setenv("PROSPECTION_DONNEES", valeur)
    assert resoudre(str(depot)).mode == "local"


def test_argument_vide_refuse_plutot_que_mode_local(depot):
    # `--donnees "$env:X"` sur une variable non posée : bruyant plutôt que silencieux
    with pytest.raises(DossierDonneesIntrouvable):
        resoudre(str(depot), "  ")


def test_dossier_absent(depot, tmp_path, monkeypatch):
    with pytest.raises(DossierDonneesIntrouvable, match="initialiser-donnees"):
        resoudre(str(depot), str(tmp_path / "absent"))
    monkeypatch.setenv("PROSPECTION_DONNEES", str(tmp_path / "absent"))
    with pytest.raises(FileNotFoundError, match="initialiser-donnees"):
        resoudre(str(depot))


def test_dossier_non_initialise(depot, tmp_path):
    d = _donnees(tmp_path, marqueur=False)
    with pytest.raises(DossierDonneesNonInitialise, match="initialiser-donnees"):
        resoudre(str(depot), str(d))


def test_la_garde_hors_depot_passe_avant_le_marqueur(depot):
    # un dossier du dépôt sans marqueur : c'est la garde qui parle, pas « non initialisé »
    d = _donnees(depot, "donnees", marqueur=False)
    with pytest.raises(DossierDonneesDansLeDepot):
        resoudre(str(depot), str(d))


def test_un_chemin_relatif_se_lit_depuis_le_repertoire_courant(depot, tmp_path, monkeypatch):
    # la ligne de commande convertit --donnees en absolu AVANT le chdir de --racine : la
    # bibliothèque lit donc un relatif depuis le répertoire courant, jamais depuis la racine
    d = _donnees(tmp_path / "ailleurs")
    monkeypatch.chdir(tmp_path / "ailleurs")
    e = resoudre(str(depot), "donnees")
    assert e.racine_donnees == str(d)


def test_marqueur_de_migration_bloque_le_mode_local(depot, tmp_path):
    (depot / "data" / MARQUEUR_MIGRATION).write_text("migré", encoding="utf-8")
    with pytest.raises(DonneesMigrees) as exc:
        resoudre(str(depot))
    message = str(exc.value)
    assert "--donnees" in message and "redémarrer" in message
    # le marqueur ne concerne que le mode local : le mode partagé passe
    d = _donnees(tmp_path)
    assert resoudre(str(depot), str(d)).mode == "partage"


# --- garde hors dépôt --------------------------------------------------------------------------

@pytest.mark.parametrize("relatif", [".", "data", os.path.join("data", "sous", "donnees")])
def test_garde_refuse_le_depot_et_ses_sous_dossiers(tmp_path, relatif):
    racine = tmp_path / "depot_sans_git"  # sans .git : c'est la règle de la racine qui joue
    racine.mkdir()
    with pytest.raises(DossierDonneesDansLeDepot, match="dans le dépôt"):
        garde_hors_depot(str(racine / relatif), str(racine))


@pytest.mark.parametrize("nature", ["dossier", "fichier"])
def test_garde_refuse_un_autre_arbre_git(depot, tmp_path, nature):
    autre = tmp_path / "autre_projet"
    autre.mkdir()
    if nature == "dossier":
        (autre / ".git").mkdir()
    else:  # copie de travail ou sous-module : `.git` est un fichier
        (autre / ".git").write_text("gitdir: ailleurs/.git/worktrees/x\n", encoding="utf-8")
    with pytest.raises(DossierDonneesDansLeDepot, match="arbre de travail git"):
        garde_hors_depot(str(autre / "sous" / "donnees"), str(depot))


def test_garde_accepte_un_dossier_hors_depot(depot, tmp_path):
    garde_hors_depot(str(tmp_path / "drive" / "donnees"), str(depot))
    # un voisin dont le nom prolonge celui du dépôt n'est pas dans le dépôt
    garde_hors_depot(str(tmp_path / "depot2" / "donnees"), str(depot))


def _lien(lien, cible):
    """Lien symbolique, ou jonction sous Windows ; test sauté si la plateforme refuse les deux."""
    try:
        os.symlink(cible, lien, target_is_directory=True)
        return
    except (OSError, NotImplementedError):
        pass
    if sys.platform == "win32":
        try:
            import _winapi

            _winapi.CreateJunction(str(cible), str(lien))
            return
        except (ImportError, AttributeError, OSError):
            pass
    pytest.skip("ni lien symbolique ni jonction possible sur cette plateforme")


def test_garde_suit_un_lien_hors_du_depot_qui_pointe_dedans(tmp_path):
    racine = tmp_path / "depot_sans_git"
    (racine / "data").mkdir(parents=True)
    lien = tmp_path / "lien_vers_data"
    _lien(lien, racine / "data")
    with pytest.raises(DossierDonneesDansLeDepot):
        garde_hors_depot(str(lien), str(racine))


def test_garde_refuse_un_lien_du_depot_qui_pointe_dehors(tmp_path):
    racine = tmp_path / "depot_sans_git"
    racine.mkdir()
    drive = tmp_path / "drive"
    drive.mkdir()
    lien = racine / "donnees_drive"
    _lien(lien, drive)
    with pytest.raises(DossierDonneesDansLeDepot):
        garde_hors_depot(str(lien), str(racine))


def test_comparaison_windows_sans_valueerror_et_sans_casse():
    # logique isolée : `ntpath` et `posixpath` se testent sur n'importe quelle plateforme
    assert _est_sous(r"D:\donnees", r"C:\depot", ntpath) is False  # autre lecteur
    assert _est_sous(r"\\serveur\partage\donnees", r"C:\depot", ntpath) is False
    assert _est_sous(r"c:\DEPOT\Data", r"C:\depot", ntpath) is True  # casse Windows
    assert _est_sous("C:/depot/data", r"C:\depot", ntpath) is True
    assert _est_sous(r"C:\depot", r"C:\depot", ntpath) is True
    assert _est_sous(r"C:\depot2\data", r"C:\depot", ntpath) is False  # préfixe de nom
    assert _est_sous("/depot/data", "/depot", posixpath) is True
    assert _est_sous("/Depot/data", "/depot", posixpath) is False  # POSIX : casse significative
