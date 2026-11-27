"""Tests de `prospection.migration` : `initialiser-donnees` (création et migration du dossier partagé).

Tout se passe dans `tmp_path` : un faux dépôt (avec un `.git` factice) qui porte un `data/` et un
`runs/` fictifs, et un faux « Drive » à côté. Jamais le vrai `data/`, jamais un vrai Drive.
Les fonctions sont appelées directement ; le câblage de la sous-commande vit dans `run.py`.
"""
import argparse
import csv
import json
import os
import shutil
import subprocess
import sys

import openpyxl
import pytest

from prospection import migration
from prospection.cles import norm
from prospection.config import CHEMINS_PAR_DEFAUT
from prospection.dedup import Historique, dedupliquer
from prospection.emplacements import (
    MARQUEUR, MARQUEUR_MIGRATION, DonneesMigrees, DossierDonneesDansLeDepot, resoudre,
)
from prospection.migration import (
    NOM_GABARIT, InitialisationImpossible, cmd_initialiser, commande_powershell, initialiser,
)
from prospection.poste import NON_BRUTS
from prospection.workbook import COLS, COLS_LEADS

CONFIG = "version: 1\nprofil: {nom: \"Personne Fictive\"}\nscoring: {seuil_conservation: 3, " \
         "seuil_redaction: 5}\nsearch_plan: {lots: {A: [\"formateur data\"]}}\n"
GABARIT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates",
                       NOM_GABARIT)
R1, R2 = "01-01-2030", "08-01-2030"
TEXTE = ("Ecole Alpha\nRecrutement\n3 j • \nNous cherchons un formateur data pour la rentree, "
         "en presentiel a Lille, deux jours par semaine.")


def _csv(chemin, cols, lignes, encoding="utf-8"):
    with open(chemin, "w", newline="", encoding=encoding) as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for ligne in lignes:
            w.writerow([ligne.get(c, "") for c in cols])


def _ligne(auteur, **kw):
    p = {"auteur": auteur, "post_extrait": f"Annonce fictive de {auteur}",
         "url_post": f"https://lnkd.in/p/{norm(auteur)}1", "cle_contenu": f"cle-{norm(auteur)}",
         "score_pertinence": "4"}
    p.update(kw)
    return p


def _classeur(chemin):
    wb = openpyxl.Workbook()
    wb.active.title = "MASTER"
    wb.save(chemin)


@pytest.fixture()
def depot(tmp_path):
    """Faux dépôt : `.git` factice, data/ (config, MASTER, DELTA, SUIVI_LEADS, classeurs), runs/."""
    d = tmp_path / "depot"
    (d / ".git").mkdir(parents=True)
    data = d / "data"
    data.mkdir()
    (data / "config.yaml").write_text(CONFIG, encoding="utf-8")
    _csv(data / "MASTER.csv", COLS, [_ligne("Ecole Alpha")])
    _csv(data / f"DELTA_{R2}.csv", COLS, [_ligne("Ecole Beta")])
    _csv(data / "SUIVI_LEADS.csv", COLS_LEADS, [{"organisation": "Ecole Beta"}])
    (data / "~$MASTER.csv").write_text("verrou d'Excel", encoding="utf-8")
    for nom in ("prospection_31-12-2029.xlsx", f"prospection_{R1}.xlsx", "prospection_15-06-2029.xlsx"):
        _classeur(data / nom)
    for run, fichiers in ((R1, ("agent_A.json", "a_scorer.json")), (R2, ("agent_B.json",))):
        (d / "runs" / run).mkdir(parents=True)
        for f in fichiers:
            (d / "runs" / run / f).write_text(json.dumps({"candidats": []}), encoding="utf-8")
    return d


def _init(depot, vers, **kw):
    kw.setdefault("depuis", str(depot / "data"))
    kw.setdefault("runs", str(depot / "runs"))
    return initialiser(str(vers), racine=str(depot), **kw)


def _args(depot, vers, **kw):
    a = {"vers": str(vers), "depuis": str(depot / "data"), "runs": str(depot / "runs"),
         "classeur": None, "gabarit": False, "racine": str(depot)}
    a.update(kw)
    return argparse.Namespace(**a)


