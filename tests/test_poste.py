"""Tests de `prospection.poste` : le contrôle d'un PC avant un run (`poste [--run R]`).

Tout se passe dans `tmp_path` : un faux dépôt (`.git` factice, donc « pas un dépôt git » pour git)
et un faux dossier de données partagé, avec des données fictives. La variable « User » du
registre Windows est neutralisée par une fixture : le résultat ne dépend pas du PC qui teste.
Les fonctions sont appelées directement ; le câblage de la sous-commande vit dans `run.py`.
"""
import argparse
import contextlib
import csv
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

import openpyxl
import pytest

from prospection import poste
from prospection.config import CHEMINS_PAR_DEFAUT
from prospection.emplacements import MARQUEUR, MARQUEUR_MIGRATION
from prospection.poste import (
    AVERTISSEMENT, BLOQUANT, OK, cle_classeur, cmd_poste, copie_en_conflit, verifier,
)
from prospection.workbook import COLS

RUN = "01-01-2030"
NOM_PROFIL = "Marie Dupont"
CONFIG = (
    "version: 1\n"
    f"profil: {{nom: \"{NOM_PROFIL}\", email: \"marie.dupont@example.com\"}}\n"
    "scoring: {seuil_conservation: 3, seuil_redaction: 5}\n"
    "search_plan: {lots: {A: [\"formateur data\"]}}\n"
)
_VARIABLE_UTILISATEUR = poste._variable_utilisateur  # la vraie, avant neutralisation


@pytest.fixture(autouse=True)
def _sans_registre(monkeypatch):
    """La variable « User » de ce PC (s'il en a une) ne doit pas colorer les résultats."""
    monkeypatch.setattr(poste, "_variable_utilisateur", lambda: None)


@pytest.fixture()
def depot(tmp_path):
    d = tmp_path / "depot"
    (d / ".git").mkdir(parents=True)
    (d / "data").mkdir()
    return d


def _delta(chemin, auteur="Ecole Alpha"):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with open(chemin, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(COLS)
        w.writerow([{"auteur": auteur, "cle_contenu": "cle-alpha"}.get(c, "") for c in COLS])


def _brut(chemin):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps({"candidats": [{"auteur": "Ecole Alpha", "texte": "Annonce fictive"}]}),
                      encoding="utf-8")


def _classeur(chemin):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    openpyxl.Workbook().save(chemin)


@pytest.fixture()
def donnees(tmp_path):
    """Dossier de données partagé sain : marqueur, config, un DELTA, son JSON brut, un classeur."""
    d = tmp_path / "drive" / "donnees"
    d.mkdir(parents=True)
    (d / MARQUEUR).write_text(json.dumps({"version": 1}), encoding="utf-8")
    (d / "config.yaml").write_text(CONFIG, encoding="utf-8")
    _delta(d / "historique" / f"DELTA_{RUN}.csv")
    _brut(d / "runs" / RUN / "agent_A.json")
    _classeur(d / "classeurs" / f"prospection_{RUN}.xlsx")
    return d


def _niveaux(res, libelle):
    return [r.niveau for r in res if r.libelle == libelle]


def _non_ok(res):
    return [r for r in res if r.niveau != OK]


def _sortie(capsys, depot, donnees=None, run=None):
    code = cmd_poste(argparse.Namespace(racine=str(depot), donnees=donnees and str(donnees),
                                        run=run, config=None))
    return code, capsys.readouterr().out


# --- environnement sain --------------------------------------------------------------------------

def test_environnement_sain_code_0(depot, donnees, capsys):
    res = verifier(str(depot), str(donnees))
    assert _non_ok(res) == []
    libelles = {r.libelle for r in res}
    assert {"python", "openpyxl", "yaml", "données", "dossier de données", "hors dépôt", "marqueur",
            "écriture", "config", "historique", "clés JSON", "copies en conflit", "verrou",
            "classeur", "code"} <= libelles
    assert any(r.libelle == "historique" and "1 fichier(s) reconnu(s), 1 ligne(s)" in r.detail for r in res)
    assert any(r.libelle == "clés JSON" and "1 clé(s) recalculée(s) depuis 1 JSON" in r.detail for r in res)
    assert any(r.libelle == "classeur" and f"classeurs/prospection_{RUN}.xlsx" in r.detail for r in res)
    code, sortie = _sortie(capsys, depot, donnees)
    assert code == 0
    assert "0 bloquant(s)" in sortie and "ne jamais la coller dans une PR" in sortie


def test_racine_affichee_une_fois_puis_chemins_relatifs(depot, donnees, capsys):
    (donnees / "historique" / f"DELTA_{RUN} (1).csv").write_bytes(
        (donnees / "historique" / f"DELTA_{RUN}.csv").read_bytes())
    code, sortie = _sortie(capsys, depot, donnees)
    assert code == 2
    assert sortie.count(str(donnees)) == 1
    assert f"données : partagé — {donnees}" in sortie
    assert f"historique/DELTA_{RUN} (1).csv" in sortie


def test_rien_de_durable_n_est_ecrit(depot, donnees):
    avant = sorted(p.relative_to(donnees) for p in donnees.rglob("*"))
    verifier(str(depot), str(donnees), run=RUN)
    assert sorted(p.relative_to(donnees) for p in donnees.rglob("*")) == avant


def test_mode_local_sain(depot):
    (depot / "data" / "config.yaml").write_text(CONFIG, encoding="utf-8")
    _delta(depot / "data" / f"DELTA_{RUN}.csv")
    _brut(depot / "runs" / RUN / "agent_A.json")
    res = verifier(str(depot))
    assert _non_ok(res) == []
    assert [r.detail for r in res if r.libelle == "données"] == [f"local — {depot / 'data'}"]
    assert [r.detail for r in res if r.libelle == "verrou"] == ["sans objet en mode local"]
    assert any(r.libelle == "config" and r.detail == "profil chargé (data/config.yaml)" for r in res)


# --- bloquants -----------------------------------------------------------------------------------

def test_sans_config_code_2(depot, donnees, capsys):
    (donnees / "config.yaml").unlink()
    res = verifier(str(depot), str(donnees))
    assert _niveaux(res, "config") == [BLOQUANT]
    assert _sortie(capsys, depot, donnees)[0] == 2


def test_copie_en_conflit_dans_historique_code_2(depot, donnees, capsys):
    (donnees / "historique" / f"DELTA_{RUN} (1).csv").write_bytes(
        (donnees / "historique" / f"DELTA_{RUN}.csv").read_bytes())
    res = verifier(str(depot), str(donnees))
    bloquants = [r for r in res if r.niveau == BLOQUANT]
    assert [r.libelle for r in bloquants] == ["copies en conflit"]
    assert f"historique/DELTA_{RUN} (1).csv" in bloquants[0].detail
    assert _sortie(capsys, depot, donnees)[0] == 2


@pytest.mark.parametrize("copie", ["config (1).yaml", f"classeurs/prospection_{RUN} (1).xlsx"])
def test_copie_en_conflit_de_la_config_ou_d_un_classeur_bloque(depot, donnees, copie):
    (donnees / copie).write_text("copie", encoding="utf-8")
    res = verifier(str(depot), str(donnees))
    assert [r.libelle for r in res if r.niveau == BLOQUANT] == ["copies en conflit"]


def test_copie_en_conflit_ailleurs_avertit_seulement(depot, donnees):
    (donnees / "runs" / RUN / "agent_A (1).json").write_text("{}", encoding="utf-8")
    (donnees / "LISEZMOI (1).md").write_text("copie", encoding="utf-8")
    res = verifier(str(depot), str(donnees))
    assert [r for r in res if r.niveau == BLOQUANT] == []
    avert = [r for r in res if r.libelle == "copies en conflit" and r.niveau == AVERTISSEMENT]
    assert len(avert) == 1
    assert f"runs/{RUN}/agent_A (1).json" in avert[0].detail and "LISEZMOI (1).md" in avert[0].detail