def _arbre(racine):
    """Tous les chemins sous `racine`, relatifs, pour comparer un avant et un après."""
    out = set()
    for dossier, sous, fichiers in os.walk(racine):
        for n in sous + fichiers:
            out.add(os.path.relpath(os.path.join(dossier, n), racine))
    return out


# --- arborescence et contenu ---------------------------------------------------------------------

def test_arborescence_creee(depot, tmp_path):
    vers = tmp_path / "drive" / "donnees"  # le parent n'existe pas encore
    rec = _init(depot, vers)
    for sous in ("historique", "runs", "classeurs"):
        assert (vers / sous).is_dir()
    assert (vers / "LISEZMOI.md").is_file()
    assert json.loads((vers / MARQUEUR).read_text(encoding="utf-8")) == {"version": 1}
    assert rec.vers == str(vers)
    # le dossier créé est un dossier de données valide : le mode partagé s'y résout
    assert resoudre(str(depot), str(vers)).mode == "partage"


def test_la_config_du_profil_et_non_le_gabarit(depot, tmp_path):
    vers = tmp_path / "donnees"
    rec = _init(depot, vers, gabarit=True)  # même avec --gabarit, la config du profil prime
    assert (vers / "config.yaml").read_text(encoding="utf-8") == CONFIG
    assert rec.config == "copiée" and rec.config_source == "data/config.yaml"
    assert not any("GABARIT" in ligne for ligne in rec.journal)
    assert any("gabarit non utilisé" in ligne for ligne in rec.journal)


def test_config_sous_le_second_nom_par_defaut(depot, tmp_path):
    # mêmes noms que config.CHEMINS_PAR_DEFAUT, copiés sous le nom config.yaml
    second = os.path.basename(CHEMINS_PAR_DEFAUT[1])
    os.replace(depot / "data" / "config.yaml", depot / "data" / second)
    rec = _init(depot, tmp_path / "donnees")
    assert (tmp_path / "donnees" / "config.yaml").read_text(encoding="utf-8") == CONFIG
    assert rec.config_source == f"data/{second}"


def test_gabarit_seulement_avec_l_option_et_annonce(depot, tmp_path, capsys):
    (depot / "data" / "config.yaml").unlink()
    sans = tmp_path / "sans_gabarit"
    rec = _init(depot, sans)  # des CSV à migrer : pas d'erreur, mais pas de config inventée
    assert not (sans / "config.yaml").exists()
    assert rec.config == "absente"

    avec = tmp_path / "avec_gabarit"
    assert cmd_initialiser(_args(depot, avec, gabarit=True)) == 0
    sortie = capsys.readouterr().out
    assert "GABARIT copié : à remplir avant tout run" in sortie
    with open(GABARIT, encoding="utf-8") as fh:
        assert (avec / "config.yaml").read_text(encoding="utf-8") == fh.read()


def test_seuls_les_csv_d_historique_sont_migres(depot, tmp_path):
    # un DELTA réenregistré par Excel : BOM, et `auteur` en première colonne
    cols = ["auteur"] + [c for c in COLS if c != "auteur"]
    _csv(depot / "data" / f"DELTA_{R1}.csv", cols, [_ligne("Ecole Gamma")], encoding="utf-8-sig")
    vers = tmp_path / "donnees"
    rec = _init(depot, vers)
    # SUIVI_LEADS (pas de colonne auteur) et le verrou d'Excel restent où ils sont
    assert not (vers / "historique" / "SUIVI_LEADS.csv").exists()
    assert not (vers / "historique" / "~$MASTER.csv").exists()
    assert sorted(rec.csv_ignores) == ["SUIVI_LEADS.csv", "~$MASTER.csv"]
    attendus = sorted(["MASTER.csv", f"DELTA_{R1}.csv", f"DELTA_{R2}.csv"])
    assert sorted(os.listdir(vers / "historique")) == attendus
    assert sorted(rec.csv) == attendus


def test_les_runs_sont_copies_avec_leur_structure(depot, tmp_path):
    vers = tmp_path / "donnees"
    rec = _init(depot, vers)
    assert sorted(os.listdir(vers / "runs" / R1)) == ["a_scorer.json", "agent_A.json"]
    assert os.listdir(vers / "runs" / R2) == ["agent_B.json"]
    assert (rec.json, rec.runs) == (3, [R1, R2])
    assert (vers / "runs" / R1 / "agent_A.json").read_bytes() == \
        (depot / "runs" / R1 / "agent_A.json").read_bytes()