def test_fichier_illisible_bloque_en_le_nommant(depot, donnees):
    (donnees / "historique" / "DELTA_02-01-2030.csv").write_bytes(b"auteur,url_post\n\xff\xfe\xfa\n")
    (donnees / "runs" / "02-01-2030").mkdir()
    (donnees / "runs" / "02-01-2030" / "agent_B.json").write_text("{tronqué", encoding="utf-8")
    res = verifier(str(depot), str(donnees))
    details = [r.detail for r in res if r.libelle == "historique" and r.niveau == BLOQUANT]
    assert len(details) == 2
    assert "historique/DELTA_02-01-2030.csv" in details[0]
    assert "runs/02-01-2030/agent_B.json" in details[1]


def test_marqueur_de_migration_en_mode_local_bloque(depot, capsys):
    (depot / "data" / MARQUEUR_MIGRATION).write_text("migré", encoding="utf-8")
    res = verifier(str(depot))
    assert _niveaux(res, "migration") == [BLOQUANT]
    assert _sortie(capsys, depot)[0] == 2


def test_dossier_absent_non_initialise_ou_dans_le_depot(depot, tmp_path):
    res = verifier(str(depot), str(tmp_path / "absent"))
    assert _niveaux(res, "dossier de données") == [BLOQUANT]
    nu = tmp_path / "nu"
    nu.mkdir()
    assert _niveaux(verifier(str(depot), str(nu)), "marqueur") == [BLOQUANT]
    dedans = depot / "donnees"
    dedans.mkdir()
    (dedans / MARQUEUR).write_text("{}", encoding="utf-8")
    assert _niveaux(verifier(str(depot), str(dedans)), "hors dépôt") == [BLOQUANT]
    assert _niveaux(verifier(str(depot), "  "), "données") == [BLOQUANT]


def test_ecriture_impossible_bloque(depot, donnees, monkeypatch):
    def refuse(*a, **kw):
        raise PermissionError(13, "Accès refusé")

    monkeypatch.setattr(poste.tempfile, "mkstemp", refuse)
    res = verifier(str(depot), str(donnees))
    assert _niveaux(res, "écriture") == [BLOQUANT]


def test_classeur_illisible_bloque_et_classeur_ouvert_avertit(depot, donnees):
    (donnees / "classeurs" / "prospection_02-01-2030.xlsx").write_text("en ligne uniquement",
                                                                        encoding="utf-8")
    (donnees / "classeurs" / f"~$prospection_{RUN}.xlsx").write_text("verrou", encoding="utf-8")
    res = verifier(str(depot), str(donnees))
    assert _niveaux(res, "classeur") == [BLOQUANT, AVERTISSEMENT]


# --- avertissements ------------------------------------------------------------------------------

def test_delta_sans_json_brut_avertit(depot, donnees):
    message = "clés de contenu antérieures au correctif #3 non recalculées"
    assert not any(message in r.detail for r in verifier(str(depot), str(donnees)))
    shutil.rmtree(donnees / "runs" / RUN)
    res = verifier(str(depot), str(donnees))
    assert [r.niveau for r in res if message in r.detail] == [AVERTISSEMENT]
    assert [r for r in res if r.niveau == BLOQUANT] == []


def test_historique_vide_avertit_en_mode_partage(depot, donnees):
    (donnees / "historique" / f"DELTA_{RUN}.csv").unlink()
    shutil.rmtree(donnees / "runs" / RUN)
    res = verifier(str(depot), str(donnees))
    assert any(r.niveau == AVERTISSEMENT and r.detail.startswith("vide") for r in res)


def test_csv_non_historique_ignore_et_signale(depot, donnees):
    (donnees / "historique" / "SUIVI_LEADS.csv").write_text("lead,organisation\n", encoding="utf-8")
    res = verifier(str(depot), str(donnees))
    avert = [r for r in res if r.libelle == "historique" and r.niveau == AVERTISSEMENT]
    assert len(avert) == 1 and "historique/SUIVI_LEADS.csv" in avert[0].detail


def test_aucun_classeur_avertit_en_mode_partage(depot, donnees):
    shutil.rmtree(donnees / "classeurs")
    assert _niveaux(verifier(str(depot), str(donnees)), "classeur") == [AVERTISSEMENT]


def test_variable_utilisateur_non_vue_par_le_processus(depot, donnees, monkeypatch):
    monkeypatch.setattr(poste, "_variable_utilisateur", lambda: str(donnees))
    res = verifier(str(depot), str(donnees))
    avert = [r for r in res if r.libelle == "variable"]
    assert [r.niveau for r in avert] == [AVERTISSEMENT]
    assert "redémarrez l'application et les terminaux" in avert[0].detail
    monkeypatch.setenv("PROSPECTION_DONNEES", str(donnees))
    assert _niveaux(verifier(str(depot)), "variable") == [OK]


class _FauxRegistre:
    """`winreg` factice : la clé Environment de HKCU porte la variable, en REG_EXPAND_SZ."""
    HKEY_CURRENT_USER, REG_SZ, REG_EXPAND_SZ = "HKCU", 1, 2

    def __init__(self, valeur):
        self.valeur = valeur

    def OpenKey(self, racine, chemin):
        assert (racine, chemin) == ("HKCU", "Environment")
        return contextlib.nullcontext("cle")

    def QueryValueEx(self, cle, nom):
        assert nom == "PROSPECTION_DONNEES"
        return self.valeur, self.REG_EXPAND_SZ

    def ExpandEnvironmentStrings(self, valeur):
        return valeur.replace("%LECTEUR%", "X:")


def test_le_registre_n_est_lu_que_sous_windows(monkeypatch):
    monkeypatch.setitem(sys.modules, "winreg", _FauxRegistre(r"%LECTEUR%\donnees"))
    monkeypatch.setattr(sys, "platform", "win32")
    assert _VARIABLE_UTILISATEUR() == r"X:\donnees"  # REG_EXPAND_SZ développé
    monkeypatch.setattr(sys, "platform", "linux")
    assert _VARIABLE_UTILISATEUR() is None


# --- verrou --------------------------------------------------------------------------------------

def _verrou(dossier, poste_, run=RUN):
    maintenant = datetime.now(timezone.utc) - timedelta(minutes=5)
    iso = maintenant.isoformat(timespec="seconds")
    (dossier / "verrou.json").write_text(json.dumps({
        "etat": "pris", "poste": poste_, "utilisateur": "compte-fictif", "run": run,
        "depuis": iso, "activite": iso, "commande": "prepare"}), encoding="utf-8")


def test_verrou_tenu_par_un_autre_poste(depot, donnees, monkeypatch):
    monkeypatch.setattr(socket, "gethostname", lambda: "PC-A")
    _verrou(donnees, "PC-B")
    avec_run = verifier(str(depot), str(donnees), run=RUN)
    assert _niveaux(avec_run, "verrou") == [BLOQUANT]
    detail = [r.detail for r in avec_run if r.libelle == "verrou"][0]
    assert "PC-B" in detail and "compte-fictif" not in detail
    # sans --run : l'état seulement, signalé, jamais bloquant
    assert _niveaux(verifier(str(depot), str(donnees)), "verrou") == [AVERTISSEMENT]


def test_verrou_tenu_par_ce_poste_pour_ce_run(depot, donnees, monkeypatch):
    monkeypatch.setattr(socket, "gethostname", lambda: "PC-A")
    _verrou(donnees, "PC-A")
    assert _niveaux(verifier(str(depot), str(donnees), run=RUN), "verrou") == [OK]
    assert _niveaux(verifier(str(depot), str(donnees), run="02-01-2030"), "verrou") == [BLOQUANT]


# --- confidentialité -----------------------------------------------------------------------------