def test_classeur_zero_le_plus_recent_par_date_et_non_par_ordre_lexical(depot, tmp_path):
    # « 31-12-2029 » vient après « 01-01-2030 » dans l'ordre lexical, avant dans le temps
    vers = tmp_path / "donnees"
    rec = _init(depot, vers)
    assert rec.classeur == f"prospection_{R1}.xlsx"
    assert os.listdir(vers / "classeurs") == [f"prospection_{R1}.xlsx"]


def test_classeur_zero_designe(depot, tmp_path):
    vers = tmp_path / "donnees"
    rec = _init(depot, vers, classeur=str(depot / "data" / "prospection_15-06-2029.xlsx"))
    assert rec.classeur == "prospection_15-06-2029.xlsx"
    assert os.listdir(vers / "classeurs") == ["prospection_15-06-2029.xlsx"]
    with pytest.raises(InitialisationImpossible, match="classeur introuvable"):
        _init(depot, tmp_path / "autre", classeur=str(depot / "data" / "absent.xlsx"))


def test_marqueur_de_migration_depose_dans_la_source(depot, tmp_path):
    vers = tmp_path / "donnees"
    rec = _init(depot, vers)
    migre = depot / "data" / MARQUEUR_MIGRATION
    texte = migre.read_text(encoding="utf-8")
    assert str(vers) in texte and "Date : 20" in texte
    assert rec.migration == str(migre)
    # le data/ local est désormais refusé en mode local : plus de lecture d'un data/ périmé
    with pytest.raises(DonneesMigrees):
        resoudre(str(depot))


def test_relance_sans_rien_ecraser(depot, tmp_path, capsys):
    vers = tmp_path / "donnees"
    _init(depot, vers)
    (vers / "config.yaml").write_text("modifiée sur le Drive\n", encoding="utf-8")
    delta = vers / "historique" / f"DELTA_{R2}.csv"
    delta_avant = delta.read_bytes()
    (depot / "data" / f"DELTA_{R2}.csv").write_text("auteur\nEcole Modifiee\n", encoding="utf-8")
    arbre_avant = _arbre(vers)

    assert cmd_initialiser(_args(depot, vers)) == 0
    sortie = capsys.readouterr().out
    assert (vers / "config.yaml").read_text(encoding="utf-8") == "modifiée sur le Drive\n"
    assert delta.read_bytes() == delta_avant
    assert _arbre(vers) == arbre_avant  # rien de plus : ni copie, ni temporaire oublié
    assert "déjà présent (contenu différent, non remplacé) : config.yaml" in sortie
    assert f"déjà présent (contenu différent, non remplacé) : historique/DELTA_{R2}.csv" in sortie
    rec = _init(depot, vers)
    assert (rec.config, rec.csv, rec.json) == ("déjà présente", [], 0)
    assert MARQUEUR in rec.deja_presents and "LISEZMOI.md" in rec.deja_presents


# --- refus -------------------------------------------------------------------------------------

def test_vers_dans_le_depot_refuse_sans_rien_creer(depot, capsys):
    avant = _arbre(depot)
    vers = depot / "sous" / "donnees"
    assert cmd_initialiser(_args(depot, vers)) == 2
    assert "dans le dépôt" in capsys.readouterr().err
    assert not (depot / "sous").exists()
    assert _arbre(depot) == avant  # pas même le marqueur de migration dans data/
    with pytest.raises(DossierDonneesDansLeDepot):
        _init(depot, depot / "data" / "partage")


def test_vers_dans_un_autre_arbre_git_refuse(depot, tmp_path):
    autre = tmp_path / "autre_projet"
    (autre / ".git").mkdir(parents=True)
    with pytest.raises(DossierDonneesDansLeDepot, match="arbre de travail git"):
        _init(depot, autre / "donnees")
    assert not (autre / "donnees").exists()