def test_jamais_le_nom_du_profil_dans_la_sortie(depot, donnees, capsys):
    code, sortie = _sortie(capsys, depot, donnees)
    assert code == 0 and "profil chargé" in sortie
    assert "Dupont" not in sortie and "example.com" not in sortie
    # config invalide : une erreur YAML peut citer le contenu fautif (ici une étiquette) ; la
    # sortie n'en donne que le numéro de ligne
    (donnees / "config.yaml").write_text(
        "version: 1\nprofil: {nom: !Dupont \"Marie\"}\nscoring: {}\nsearch_plan: {}\n",
        encoding="utf-8")
    code, sortie = _sortie(capsys, depot, donnees)
    assert code == 2 and "YAML invalide (ligne 2)" in sortie
    assert "Dupont" not in sortie


def test_jamais_le_nom_du_fichier_de_config_quand_il_peut_nommer_le_profil(depot, capsys):
    """Mode local : `charger()` retient le second nom de `config.CHEMINS_PAR_DEFAUT` quand
    data/config.yaml manque. Ce nom porte un prénom : la sortie ne le cite pas."""
    second = os.path.basename(CHEMINS_PAR_DEFAUT[1])
    marque = os.path.splitext(second)[0].split("-", 1)[1]  # ce qui suit « config- »
    (depot / "data" / second).write_text(CONFIG, encoding="utf-8")
    code, sortie = _sortie(capsys, depot)
    assert code == 0 and "profil chargé" in sortie
    assert second not in sortie
    assert marque.lower() not in sortie.lower()


def test_l_option_config_est_bloquante_en_mode_partage(depot, donnees, tmp_path):
    """Comme prepare, lots et finaliser : en partagé, la config est celle du dossier de données."""
    autre = tmp_path / "autre.yaml"
    autre.write_text(CONFIG, encoding="utf-8")
    res = verifier(str(depot), str(donnees), config=str(autre))
    bloquants = [r for r in res if r.niveau == BLOQUANT]
    assert [r.libelle for r in bloquants] == ["config"]
    assert "--config" in bloquants[0].detail
    assert _niveaux(verifier(str(depot), str(donnees)), "config") == [OK]


def test_le_run_vise_deja_finalise_ou_prepare_ailleurs_bloque(depot, donnees, monkeypatch):
    """`poste --run R` dit, avant `lots`, ce que `lots` et `prepare` refuseraient."""
    monkeypatch.setattr(socket, "gethostname", lambda: "PC-A")
    autre = "02-01-2030"
    assert _niveaux(verifier(str(depot), str(donnees), run=RUN), "run") == [BLOQUANT]  # DELTA présent
    assert _niveaux(verifier(str(depot), str(donnees), run=autre), "run") == [OK]
    (donnees / "runs" / autre).mkdir()
    (donnees / "runs" / autre / "proprietaire.json").write_text(
        json.dumps({"poste": "PC-B", "depuis": "2030-01-02T08:00:00+00:00"}), encoding="utf-8")
    res = verifier(str(depot), str(donnees), run=autre)
    assert _niveaux(res, "run") == [BLOQUANT]
    assert any(r.libelle == "run" and "PC-B" in r.detail for r in res)
    monkeypatch.setattr(socket, "gethostname", lambda: "PC-B")
    assert _niveaux(verifier(str(depot), str(donnees), run=autre), "run") == [OK]
    assert _niveaux(verifier(str(depot), str(donnees), run="2030-01-02"), "run") == [BLOQUANT]
    # sans --run, ni en mode local : pas de contrôle du run
    assert _niveaux(verifier(str(depot), str(donnees)), "run") == []


# --- code (git) ----------------------------------------------------------------------------------

def _git_env(tmp_path):
    """Environnement d'un dépôt git jetable, isolé de la configuration de la machine."""
    vide = tmp_path / "gitconfig-vide"
    vide.write_text("", encoding="utf-8")
    env = dict(os.environ)
    env.update({"GIT_CONFIG_GLOBAL": str(vide), "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.invalid",
                "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.invalid"})
    return env