def test_vers_sous_un_fichier_refuse(depot, tmp_path, capsys):
    fichier = tmp_path / "pas_un_dossier"
    fichier.write_text("x", encoding="utf-8")
    assert cmd_initialiser(_args(depot, fichier / "donnees")) == 2
    assert "n'est pas un dossier" in capsys.readouterr().err
    assert fichier.read_text(encoding="utf-8") == "x"


def test_rien_a_migrer_sans_gabarit_code_2(depot, tmp_path, capsys):
    vide = tmp_path / "data_vide"
    vide.mkdir()
    vers = tmp_path / "donnees"
    assert cmd_initialiser(_args(depot, vers, depuis=str(vide))) == 2
    assert "rien à migrer" in capsys.readouterr().err
    assert not vers.exists()
    # avec --gabarit, on part du gabarit
    assert cmd_initialiser(_args(depot, vers, depuis=str(vide), gabarit=True)) == 0
    assert (vers / "config.yaml").is_file()


def test_csv_illisible_arrete_tout_sans_rien_creer(depot, tmp_path):
    (depot / "data" / "ABIME.csv").write_bytes(b"auteur,url_post\n\xff\xfe\xfa\n")
    vers = tmp_path / "donnees"
    with pytest.raises(InitialisationImpossible, match="ABIME.csv"):
        _init(depot, vers)
    assert not vers.exists()
    assert not (depot / "data" / MARQUEUR_MIGRATION).exists()


# --- variable d'environnement ------------------------------------------------------------------

def test_commande_powershell_apostrophes_doublees():
    assert commande_powershell(r"C:\Drive\l'equipe\donnees") == (
        "[Environment]::SetEnvironmentVariable('PROSPECTION_DONNEES', "
        r"'C:\Drive\l''equipe\donnees', 'User')"
    )


@pytest.mark.parametrize("apostrophe", ["\u2018", "\u2019", "\u201a", "\u201b"])
def test_commande_powershell_double_aussi_les_apostrophes_typographiques(apostrophe):
    """PowerShell (5.1 comme 7) prend ‘ ’ ‚ ‛ pour des délimiteurs de chaîne, comme ' : un dossier
    nommé avec une correction automatique (« l’équipe ») casserait la commande affichée."""
    chemin = f"G:\\Mon Drive\\l{apostrophe}equipe\\donnees"
    assert commande_powershell(chemin) == (
        "[Environment]::SetEnvironmentVariable('PROSPECTION_DONNEES', "
        f"'G:\\Mon Drive\\l{apostrophe * 2}equipe\\donnees', 'User')"
    )


def _powershell():
    for nom in ("pwsh", "powershell"):
        if shutil.which(nom):
            return shutil.which(nom)
    return None


@pytest.mark.skipif(_powershell() is None, reason="PowerShell absent")
def test_la_commande_affichee_s_analyse_sans_erreur_dans_powershell(tmp_path):
    """Analyse seule (Parser::ParseFile), rien n'est exécuté : la commande, avec ' et ’ dans le
    chemin, ne produit aucune erreur et le littéral garde le chemin entier.

    Le résultat passe par un fichier JSON, pas par la console : sous Linux, `pwsh` alimenté par
    l'entrée standard glisse des séquences de terminal (`ESC[?1h ESC[?1l`) dans sa sortie, ce
    qui faisait échouer la version précédente de ce test en CI alors que l'analyse était bonne.
    """
    chemin = "G:\\Mon Drive\\l\u2019equipe d'Alpha\\donnees"
    script = tmp_path / "commande.ps1"
    script.write_text(commande_powershell(chemin), encoding="utf-8-sig")
    sortie = tmp_path / "analyse.json"
    # le code d'analyse passe par l'entrée standard (`-Command -`) : aucun script n'est lancé, et
    # la commande à analyser n'est que lue (ParseFile), jamais exécutée. Les littéraux sont écrits
    # en codes de caractères : ni la console ni l'encodage du fichier n'abîment ’ ou les accents.
    analyse = "\n".join([
        "$e = $null; $t = $null",
        f"$ast = [System.Management.Automation.Language.Parser]::ParseFile('{script}', [ref]$t, [ref]$e)",
        "$s = $ast.FindAll({ param($n) $n -is "
        "[System.Management.Automation.Language.StringConstantExpressionAst] }, $true)",
        "$v = @(foreach ($x in $s) { ([int[]][char[]]$x.Value) -join ',' })",
        "$r = @{ erreurs = $e.Count; valeurs = $v } | ConvertTo-Json -Depth 3",
        f"[System.IO.File]::WriteAllText('{sortie}', $r)",
        "",
    ])
    p = subprocess.run([_powershell(), "-NoProfile", "-NonInteractive", "-Command", "-"],
                       input=analyse, capture_output=True, text=True, timeout=120)
    assert sortie.exists(), p.stdout + p.stderr
    r = json.loads(sortie.read_text(encoding="utf-8-sig"))
    assert r["erreurs"] == 0
    valeurs = ["".join(chr(int(c)) for c in v.split(",")) for v in r["valeurs"]]
    assert chemin in valeurs