@pytest.mark.skipif(shutil.which("git") is None, reason="git absent")
def test_aucun_bloquant_git_en_ci_a_head_detache(tmp_path, capsys):
    ci = tmp_path / "ci"
    ci.mkdir()
    env = _git_env(tmp_path)
    for cmd in (["init", "-q"], ["commit", "-q", "--allow-empty", "-m", "init"],
                ["checkout", "-q", "--detach"]):
        subprocess.run(["git", "-C", str(ci), *cmd], check=True, capture_output=True, env=env)
    (ci / "data").mkdir()
    (ci / "data" / "config.yaml").write_text(CONFIG, encoding="utf-8")
    res = verifier(str(ci))
    git = [r for r in res if r.libelle in ("code", "dernier fetch", "amont")]
    assert [r.niveau for r in git] == [OK, OK, OK]
    assert "HEAD détaché" in git[0].detail and "aucun" in git[2].detail
    assert cmd_poste(argparse.Namespace(racine=str(ci), donnees=None, run=None, config=None)) == 0


def test_sans_git_simple_information(depot, donnees, monkeypatch):
    def absent(*a, **kw):
        raise FileNotFoundError("git")

    monkeypatch.setattr(poste.subprocess, "run", absent)
    res = verifier(str(depot), str(donnees))
    assert [r for r in res if r.niveau == BLOQUANT] == []
    assert [(r.niveau, r.detail.startswith("git introuvable")) for r in res if r.libelle == "code"] == [
        (OK, True)]


def test_branche_fetch_ancien_et_retard_avertissent_sans_bloquer(depot, donnees, tmp_path, monkeypatch):
    commun = tmp_path / "commun"
    commun.mkdir()
    (commun / "FETCH_HEAD").write_text("", encoding="utf-8")
    vieux = time.time() - 3 * 24 * 3600
    os.utime(commun / "FETCH_HEAD", (vieux, vieux))
    reponses = {
        ("--version",): "git version 2.0", ("rev-parse", "--is-inside-work-tree"): "true",
        ("rev-parse", "--short", "HEAD"): "abc1234", ("rev-parse", "--abbrev-ref", "HEAD"): "feat/x",
        ("rev-parse", "--git-common-dir"): str(commun),
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"): "origin/feat/x",
        ("rev-list", "--count", "HEAD..@{u}"): "3",
    }
    monkeypatch.setattr(poste, "_git", lambda racine, *args: reponses.get(args))
    res = verifier(str(depot), str(donnees))
    assert [r for r in res if r.niveau == BLOQUANT] == []
    git = {r.libelle: r for r in res if r.libelle in ("code", "dernier fetch", "amont")}
    assert {k: r.niveau for k, r in git.items()} == {
        "code": AVERTISSEMENT, "dernier fetch": AVERTISSEMENT, "amont": AVERTISSEMENT}
    assert "git pull --ff-only" in git["dernier fetch"].detail and "il y a 3 j" in git["dernier fetch"].detail
    assert "3 commit(s) de retard sur origin/feat/x" in git["amont"].detail


# --- outils --------------------------------------------------------------------------------------

@pytest.mark.parametrize("nom,attendu", [
    ("verrou (1).json", True), ("config (2).yaml", True), (f"DELTA_{RUN} (1).csv", True),
    ("historique (1)", True), (f"DELTA_{RUN}.csv", False), ("~$prospection (1).xlsx", False),
    ("notes (brouillon).txt", False), ("verrou (1).json.tmp", False),
])
def test_copie_en_conflit(nom, attendu):
    assert copie_en_conflit(nom) is attendu


def test_cle_classeur_trie_par_date():
    noms = ["prospection_31-12-2029.xlsx", "prospection_01-01-2030-2.xlsx", "prospection_01-01-2030.xlsx"]
    assert sorted(noms, key=cle_classeur) == [
        "prospection_31-12-2029.xlsx", "prospection_01-01-2030.xlsx", "prospection_01-01-2030-2.xlsx"]
    for nom in ("prospection_31-02-2030.xlsx", "prospection_01-01-2030-1.xlsx", "MASTER.xlsx",
                "~$prospection_01-01-2030.xlsx"):
        assert cle_classeur(nom) is None