class _Interdit:
    """Remplace tout ce qui pourrait poser une variable « User » : chaque appel est enregistré."""

    def __init__(self, nom, appels):
        self.nom, self.appels = nom, appels

    def __call__(self, *a, **kw):
        self.appels.append((self.nom, a))
        raise AssertionError(f"{self.nom} appelé par initialiser-donnees")


class _FauxRegistre:
    """`winreg` factice : toute écriture est enregistrée, toute lecture échoue (clé absente)."""
    HKEY_CURRENT_USER, REG_SZ, REG_EXPAND_SZ, KEY_SET_VALUE, KEY_ALL_ACCESS = "HKCU", 1, 2, 2, 0xF003F
    FAUX = True

    def __init__(self, appels):
        for nom in ("SetValueEx", "SetValue", "CreateKey", "CreateKeyEx", "DeleteValue",
                    "DeleteKey", "OpenKey", "OpenKeyEx"):
            setattr(self, nom, _Interdit(f"winreg.{nom}", appels))


def test_la_commande_affiche_la_variable_sans_la_poser(depot, tmp_path, capsys, monkeypatch):
    """Poser une variable « User » (setx, registre, [Environment]::SetEnvironmentVariable) ne
    change jamais `os.environ` du processus : comparer `os.environ` ne garde rien. Tout chemin
    d'écriture est donc intercepté, et aucun ne doit servir."""
    appels = []
    import subprocess as sp
    for nom in ("run", "Popen", "call", "check_call", "check_output"):
        monkeypatch.setattr(sp, nom, _Interdit(f"subprocess.{nom}", appels))
    monkeypatch.setattr(os, "system", _Interdit("os.system", appels))
    if hasattr(os, "startfile"):
        monkeypatch.setattr(os, "startfile", _Interdit("os.startfile", appels))
    monkeypatch.setitem(sys.modules, "winreg", _FauxRegistre(appels))
    vers = tmp_path / "l'equipe" / "donnees"
    env_avant = dict(os.environ)
    assert cmd_initialiser(_args(depot, vers)) == 0
    sortie = capsys.readouterr().out
    assert sortie.startswith(f"cible : {vers}")
    assert str(vers).replace("'", "''") in sortie
    assert commande_powershell(str(vers)) in sortie
    assert "redémarrer Claude, les terminaux et GitKraken" in sortie
    assert "config copiée depuis data/config.yaml · 2 CSV d'historique · 3 JSON dans 2 run(s)" \
           f" · classeur zéro : prospection_{R1}.xlsx" in sortie
    assert appels == []
    assert dict(os.environ) == env_avant


def test_un_lecteur_non_monte_est_annonce_comme_tel(depot, tmp_path, capsys, monkeypatch):
    """Google Drive pour ordinateur arrêté : la racine du lecteur n'existe pas. Le message le dit,
    au lieu de prétendre qu'elle « existe et n'est pas un dossier »."""
    racine_absente = str(tmp_path / "Z_lecteur_absent")  # tient lieu de « Z:\ »
    monkeypatch.setattr(migration, "_ancetre_existant", lambda chemin: racine_absente)
    vers = os.path.join(racine_absente, "Mon Drive", "donnees")
    assert cmd_initialiser(_args(depot, vers)) == 2
    err = capsys.readouterr().err
    assert "n'est pas un dossier" not in err
    assert f"{racine_absente} introuvable" in err and "lecteur non monté" in err
    assert not os.path.exists(racine_absente)
    assert not (depot / "data" / MARQUEUR_MIGRATION).exists()


def _lecteur_libre():
    import string
    for lettre in reversed(string.ascii_uppercase[3:]):
        if not os.path.exists(f"{lettre}:\\"):
            return f"{lettre}:\\"
    return None


@pytest.mark.skipif(sys.platform != "win32", reason="lettres de lecteur : Windows seulement")
def test_un_vrai_lecteur_absent_sous_windows(depot, capsys):
    lecteur = _lecteur_libre()
    if lecteur is None:
        pytest.skip("aucune lettre de lecteur libre")
    assert cmd_initialiser(_args(depot, lecteur + r"Mon Drive\prospection\donnees")) == 2
    err = capsys.readouterr().err
    assert "n'est pas un dossier" not in err
    assert "lecteur non monté" in err


# --- migration et déduplication ----------------------------------------------------------------

def _historique_partage(vers, run_courant):
    """Sources de l'historique en mode partagé : historique/*.csv reconnus et JSON bruts des runs."""
    h = Historique()
    for f in sorted((vers / "historique").glob("*.csv")):
        h.ajouter_csv(str(f), stricte=True)
    for d in sorted((vers / "runs").iterdir()):
        if d.name == run_courant:
            continue
        for f in sorted(d.glob("*.json")):
            if not f.name.startswith(NON_BRUTS):
                h.ajouter_run(str(f))
    return h


def test_un_post_connu_par_un_json_brut_reste_connu_apres_migration(depot, tmp_path):
    # le post n'est connu que par le JSON brut d'un ancien run : son DELTA porte une clé périmée
    # (calculée avant le correctif #3) et un lien lnkd.in différent
    brut = {"candidats": [{"auteur": "Ecole Alpha", "texte": TEXTE, "url_post": "https://lnkd.in/p/AAA",
                           "date_rel": "3 j"}]}
    (depot / "runs" / R1 / "agent_A.json").write_text(json.dumps(brut), encoding="utf-8")
    _csv(depot / "data" / f"DELTA_{R1}.csv", COLS,
         [_ligne("Ecole Alpha", cle_contenu="cle-perimee", url_post="https://lnkd.in/p/BBB")])
    revu = {"auteur": "Ecole Alpha", "texte": TEXTE, "url_post": "https://lnkd.in/p/CCC",
            "date_rel": "1 sem"}
    run_courant = "15-01-2030"

    vers = tmp_path / "donnees"
    _init(depot, vers)
    _, rap = dedupliquer([dict(revu)], _historique_partage(vers, run_courant))
    assert (rap.deja_connus, rap.nouveaux) == (1, 0)

    # garde : sans la copie des runs, le post revient comme nouveau
    sans_runs = tmp_path / "donnees_sans_runs"
    _init(depot, sans_runs, runs=str(tmp_path / "pas_de_runs"))
    _, rap = dedupliquer([dict(revu)], _historique_partage(sans_runs, run_courant))
    assert (rap.deja_connus, rap.nouveaux) == (0, 1)


def test_les_fichiers_non_migres_de_la_source_sont_signales(depot, tmp_path, capsys):
    """Le marqueur de migration coupe le mode local : ce qui reste dans data/ est nommé."""
    (depot / "data" / "notes-profil.md").write_text("notes fictives", encoding="utf-8")
    (depot / "data" / "auteurs.txt").write_text("Ecole Alpha", encoding="utf-8")
    (depot / "data" / "README.md").write_text("doc du dépôt", encoding="utf-8")
    (depot / "data" / ".gitkeep").write_text("", encoding="utf-8")
    vers = tmp_path / "donnees"
    assert cmd_initialiser(_args(depot, vers)) == 0
    out = capsys.readouterr().out
    restes = sorted(l.split(" : ", 1)[1] for l in out.splitlines() if "non migré" in l)
    # les notes, la liste d'auteurs et les classeurs plus anciens que le classeur zéro ; jamais
    # la doc du dépôt, la config, les CSV déjà signalés ni le marqueur de migration
    assert restes == sorted(["auteurs.txt", "notes-profil.md", "prospection_15-06-2029.xlsx",
                             "prospection_31-12-2029.xlsx"])
