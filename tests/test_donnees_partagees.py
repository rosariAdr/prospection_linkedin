"""Mode partagé, scénario sur plusieurs PC : `prepare`, `finaliser`, `lots` et `verrou` sur un
dossier de données commun (spec feat/donnees-drive, §3 à §6 et §8).

Tout se passe dans `tmp_path`, avec des données fictives :
- un faux dépôt `depot/` (un `.git` factice, son `data/` local avec une config DIFFÉRENTE, pour
  prouver que le mode partagé lit celle du dossier de données) ;
- un dossier de données `drive/donnees/` initialisé à la main : marqueur, config, `historique/`,
  `runs/`, `classeurs/`.
Les « postes » sont simulés par un monkeypatch de `socket.gethostname`. La fixture de
`tests/conftest.py` retire `PROSPECTION_DONNEES` : chaque test passe `--donnees` ou pose la
variable lui-même.
"""
import csv
import getpass
import json
import os
import socket
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pytest

from prospection import poste, verrou
from prospection import run as run_mod
from prospection.cles import cle_contenu
from prospection.emplacements import MARQUEUR, MARQUEUR_MIGRATION
from prospection.run import main
from prospection.workbook import COLS, COLS_LEADS, construire

R0, R1, R2, R3 = "25-12-2029", "01-01-2030", "08-01-2030", "15-01-2030"
COLS_SANS_CLE = [c for c in COLS if c != "cle_contenu"]  # DELTA d'avant la colonne cle_contenu
CONFIG = textwrap.dedent(
    """
    version: 1
    profil: {nom: "Personne Fictive"}
    blacklist:
      organisations: ["Ecole Interdite"]
      en_observation: ["Ecole Surveillee"]
    scoring: {seuil_conservation: 3, seuil_redaction: 5}
    search_plan:
      lots:
        A: ["formateur data", "intervenant data"]
        B: ["formateur python"]
    """
)
# config du data/ local : autre blacklist, autres mots-clés. Le mode partagé ne la lit jamais.
CONFIG_LOCALE = CONFIG.replace("Ecole Interdite", "Ecole Locale Seulement").replace(
    "formateur python", "mot-cle local")
TEXTES = ("reponse_commentaire_linkedin", "note_invitation_200", "note_invitation_300",
          "message_linkedin", "reponse_mail")


# --- environnement ----------------------------------------------------------------------------

@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Faux dépôt + dossier de données partagé initialisé. Le test s'exécute dans le dépôt."""
    depot = tmp_path / "depot"
    (depot / ".git").mkdir(parents=True)
    (depot / "data").mkdir()
    (depot / "runs").mkdir()
    (depot / "data" / "config.yaml").write_text(CONFIG_LOCALE, encoding="utf-8")
    donnees = tmp_path / "drive" / "donnees"
    for s in ("historique", "runs", "classeurs"):
        (donnees / s).mkdir(parents=True)
    (donnees / MARQUEUR).write_text(json.dumps({"version": 1}), encoding="utf-8")
    (donnees / "config.yaml").write_text(CONFIG, encoding="utf-8")
    monkeypatch.setattr(getpass, "getuser", lambda: "compte-fictif")

    def poste(nom):
        monkeypatch.setattr(socket, "gethostname", lambda: nom)

    poste("PC-A")
    monkeypatch.chdir(depot)
    return SimpleNamespace(tmp=tmp_path, depot=depot, donnees=donnees, poste=poste)


def _cmd(env, *args):
    return main(["--donnees", str(env.donnees), *args])


def _arbre(racine):
    """Instantané d'une arborescence : chemins (dossiers compris), tailles et dates."""
    out = {}
    for p in racine.rglob("*"):
        st = p.stat()
        out[str(p.relative_to(racine))] = None if p.is_dir() else (st.st_size, st.st_mtime_ns)
    return out


def _slug(auteur):
    return auteur.lower().replace(" ", "-")


def _texte(auteur):
    return f"{auteur} recherche un formateur data pour son campus, annonce fictive."


def _candidat(auteur, url=None):
    return {"mot_cle": "formateur data", "auteur": auteur, "profil": "",
            "url_post": url or f"https://www.linkedin.com/posts/{_slug(auteur)}_activity-0000000000000000002/",
            "date_rel": "3 j", "texte": _texte(auteur)}


def _lot(env, run, candidats, nom="A"):
    d = env.donnees / "runs" / run
    d.mkdir(parents=True, exist_ok=True)
    lot = {"batch": nom, "date_run": "2030-01-01", "filtre": "past-week",
           "mots_cles_traites": ["formateur data", "intervenant data", "formateur python"],
           "mots_cles_non_traites": [], "nb_candidats": len(candidats), "candidats": candidats,
           "rejetes": []}
    (d / f"{nom}.json").write_text(json.dumps(lot, ensure_ascii=False), encoding="utf-8")


def _post(auteur, score=10, **kw):
    """Une ligne scorée fictive, conforme aux garde-fous."""
    p = {
        "post_extrait": f"Annonce fictive de {auteur}",
        "url_post": f"https://www.linkedin.com/posts/{_slug(auteur)}_activity-0000000000000000001/",
        "url_profil_auteur": f"https://www.linkedin.com/in/{_slug(auteur)}/",
        "auteur": auteur, "date": "3 j", "mail": "", "taux_horaire": "à déterminer",
        "localisation": "IDF", "score_pertinence": score, "mot_cle_recherche": "formateur data",
        "batch": "A", "type_opportunite": "annonce directe", "echeance": "S1 2030",
        "deal_breaker": "", "commentaire_scoring": "+4 intention +3 metier +3 zone",
        "cle_contenu": f"cle-{_slug(auteur)}",
        "reponse_commentaire_linkedin": "Votre annonce m'interesse.",
        "note_invitation_200": "Bonjour, formateur data, votre annonce m'interesse.",
        "note_invitation_300": "Bonjour, ingenieur data et formateur, votre annonce m'interesse.",
        "message_linkedin": "Bonjour,\nVotre annonce m'interesse.\nPersonne Fictive",
        "reponse_mail": "",
    }
    if score <= 5:  # sous le seuil de rédaction : aucun texte
        p.update({c: "" for c in TEXTES})
    p.update(kw)
    return p


def _scored(env, run, posts, nom="A"):
    d = env.donnees / "runs" / run
    d.mkdir(parents=True, exist_ok=True)
    (d / f"scored_{nom}.json").write_text(json.dumps({"posts": posts}, ensure_ascii=False),
                                          encoding="utf-8")


def _ecrire_csv(chemin, cols, lignes, encoding="utf-8"):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with open(chemin, "w", newline="", encoding=encoding) as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for ligne in lignes:
            w.writerow([ligne.get(c, "") for c in cols])
    return chemin


def _lignes_csv(chemin):
    with open(chemin, encoding="utf-8", newline="") as fh:
        return list(csv.reader(fh))


def _classeur(env, run):
    return env.donnees / "classeurs" / f"prospection_{run}.xlsx"


def _onglet(chemin, nom="MASTER"):
    ws = openpyxl.load_workbook(chemin)[nom]
    cols = [c.value for c in ws[1]]
    return [dict(zip(cols, r)) for r in ws.iter_rows(min_row=2, values_only=True)]


def _rapport(env, run):
    return json.loads((env.donnees / "runs" / run / "rapport_prepare.json").read_text(encoding="utf-8"))


def _verrou(env):
    return json.loads((env.donnees / "verrou.json").read_text(encoding="utf-8"))


def _tmp_restants(env):
    return sorted(p.name for p in env.donnees.rglob("*.tmp"))


# --- ligne de commande : --donnees, chemins, erreurs d'emplacement ----------------------------

def test_prepare_partage_annonce_le_mode_et_les_chemins_absolus(env, capsys):
    _lot(env, R1, [_candidat("Ecole Alpha")])
    avant = _arbre(env.depot)
    assert _cmd(env, "prepare", "--run", R1) == 0
    out = capsys.readouterr().out
    run = env.donnees / "runs" / R1
    assert out.splitlines()[0] == f"données : partagé — {env.donnees}"
    assert f"dossier du run : {run}" in out
    assert f"config : {env.donnees / 'config.yaml'}" in out
    assert (run / "a_scorer.json").exists()
    assert json.loads((run / "proprietaire.json").read_text(encoding="utf-8"))["poste"] == "PC-A"
    v = _verrou(env)
    assert (v["etat"], v["poste"], v["run"], v["commande"]) == ("pris", "PC-A", R1, "prepare")
    assert _arbre(env.depot) == avant  # rien d'écrit sous le dépôt


def test_la_variable_d_environnement_choisit_aussi_le_mode_partage(env, capsys, monkeypatch):
    monkeypatch.setenv("PROSPECTION_DONNEES", str(env.donnees))
    _lot(env, R1, [_candidat("Ecole Alpha")])
    assert main(["prepare", "--run", R1]) == 0
    assert capsys.readouterr().out.startswith(f"données : partagé — {env.donnees}\n")


def test_donnees_placee_apres_la_sous_commande(env, capsys):
    _lot(env, R1, [_candidat("Ecole Alpha")])
    assert main(["prepare", "--donnees", str(env.donnees), "--run", R1]) == 0
    assert capsys.readouterr().out.startswith(f"données : partagé — {env.donnees}\n")
    assert (env.donnees / "runs" / R1 / "a_scorer.json").exists()
    assert not (env.depot / "runs" / R1).exists()
    assert main(["lots", "--donnees", str(env.donnees)]) == 0
    out = capsys.readouterr().out
    assert "mot-cle local" not in out  # la config du data/ local n'est pas lue
    assert out.startswith("données : partagé") and "formateur python" in out


@pytest.mark.parametrize("place", ["avant", "apres"])
def test_un_chemin_relatif_se_lit_avant_le_chdir_de_racine(env, capsys, monkeypatch, place):
    """`--donnees drive/donnees` se lit depuis le répertoire courant, pas depuis `--racine`."""
    monkeypatch.chdir(env.tmp)
    _lot(env, R1, [_candidat("Ecole Alpha")])
    relatif = os.path.join("drive", "donnees")
    if place == "avant":
        argv = ["--racine", "depot", "--donnees", relatif, "prepare", "--run", R1]
    else:
        argv = ["--racine", "depot", "prepare", "--donnees", relatif, "--run", R1]
    assert main(argv) == 0
    assert capsys.readouterr().out.startswith(f"données : partagé — {env.donnees}\n")
    assert (env.donnees / "runs" / R1 / "a_scorer.json").exists()


def test_les_erreurs_d_emplacement_sortent_en_code_2(env, capsys):
    absent = env.tmp / "absent"
    assert main(["--donnees", str(absent), "prepare", "--run", R1]) == 2
    assert "initialiser-donnees" in capsys.readouterr().err
    vierge = env.tmp / "vierge"
    vierge.mkdir()
    assert main(["--donnees", str(vierge), "finaliser", "--run", R1]) == 2
    assert MARQUEUR in capsys.readouterr().err
    assert main(["--donnees", str(env.depot / "data"), "lots"]) == 2
    assert "dépôt" in capsys.readouterr().err
    (env.depot / "data" / MARQUEUR_MIGRATION).write_text("migré", encoding="utf-8")
    assert main(["lots"]) == 2  # mode local sur un data/ migré
    assert "--donnees" in capsys.readouterr().err


def test_une_config_absente_du_dossier_partage_renvoie_vers_initialiser(env, capsys):
    (env.donnees / "config.yaml").unlink()
    _lot(env, R1, [_candidat("Ecole Alpha")])
    assert _cmd(env, "prepare", "--run", R1) == 2
    err = capsys.readouterr().err
    assert "config introuvable" in err and "initialiser-donnees" in err


# --- prepare partagé ------------------------------------------------------------------------

@pytest.mark.parametrize("premiere", ["cle_contenu", "auteur"])
def test_prepare_lit_un_historique_avec_bom(env, premiere):
    """Un CSV réenregistré par Excel commence par un BOM, collé au nom de la PREMIÈRE colonne :
    sans `utf-8-sig`, la clé (ou le fichier entier, faute de colonne auteur) serait perdue."""
    cols = [premiere] + [c for c in ("cle_contenu", "auteur", "url_post", "post_extrait")
                         if c != premiere]
    _ecrire_csv(env.donnees / "historique" / f"DELTA_{R0}.csv", cols, [{
        "cle_contenu": cle_contenu("Ecole Alpha", _texte("Ecole Alpha")), "auteur": "Ecole Alpha",
        "url_post": "https://lnkd.in/p/autrelien", "post_extrait": "Annonce fictive",
    }], encoding="utf-8-sig")
    _lot(env, R1, [_candidat("Ecole Alpha")])
    assert _cmd(env, "prepare", "--run", R1) == 0
    rap = _rapport(env, R1)
    assert (rap["deja_connus"], rap["nouveaux"]) == (1, 0)


def test_prepare_lit_une_copie_en_conflit_avec_avertissement(env, capsys):
    copie = f"DELTA_{R0} (1).csv"
    _ecrire_csv(env.donnees / "historique" / copie, COLS, [
        _post("Ecole Alpha", cle_contenu=cle_contenu("Ecole Alpha", _texte("Ecole Alpha")),
              url_post="https://lnkd.in/p/autrelien")])
    _lot(env, R1, [_candidat("Ecole Alpha")])
    assert _cmd(env, "prepare", "--run", R1) == 0
    assert _rapport(env, R1)["deja_connus"] == 1  # l'union des clés : la plus prudente
    err = capsys.readouterr().err
    assert "copie(s) en conflit" in err and copie in err


def test_prepare_ignore_le_fichier_de_travail_d_excel(env, capsys):
    verrou_excel = f"~$DELTA_{R0}.csv"
    _ecrire_csv(env.donnees / "historique" / verrou_excel, COLS, [
        _post("Ecole Alpha", cle_contenu=cle_contenu("Ecole Alpha", _texte("Ecole Alpha")))])
    _lot(env, R1, [_candidat("Ecole Alpha")])
    assert _cmd(env, "prepare", "--run", R1) == 0
    rap = _rapport(env, R1)
    assert (rap["deja_connus"], rap["nouveaux"]) == (0, 1)
    assert verrou_excel in capsys.readouterr().out  # ignoré, mais nommé


def test_prepare_bloque_sur_un_fichier_illisible_sans_rien_ecrire(env, capsys):
    """Un fichier « en ligne uniquement » sur un poste hors connexion, ou mal encodé : BLOQUANT."""
    illisible = env.donnees / "historique" / f"DELTA_{R0}.csv"
    illisible.write_bytes("auteur,post_extrait\nÉcole Alpha,Annonce\n".encode("latin-1"))
    _lot(env, R1, [_candidat("Ecole Alpha")])
    code = _cmd(env, "prepare", "--run", R1)
    assert not (env.donnees / "runs" / R1 / "a_scorer.json").exists()
    assert not (env.donnees / "verrou.json").exists()
    assert not (env.donnees / "runs" / R1 / "proprietaire.json").exists()
    assert code == 2
    err = capsys.readouterr().err
    assert "illisible" in err and str(illisible) in err


def test_prepare_d_un_run_deja_finalise(env, capsys):
    _ecrire_csv(env.donnees / "historique" / f"DELTA_{R1}.csv", COLS, [])
    _lot(env, R1, [_candidat("Ecole Alpha")])
    code = _cmd(env, "prepare", "--run", R1)
    assert not (env.donnees / "runs" / R1 / "a_scorer.json").exists()
    assert code == 2
    assert "déjà finalisé" in capsys.readouterr().err
    assert _cmd(env, "prepare", "--run", R1, "--forcer") == 0


@pytest.mark.parametrize("run", [
    "2030-01-01", "1-1-2030", "32-01-2030", "01-13-2030", "01-01-2030-1", "01-01-2030-02",
    "01-01-2030-bis", "01.01.2030",
])
def test_prepare_refuse_un_identifiant_de_run_invalide(env, capsys, run):
    _lot(env, run, [_candidat("Ecole Alpha")])
    code = _cmd(env, "prepare", "--run", run)
    assert not (env.donnees / "runs" / run / "a_scorer.json").exists()
    assert not (env.donnees / "verrou.json").exists()
    assert code == 2
    assert "identifiant de run invalide" in capsys.readouterr().err


def test_le_mode_local_garde_l_identifiant_libre(env, capsys):
    (env.depot / "runs" / "run-libre").mkdir()
    code = main(["prepare", "--run", "run-libre"])
    assert "identifiant de run invalide" not in capsys.readouterr().err
    assert code == 1  # aucun JSON à préparer, mais le nom n'est pas refusé


def test_prepare_sous_verrou_etranger_code_3(env, capsys):
    env.poste("PC-B")
    verrou.prendre(str(env.donnees), R1, "lots")
    tenu = (env.donnees / "verrou.json").read_text(encoding="utf-8")
    env.poste("PC-A")
    _lot(env, R1, [_candidat("Ecole Alpha")])
    code = _cmd(env, "prepare", "--run", R1)
    assert not (env.donnees / "runs" / R1 / "a_scorer.json").exists()
    assert (env.donnees / "verrou.json").read_text(encoding="utf-8") == tenu
    assert code == 3
    assert "PC-B" in capsys.readouterr().err


def test_prepare_d_un_run_prepare_par_un_autre_poste(env, capsys):
    env.poste("PC-B")
    _lot(env, R1, [_candidat("Ecole Alpha")])
    assert _cmd(env, "prepare", "--run", R1) == 0
    verrou.liberer(str(env.donnees), R1)  # PC-B a fini sa journée sans finaliser
    env.poste("PC-A")
    code = _cmd(env, "prepare", "--run", R1)
    assert _verrou(env)["etat"] == "libre"
    assert code == 3
    assert "PC-B" in capsys.readouterr().err
    assert _cmd(env, "prepare", "--run", R1, "--forcer") == 0
    proprio = json.loads((env.donnees / "runs" / R1 / "proprietaire.json").read_text(encoding="utf-8"))
    assert proprio["poste"] == "PC-A"


def test_prepare_compte_a_part_les_cles_recalculees_des_json_bruts(env, capsys):
    _lot(env, R0, [_candidat("Ecole Alpha", url="https://lnkd.in/p/premierlien")])
    _lot(env, R1, [_candidat("Ecole Alpha", url="https://lnkd.in/p/secondlien"),
                   _candidat("Ecole Beta")])
    assert _cmd(env, "prepare", "--run", R1) == 0
    assert "1 clé(s) recalculée(s) depuis 1 JSON brut(s)" in capsys.readouterr().out
    assert (_rapport(env, R1)["deja_connus"], _rapport(env, R1)["nouveaux"]) == (1, 1)


# --- finaliser partagé ----------------------------------------------------------------------

def test_finaliser_ecrit_classeur_et_delta_sans_temporaire_ni_export(env, capsys):
    _scored(env, R1, [_post("Ecole Alpha"), _post("Ecole Beta", score=4)])
    avant = _arbre(env.depot)
    assert _cmd(env, "finaliser", "--run", R1) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == f"données : partagé — {env.donnees}"
    assert sorted(p["auteur"] for p in _onglet(_classeur(env, R1))) == ["Ecole Alpha", "Ecole Beta"]
    delta = _lignes_csv(env.donnees / "historique" / f"DELTA_{R1}.csv")
    assert delta[0] == COLS and len(delta) == 3
    assert _tmp_restants(env) == []
    # ni MASTER.csv ni SUIVI_LEADS.csv, nulle part ; rien sous le dépôt
    assert sorted(p.name for p in env.donnees.rglob("*.csv")) == [f"DELTA_{R1}.csv"]
    assert _arbre(env.depot) == avant


def _refuser_replace(monkeypatch, suffixe):
    """`os.replace` refusé (fichier ouvert dans Excel, Drive qui synchronise) vers `*suffixe`."""
    vrai = os.replace

    def replace(src, dst):
        if str(dst).endswith(suffixe):
            raise PermissionError(13, "fichier ouvert ailleurs", str(dst))
        return vrai(src, dst)

    monkeypatch.setattr(os, "replace", replace)


def test_un_classeur_refuse_ne_laisse_ni_fichier_ni_temporaire(env, capsys, monkeypatch):
    _scored(env, R1, [_post("Ecole Alpha")])
    _refuser_replace(monkeypatch, ".xlsx")
    code = _cmd(env, "finaliser", "--run", R1)
    assert not _classeur(env, R1).exists()
    assert not (env.donnees / "historique" / f"DELTA_{R1}.csv").exists()
    assert _tmp_restants(env) == []
    assert code == 2
    assert "écriture refusée" in capsys.readouterr().err


def test_un_delta_refuse_laisse_le_run_non_finalise(env, capsys, monkeypatch):
    """Le DELTA vient après le classeur : refusé, le run n'est pas marqué finalisé."""
    _scored(env, R1, [_post("Ecole Alpha")])
    _refuser_replace(monkeypatch, ".csv")
    code = _cmd(env, "finaliser", "--run", R1)
    assert _classeur(env, R1).exists()
    assert not (env.donnees / "historique" / f"DELTA_{R1}.csv").exists()
    assert _tmp_restants(env) == []
    assert code == 2
    assert "pas marqué finalisé" in capsys.readouterr().err


def test_un_verrou_impossible_a_ecrire_sort_en_code_2_avec_un_message(env, capsys, monkeypatch):
    _lot(env, R1, [_candidat("Ecole Alpha")])
    _refuser_replace(monkeypatch, "verrou.json")
    code = _cmd(env, "prepare", "--run", R1)
    assert not (env.donnees / "runs" / R1 / "a_scorer.json").exists()
    assert code == 2
    assert "impossible d'écrire le verrou" in capsys.readouterr().err


def test_master_base_plus_anterieurs_plus_courant_sans_doublon(env, capsys):
    """Base R1, DELTA_R1 sans colonne cle_contenu et aux liens lnkd.in tous différents, run R2.

    Gamma manque à la base (ligne supprimée à la main) : elle est réinjectée, une fois."""
    construire([_post("Ecole Alpha"), _post("Ecole Beta")], run=R1, sortie=str(_classeur(env, R1)))
    _ecrire_csv(env.donnees / "historique" / f"DELTA_{R1}.csv", COLS_SANS_CLE, [
        _post("Ecole Alpha", url_post="https://lnkd.in/p/alpha2"),
        _post("Ecole Beta", url_post="https://lnkd.in/p/beta2"),
        _post("Ecole Gamma", url_post="https://lnkd.in/p/gamma2"),
    ])
    _scored(env, R2, [_post("Ecole Delta")])
    assert _cmd(env, "finaliser", "--run", R2) == 0
    assert [p["auteur"] for p in _onglet(_classeur(env, R2))] == [
        "Ecole Alpha", "Ecole Beta", "Ecole Gamma", "Ecole Delta"]
    out = capsys.readouterr().out
    assert "reinjectees=1" in out and "réinjectées depuis l'historique : 1" in out
    # un antérieur n'entre pas au DELTA du run courant
    assert [r[COLS.index("auteur")] for r in _lignes_csv(
        env.donnees / "historique" / f"DELTA_{R2}.csv")[1:]] == ["Ecole Delta"]


def test_un_anterieur_blackliste_n_est_jamais_reinjecte(env, capsys):
    # « Ecole Interdite » n'est blacklistée que dans la config du dossier partagé
    _ecrire_csv(env.donnees / "historique" / f"DELTA_{R1}.csv", COLS, [
        _post("Ecole Interdite Lyon"), _post("Ecole Alpha")])
    _scored(env, R2, [_post("Ecole Delta")])
    assert _cmd(env, "finaliser", "--run", R2) == 0
    assert [p["auteur"] for p in _onglet(_classeur(env, R2))] == ["Ecole Alpha", "Ecole Delta"]
    assert "1 ligne(s) d'historique écartée(s) (F4 blacklist)" in capsys.readouterr().out


def test_les_labels_du_classeur_precedent_sont_reportes(env):
    _scored(env, R1, [_post("Ecole Alpha"), _post("Ecole Beta", score=4)])
    assert _cmd(env, "finaliser", "--run", R1) == 0
    chemin = _classeur(env, R1)
    wb = openpyxl.load_workbook(chemin)
    lignes = [r[COLS.index("auteur")] for r in wb["MASTER"].iter_rows(min_row=2, values_only=True)]
    wb["MASTER"].cell(row=lignes.index("Ecole Beta") + 2, column=COLS.index("validation") + 1,
                      value="NON")
    wb["SUIVI_LEADS"].cell(row=2, column=COLS_LEADS.index("statut_lead") + 1, value="Contacté")
    wb.save(chemin)
    _scored(env, R2, [_post("Ecole Gamma")])
    assert _cmd(env, "finaliser", "--run", R2) == 0
    master = {p["auteur"]: p["validation"] for p in _onglet(_classeur(env, R2))}
    assert master == {"Ecole Alpha": None, "Ecole Beta": "NON", "Ecole Gamma": None}
    leads = {p["organisation"]: p["statut_lead"] for p in _onglet(_classeur(env, R2), "SUIVI_LEADS")}
    assert leads == {"Ecole Alpha": "Contacté", "Ecole Gamma": "À contacter"}


def test_refinaliser_conserve_les_labels_saisis_dans_le_classeur_du_run(env, capsys):
    _scored(env, R1, [_post("Ecole Alpha"), _post("Ecole Beta", score=4)])
    assert _cmd(env, "finaliser", "--run", R1) == 0
    chemin = _classeur(env, R1)
    wb = openpyxl.load_workbook(chemin)
    wb["MASTER"].cell(row=2, column=COLS.index("validation") + 1, value="OUI")
    wb["MASTER"].cell(row=2, column=COLS.index("motif") + 1, value="à relancer")
    wb["SUIVI_LEADS"].cell(row=2, column=COLS_LEADS.index("statut_lead") + 1, value="Relancé")
    wb.save(chemin)
    capsys.readouterr()
    assert _cmd(env, "finaliser", "--run", R1) == 0
    master = _onglet(chemin)
    assert len(master) == 2  # le MASTER reste en ajout seul : aucun doublon
    assert (master[0]["validation"], master[0]["motif"]) == ("OUI", "à relancer")
    assert [p["statut_lead"] for p in _onglet(chemin, "SUIVI_LEADS")] == ["Relancé"]
    assert "reinjectees=0" in capsys.readouterr().out


def test_un_classeur_posterieur_bloque_la_finalisation(env, capsys):
    construire([_post("Ecole Zeta")], run=R3, sortie=str(_classeur(env, R3)))
    _scored(env, R2, [_post("Ecole Alpha")])
    code = _cmd(env, "finaliser", "--run", R2)
    assert not _classeur(env, R2).exists()
    assert not (env.donnees / "historique" / f"DELTA_{R2}.csv").exists()
    assert code == 2
    assert f"prospection_{R3}.xlsx" in capsys.readouterr().err
    assert _cmd(env, "finaliser", "--run", R2, "--forcer") == 0


def test_la_base_se_choisit_par_date_analysee_et_non_par_ordre_lexical(env, capsys):
    # en ordre lexical, « 25-12-2029 » passerait après « 01-01-2030 »
    construire([_post("Ecole Ancienne")], run=R0, sortie=str(_classeur(env, R0)))
    construire([_post("Ecole Recente")], run=R1, sortie=str(_classeur(env, R1)))
    _scored(env, R2, [_post("Ecole Gamma")])
    assert _cmd(env, "finaliser", "--run", R2) == 0
    assert f"classeur de base : {_classeur(env, R1)}" in capsys.readouterr().out


@pytest.mark.parametrize("dossier, copie", [
    ("classeurs", f"prospection_{R1} (1).xlsx"),
    ("historique", f"DELTA_{R1} (1).csv"),
    (".", "config (1).yaml"),
], ids=["classeurs", "historique", "config"])
def test_une_copie_en_conflit_critique_bloque_la_finalisation(env, capsys, dossier, copie):
    (env.donnees / dossier / copie).write_bytes(b"copie en conflit du Drive")
    _scored(env, R2, [_post("Ecole Alpha")])
    code = _cmd(env, "finaliser", "--run", R2)
    assert not _classeur(env, R2).exists()
    assert not (env.donnees / "historique" / f"DELTA_{R2}.csv").exists()
    assert code == 2
    assert copie in capsys.readouterr().err


def test_une_base_illisible_bloque_sans_rien_ecrire(env, capsys):
    _classeur(env, R1).write_bytes(b"pas un classeur : un fichier en ligne uniquement")
    _scored(env, R2, [_post("Ecole Alpha")])
    code = _cmd(env, "finaliser", "--run", R2)
    assert not _classeur(env, R2).exists()
    assert not (env.donnees / "historique" / f"DELTA_{R2}.csv").exists()
    assert not (env.donnees / "verrou.json").exists()
    assert code == 2
    err = capsys.readouterr().err
    assert "illisible" in err and f"prospection_{R1}.xlsx" in err


def test_un_classeur_ouvert_dans_excel_bloque(env, capsys):
    construire([_post("Ecole Alpha")], run=R1, sortie=str(_classeur(env, R1)))
    (env.donnees / "classeurs" / f"~$prospection_{R1}.xlsx").write_bytes(b"\x04anon")
    _scored(env, R2, [_post("Ecole Beta")])
    assert _cmd(env, "finaliser", "--run", R2) == 2  # la base est ouverte
    assert "ouvert dans Excel" in capsys.readouterr().err
    _scored(env, R1, [_post("Ecole Alpha")])
    assert _cmd(env, "finaliser", "--run", R1) == 2  # le classeur du run est ouvert


def test_l_option_base_est_controlee(env, capsys):
    construire([_post("Ecole Ancienne")], run=R0, sortie=str(_classeur(env, R0)))
    construire([_post("Ecole Recente")], run=R1, sortie=str(_classeur(env, R1)))
    ailleurs = env.tmp / "ailleurs.xlsx"
    construire([_post("Ecole Externe")], run=R0, sortie=str(ailleurs))
    _scored(env, R2, [_post("Ecole Gamma")])
    for base, motif in ((env.tmp / "absent.xlsx", "--base introuvable"),
                        (ailleurs, "hors de classeurs/"),
                        (_classeur(env, R0), "différent de la base calculée")):
        code = _cmd(env, "finaliser", "--run", R2, "--base", str(base))
        assert not _classeur(env, R2).exists()
        assert code == 2
        assert motif in capsys.readouterr().err
    assert _cmd(env, "finaliser", "--run", R2, "--base", str(_classeur(env, R1))) == 0
    assert _cmd(env, "finaliser", "--run", R2, "--base", str(ailleurs), "--forcer") == 0
    assert "Ecole Externe" in [p["auteur"] for p in _onglet(_classeur(env, R2))]


def test_un_delta_anterieur_absent_de_la_base_est_signale(env, capsys):
    construire([_post("Ecole Alpha")], run=R1, sortie=str(_classeur(env, R1)))
    _ecrire_csv(env.donnees / "historique" / f"DELTA_{R0}.csv", COLS, [_post("Ecole Zeta")])
    _ecrire_csv(env.donnees / "historique" / f"DELTA_{R1}.csv", COLS, [_post("Ecole Alpha")])
    _scored(env, R2, [_post("Ecole Gamma")])
    assert _cmd(env, "finaliser", "--run", R2) == 0
    err = capsys.readouterr().err
    assert f"pas d'onglet DELTA_{R0}" in err
    assert f"pas d'onglet DELTA_{R1}" not in err  # l'onglet DELTA_R1 est dans la base


def test_finaliser_sous_verrou_etranger_ou_run_d_un_autre_poste(env, capsys):
    _scored(env, R1, [_post("Ecole Alpha")])
    env.poste("PC-B")
    verrou.prendre(str(env.donnees), R1, "prepare")
    env.poste("PC-A")
    code = _cmd(env, "finaliser", "--run", R1)
    assert not _classeur(env, R1).exists()
    assert code == 3
    assert "PC-B" in capsys.readouterr().err
    env.poste("PC-B")
    verrou.liberer(str(env.donnees), R1)
    (env.donnees / "runs" / R1 / "proprietaire.json").write_text(
        json.dumps({"poste": "PC-B", "depuis": "2030-01-01T08:00:00+00:00"}), encoding="utf-8")
    env.poste("PC-A")
    code = _cmd(env, "finaliser", "--run", R1)
    assert not _classeur(env, R1).exists()
    assert code == 3
    assert "préparé sur le poste PC-B" in capsys.readouterr().err
    assert _cmd(env, "finaliser", "--run", R1, "--forcer") == 0


def test_un_garde_fou_en_echec_ne_prend_pas_le_verrou(env, capsys):
    _scored(env, R1, [_post("Ecole Alpha", commentaire_scoring="")])
    code = _cmd(env, "finaliser", "--run", R1)
    assert not (env.donnees / "verrou.json").exists()
    assert not _classeur(env, R1).exists()
    assert code == 2
    assert "GARDE-FOUS EN ÉCHEC" in capsys.readouterr().err


def test_deux_runs_depuis_deux_postes_master_cumulatif(env, capsys):
    """PC-A fait le run R1 de bout en bout, puis PC-B le run R2 sur le même dossier."""
    _lot(env, R1, [_candidat("Ecole Alpha")])
    assert _cmd(env, "prepare", "--run", R1) == 0
    _scored(env, R1, [_post("Ecole Alpha")])
    assert _cmd(env, "finaliser", "--run", R1) == 0
    assert (_verrou(env)["etat"], _verrou(env)["poste"]) == ("libre", "PC-A")

    env.poste("PC-B")
    # Alpha revient avec un nouveau lien lnkd.in : connue par son contenu
    _lot(env, R2, [_candidat("Ecole Alpha", url="https://lnkd.in/p/nouveaulien"),
                   _candidat("Ecole Beta")])
    assert _cmd(env, "lots", "--run", R2) == 0
    capsys.readouterr()
    assert _cmd(env, "prepare", "--run", R2) == 0
    assert (_rapport(env, R2)["deja_connus"], _rapport(env, R2)["nouveaux"]) == (1, 1)
    # runs/R1 porte A.json, mais aussi proprietaire.json, a_scorer.json, rapport et scored :
    # seul A.json est un JSON brut d'agent
    assert "1 clé(s) recalculée(s) depuis 1 JSON brut(s)" in capsys.readouterr().out
    _scored(env, R2, [_post("Ecole Beta")])
    capsys.readouterr()
    assert _cmd(env, "finaliser", "--run", R2) == 0
    out = capsys.readouterr().out
    assert [p["auteur"] for p in _onglet(_classeur(env, R2))] == ["Ecole Alpha", "Ecole Beta"]
    assert "réinjectées depuis l'historique : 0" in out  # régime normal
    assert sorted(p.name for p in (env.donnees / "historique").iterdir()) == [
        f"DELTA_{R1}.csv", f"DELTA_{R2}.csv"]
    v = _verrou(env)
    assert (v["etat"], v["poste"], v["run"]) == ("libre", "PC-B", R2)  # libéré à la fin
    assert "verrou libéré" in out


# --- lots --run et verrou ---------------------------------------------------------------------

def test_lots_run_cree_le_dossier_prend_le_verrou_et_affiche_les_chemins(env, capsys):
    assert _cmd(env, "lots", "--run", R1) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == f"données : partagé — {env.donnees}"
    assert f"dossier du run : {env.donnees / 'runs' / R1}" in out
    assert f"config : {env.donnees / 'config.yaml'}" in out
    assert (env.donnees / "runs" / R1).is_dir()
    assert (_verrou(env)["etat"], _verrou(env)["commande"]) == ("pris", "lots")


def test_lots_run_refuse_un_identifiant_invalide_ou_un_verrou_etranger(env, capsys):
    code = _cmd(env, "lots", "--run", "01-01-30")
    assert not (env.donnees / "runs" / "01-01-30").exists()
    assert code == 2
    env.poste("PC-B")
    verrou.prendre(str(env.donnees), R1, "lots")
    env.poste("PC-A")
    code = _cmd(env, "lots", "--run", R2)
    assert not (env.donnees / "runs" / R2).exists()
    assert code == 3
    assert "PC-B" in capsys.readouterr().err


def test_lots_run_en_mode_local_cree_le_dossier_sans_verrou(env, capsys):
    assert main(["lots", "--run", "run-libre"]) == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == f"données : local — {env.depot / 'data'}"
    assert (env.depot / "runs" / "run-libre").is_dir()
    assert not list(env.depot.rglob("verrou*.json"))


def test_poste_et_initialiser_donnees_passent_par_la_ligne_de_commande(env, capsys, monkeypatch):
    """Câblage seulement (le détail est testé dans test_poste.py et test_migration.py) :
    `--vers` relatif se lit, comme `--donnees`, depuis le répertoire courant, avant `--racine`."""
    _sans_registre(monkeypatch)
    monkeypatch.chdir(env.tmp)
    assert main(["--racine", "depot", "initialiser-donnees", "--vers", "neuf"]) == 0
    assert (env.tmp / "neuf" / MARQUEUR).is_file()
    assert (env.tmp / "neuf" / "config.yaml").read_text(encoding="utf-8") == CONFIG_LOCALE
    # dossier initialisé, config présente, verrou libre, git jamais bloquant : aucun BLOQUANT
    assert main(["--donnees", str(env.donnees), "poste", "--run", R1]) == 0
    assert "profil chargé" in capsys.readouterr().out


def test_la_commande_verrou(env, capsys):
    assert main(["verrou", "statut"]) == 0
    assert "sans objet en mode local" in capsys.readouterr().out
    assert _cmd(env, "verrou", "prendre") == 2  # --run exigé
    assert _cmd(env, "verrou", "prendre", "--run", R1) == 0
    assert _cmd(env, "verrou", "statut", "--run", R1) == 0
    out = capsys.readouterr().out
    assert "pris — poste PC-A" in out and "possible" in out
    env.poste("PC-B")
    assert _cmd(env, "verrou", "liberer", "--run", R1) == 3
    assert _verrou(env)["etat"] == "pris"
    assert _cmd(env, "verrou", "liberer", "--run", R1, "--forcer") == 0
    assert _verrou(env)["etat"] == "libre"


# --- scénarios transverses : migration, plusieurs postes, poste (spec §8) ---------------------

def _ailleurs(donnees):
    """Pour réutiliser `_lot` et `_rapport` sur un autre dossier que `env.donnees`."""
    return SimpleNamespace(donnees=donnees)


def _sans_registre(monkeypatch):
    """La variable « User » de ce PC (s'il en a une) ne doit pas colorer la sortie de `poste`."""
    monkeypatch.setattr(poste, "_variable_utilisateur", lambda: None)


def test_migration_puis_dedup_un_post_connu_par_un_json_brut_reste_connu(env, capsys):
    """Le post n'est connu que par le JSON brut d'un ancien run : son DELTA porte une clé de
    contenu périmée (calculée avant le correctif #3) et un autre lien lnkd.in. Après
    `initialiser-donnees`, `prepare` partagé le compte `deja_connus` grâce aux clés recalculées
    depuis le JSON copié. Garde : migré sans les runs, le même post revient comme nouveau."""
    _ecrire_csv(env.depot / "data" / f"DELTA_{R0}.csv", COLS, [
        _post("Ecole Alpha", cle_contenu="cle-perimee", url_post="https://lnkd.in/p/BBB")])
    _lot(_ailleurs(env.depot), R0, [_candidat("Ecole Alpha", url="https://lnkd.in/p/AAA")])
    revu = [_candidat("Ecole Alpha", url="https://lnkd.in/p/CCC")]

    rapports, sorties = {}, {}
    for nom, options in (("avec_runs", []), ("sans_runs", ["--runs", "pas_de_runs"])):
        cible = env.tmp / "drive" / nom
        assert main(["initialiser-donnees", "--vers", str(cible), *options]) == 0
        assert (cible / "historique" / f"DELTA_{R0}.csv").is_file()  # le DELTA migre dans les deux cas
        _lot(_ailleurs(cible), R1, revu)
        capsys.readouterr()
        assert main(["--donnees", str(cible), "prepare", "--run", R1]) == 0
        rapports[nom], sorties[nom] = _rapport(_ailleurs(cible), R1), capsys.readouterr().out

    assert (rapports["avec_runs"]["deja_connus"], rapports["avec_runs"]["nouveaux"]) == (1, 0)
    assert "1 clé(s) recalculée(s) depuis 1 JSON brut(s)" in sorties["avec_runs"]
    assert (rapports["sans_runs"]["deja_connus"], rapports["sans_runs"]["nouveaux"]) == (0, 1)
    assert "0 clé(s) recalculée(s) depuis 0 JSON brut(s)" in sorties["sans_runs"]


def test_deux_postes_le_second_attend_la_fin_du_run_du_premier(env, capsys, monkeypatch):
    """PC-A tient le verrou de R1, de `lots --run` à `finaliser`. Pendant ce temps PC-B est
    refusé (code 3, et 2 pour `poste --run`) sans rien écrire. Puis PC-B fait R2 sur le même
    dossier : MASTER cumulatif, labels saisis par PC-A dans le classeur R1 reportés, verrou pris
    puis libéré par chaque poste, et PC-A refusé à son tour pendant le run de PC-B."""
    _sans_registre(monkeypatch)
    runs = env.donnees / "runs"

    # PC-A ouvre et prépare R1 : le verrou est à lui
    assert _cmd(env, "lots", "--run", R1) == 0
    v = _verrou(env)
    assert (v["etat"], v["poste"], v["run"], v["commande"]) == ("pris", "PC-A", R1, "lots")
    _lot(env, R1, [_candidat("Ecole Alpha"), _candidat("Ecole Beta")])
    assert _cmd(env, "prepare", "--run", R1) == 0
    assert (_verrou(env)["etat"], _verrou(env)["commande"]) == ("pris", "prepare")
    tenu = (env.donnees / "verrou.json").read_bytes()

    # PC-B, pendant le run de PC-A
    env.poste("PC-B")
    capsys.readouterr()
    code_lots = _cmd(env, "lots", "--run", R2)
    assert not (runs / R2).exists()  # le dossier du run n'est créé qu'une fois le verrou pris
    assert code_lots == 3
    assert "PC-A" in capsys.readouterr().err
    _lot(env, R2, [_candidat("Ecole Gamma")])  # ses agents ont scrapé (et scoré) quand même
    _scored(env, R2, [_post("Ecole Gamma")])
    codes = {cmd: _cmd(env, cmd, "--run", R2) for cmd in ("prepare", "finaliser")}
    codes["verrou liberer"] = _cmd(env, "verrou", "liberer", "--run", R1)
    assert sorted(p.name for p in (runs / R2).iterdir()) == ["A.json", "scored_A.json"]
    assert not _classeur(env, R2).exists()
    assert not (env.donnees / "historique" / f"DELTA_{R2}.csv").exists()
    assert (env.donnees / "verrou.json").read_bytes() == tenu  # ni repris, ni libéré
    assert codes == {"prepare": 3, "finaliser": 3, "verrou liberer": 3}
    capsys.readouterr()
    assert _cmd(env, "poste", "--run", R2) == 2  # le contrôle du PC le dit aussi : BLOQUANT
    assert any(ligne.startswith("BLOQUANT") and "verrou" in ligne and "PC-A" in ligne
               for ligne in capsys.readouterr().out.splitlines())

    # PC-A finalise R1 et libère le verrou, puis saisit ses labels dans le classeur R1
    env.poste("PC-A")
    _scored(env, R1, [_post("Ecole Alpha"), _post("Ecole Beta", score=4)])
    assert _cmd(env, "finaliser", "--run", R1) == 0
    v = _verrou(env)
    assert (v["etat"], v["poste"], v["run"]) == ("libre", "PC-A", R1)
    chemin = _classeur(env, R1)
    wb = openpyxl.load_workbook(chemin)
    auteurs = [r[COLS.index("auteur")] for r in wb["MASTER"].iter_rows(min_row=2, values_only=True)]
    ligne_beta = auteurs.index("Ecole Beta") + 2
    wb["MASTER"].cell(row=ligne_beta, column=COLS.index("validation") + 1, value="NON")
    wb["MASTER"].cell(row=ligne_beta, column=COLS.index("motif") + 1, value="hors zone")
    wb["SUIVI_LEADS"].cell(row=2, column=COLS_LEADS.index("statut_lead") + 1, value="Contacté")
    wb.save(chemin)

    # PC-B fait R2 : le verrou est à lui, PC-A est refusé à son tour
    env.poste("PC-B")
    assert _cmd(env, "lots", "--run", R2) == 0
    v = _verrou(env)
    assert (v["etat"], v["poste"], v["run"]) == ("pris", "PC-B", R2)
    assert _cmd(env, "poste", "--run", R2) == 0
    # Alpha revient avec un nouveau lien lnkd.in : connue par le JSON brut de R1
    _lot(env, R2, [_candidat("Ecole Alpha", url="https://lnkd.in/p/nouveaulien"),
                   _candidat("Ecole Gamma")])
    assert _cmd(env, "prepare", "--run", R2) == 0
    assert (_rapport(env, R2)["deja_connus"], _rapport(env, R2)["nouveaux"]) == (1, 1)
    env.poste("PC-A")
    code_lots = _cmd(env, "lots", "--run", R3)
    assert not (runs / R3).exists()
    assert code_lots == 3
    env.poste("PC-B")
    _scored(env, R2, [_post("Ecole Gamma")])
    capsys.readouterr()
    assert _cmd(env, "finaliser", "--run", R2) == 0
    out = capsys.readouterr().out

    master = _onglet(_classeur(env, R2))
    assert [p["auteur"] for p in master] == ["Ecole Alpha", "Ecole Beta", "Ecole Gamma"]
    assert {p["auteur"]: (p["validation"], p["motif"]) for p in master} == {
        "Ecole Alpha": (None, None), "Ecole Beta": ("NON", "hors zone"), "Ecole Gamma": (None, None)}
    leads = {p["organisation"]: p["statut_lead"] for p in _onglet(_classeur(env, R2), "SUIVI_LEADS")}
    assert leads == {"Ecole Alpha": "Contacté", "Ecole Gamma": "À contacter"}
    assert "réinjectées depuis l'historique : 0" in out
    assert sorted(p.name for p in (env.donnees / "historique").iterdir()) == [
        f"DELTA_{R1}.csv", f"DELTA_{R2}.csv"]
    proprietaires = {r: json.loads((runs / r / "proprietaire.json").read_text(encoding="utf-8"))["poste"]
                     for r in (R1, R2)}
    assert proprietaires == {R1: "PC-A", R2: "PC-B"}
    v = _verrou(env)
    assert (v["etat"], v["poste"], v["run"]) == ("libre", "PC-B", R2)


def test_initialiser_donnees_puis_poste_sur_le_dossier_cree(env, capsys, monkeypatch):
    """Par la ligne de commande : le dossier créé par `initialiser-donnees` passe `poste` (code 0),
    par `--donnees` comme par la variable. Sans elle, le mode local s'arrête sur le marqueur de
    migration (code 2) au lieu de lire un data/ périmé."""
    _sans_registre(monkeypatch)
    _ecrire_csv(env.depot / "data" / f"DELTA_{R0}.csv", COLS, [_post("Ecole Alpha")])
    _lot(_ailleurs(env.depot), R0, [_candidat("Ecole Alpha")])
    construire([_post("Ecole Alpha")], run=R0,
               sortie=str(env.depot / "data" / f"prospection_{R0}.xlsx"))
    cible = env.tmp / "drive" / "migre"
    assert main(["initialiser-donnees", "--vers", str(cible)]) == 0
    capsys.readouterr()

    assert main(["--donnees", str(cible), "poste", "--run", R1]) == 0
    out = capsys.readouterr().out
    assert f"données : partagé — {cible}" in out
    for attendu in ("profil chargé (config.yaml)",
                    "historique : 1 fichier(s) reconnu(s), 1 ligne(s)",
                    "clés JSON : 1 clé(s) recalculée(s) depuis 1 JSON brut(s)",
                    f"classeur : le plus récent : classeurs/prospection_{R0}.xlsx",
                    "bilan : 0 bloquant(s)"):
        assert attendu in out

    monkeypatch.setenv("PROSPECTION_DONNEES", str(cible))  # posée, terminaux redémarrés
    assert main(["poste"]) == 0
    assert f"données : partagé — {cible}" in capsys.readouterr().out

    monkeypatch.delenv("PROSPECTION_DONNEES")
    assert main(["poste"]) == 2
    assert any(ligne.startswith("BLOQUANT") and "migration" in ligne
               for ligne in capsys.readouterr().out.splitlines())


@pytest.mark.parametrize("run", [
    R0, R1, "01-01-2030-2", "01-01-2030-10", "01-01-2030-1", "01-01-2030-02", "31-02-2030",
    "2030-01-01", "01-01-2030-bis",
])
def test_poste_et_finaliser_reconnaissent_les_memes_classeurs(run):
    """`poste` et `initialiser-donnees` (poste.cle_classeur) désignent le classeur le plus récent,
    `finaliser` (run.cle_run) choisit sa base : ils doivent lire les mêmes noms, dans le même
    ordre. Un « -02 » classeur pour l'un et pas pour l'autre ferait migrer un classeur zéro que
    finaliser ne prendrait jamais comme base."""
    assert poste.cle_classeur(f"prospection_{run}.xlsx") == run_mod.cle_run(run)


@pytest.mark.parametrize("nom", [
    "config (1).yaml", f"DELTA_{R1} (2).csv", "verrou (1).json", "historique (1)",
    f"DELTA_{R1}.csv", "~$prospection (1).xlsx", "verrou (1).json.tmp", "notes (brouillon).txt",
])
def test_poste_et_finaliser_voient_les_memes_copies_en_conflit(nom):
    assert poste.copie_en_conflit(nom) == run_mod.copie_en_conflit(nom)


# --- revue adversariale : verrou en fin de run, --config, lots, ordre des antérieurs ----------

def _refuser_replace_apres(monkeypatch, suffixe, acceptes):
    """`os.replace` vers `*suffixe` accepté `acceptes` fois, puis refusé (Drive qui tient le fichier)."""
    vrai = os.replace
    vus = []

    def replace(src, dst):
        if str(dst).endswith(suffixe):
            vus.append(dst)
            if len(vus) > acceptes:
                raise PermissionError(13, "fichier ouvert ailleurs", str(dst))
        return vrai(src, dst)

    monkeypatch.setattr(os, "replace", replace)


def test_un_verrou_impossible_a_liberer_laisse_le_run_finalise_avec_un_avertissement(
        env, capsys, monkeypatch):
    """Le Drive refuse la réécriture de verrou.json en fin de `finaliser` : le run EST finalisé
    (classeur et DELTA écrits), donc code 0, et l'avertissement dit comment libérer le verrou.
    Code 1 voudrait dire « rien à traiter » (docs/10) : une tâche planifiée s'y tromperait."""
    _scored(env, R1, [_post("Ecole Alpha")])
    _refuser_replace_apres(monkeypatch, "verrou.json", 1)  # la prise passe, la libération non
    code = _cmd(env, "finaliser", "--run", R1)
    assert _classeur(env, R1).exists()
    assert (env.donnees / "historique" / f"DELTA_{R1}.csv").exists()
    assert _tmp_restants(env) == []
    v = _verrou(env)
    assert (v["etat"], v["poste"], v["run"]) == ("pris", "PC-A", R1)
    assert code == 0
    err = capsys.readouterr().err
    assert "run finalisé" in err and "verrou non libéré" in err
    assert f"verrou liberer --run {R1}" in err


@pytest.mark.skipif(sys.platform != "win32", reason="seul Windows refuse de remplacer un fichier ouvert")
def test_une_poignee_ouverte_sur_le_verrou_pendant_la_liberation(env, capsys, monkeypatch):
    """Une vraie poignée ouverte sur verrou.json (synchronisation du Drive, antivirus) pendant la
    libération : `os.replace` lève PermissionError [WinError 5]."""
    _scored(env, R1, [_post("Ecole Alpha")])
    vrai = verrou.liberer

    def liberer(dossier, *a, **kw):
        with open(os.path.join(dossier, verrou.NOM), encoding="utf-8"):
            return vrai(dossier, *a, **kw)

    monkeypatch.setattr(verrou, "liberer", liberer)
    code = _cmd(env, "finaliser", "--run", R1)
    assert (env.donnees / "historique" / f"DELTA_{R1}.csv").exists()
    assert _verrou(env)["etat"] == "pris"
    assert code == 0
    assert f"verrou liberer --run {R1}" in capsys.readouterr().err


def test_verrou_liberer_refuse_par_le_drive_sort_en_code_2(env, capsys, monkeypatch):
    assert _cmd(env, "verrou", "prendre", "--run", R1) == 0
    _refuser_replace(monkeypatch, "verrou.json")
    code = _cmd(env, "verrou", "liberer", "--run", R1)
    assert _verrou(env)["etat"] == "pris"
    assert _tmp_restants(env) == []
    assert code == 2
    assert "impossible d'écrire le verrou" in capsys.readouterr().err


@pytest.mark.parametrize("commande", [
    ["lots"], ["lots", "--run", R1], ["prepare", "--run", R1], ["finaliser", "--run", R1],
], ids=["lots", "lots-run", "prepare", "finaliser"])
def test_l_option_config_est_refusee_en_mode_partage(env, capsys, commande):
    """En mode partagé, la config est `<donnees>/config.yaml`, celle que contrôle `poste`. Un
    `--config data/config.yaml` resté dans un prompt ferait filtrer avec une blacklist périmée."""
    _lot(env, R1, [_candidat("Ecole Alpha")])
    _scored(env, R1, [_post("Ecole Alpha")])
    code = main(["--config", os.path.join("data", "config.yaml"), "--donnees", str(env.donnees),
                 *commande])
    out, err = capsys.readouterr()
    assert "mot-cle local" not in out  # la config du data/ local n'a pas été lue
    assert not (env.donnees / "verrou.json").exists()
    assert not (env.donnees / "runs" / R1 / "a_scorer.json").exists()
    assert not _classeur(env, R1).exists()
    assert code == 2
    assert "--config" in err and str(env.donnees / "config.yaml") in err


def test_prepare_ignore_un_json_de_travail_dans_le_dossier_du_run(env, capsys):
    """`~$A.json` (fichier de travail d'Office) n'est pas un JSON d'agent : ignoré, mais nommé."""
    _lot(env, R1, [_candidat("Ecole Alpha")])
    (env.donnees / "runs" / R1 / "~$A.json").write_bytes(b"\x04verrou d'Office")
    assert _cmd(env, "prepare", "--run", R1) == 0
    assert "~$A.json" in capsys.readouterr().out
    assert _rapport(env, R1)["fichiers"] == ["A.json"]


def test_le_mode_local_ignore_aussi_un_json_de_travail(env, capsys):
    d = env.depot / "runs" / "run-libre"
    _lot(_ailleurs(env.depot), "run-libre", [_candidat("Ecole Alpha")])
    (d / "~$A.json").write_bytes(b"\x04verrou d'Office")
    assert main(["prepare", "--run", "run-libre"]) == 0
    assert "~$A.json" in capsys.readouterr().out
    assert json.loads((d / "rapport_prepare.json").read_text(encoding="utf-8"))["fichiers"] == [
        "A.json"]


def test_prepare_partage_ignore_un_export_suivi_leads(env, capsys):
    """Lecture stricte : un SUIVI_LEADS.csv posé dans historique/ n'est pas un historique. Lu, ses
    `url_post` écarteraient à tort le post qu'il cite."""
    candidat = _candidat("Ecole Alpha")
    _ecrire_csv(env.donnees / "historique" / "SUIVI_LEADS.csv", COLS_LEADS, [
        {"lead": "Ecole Alpha [x]", "organisation": "Ecole Alpha", "url_post": candidat["url_post"]}])
    _lot(env, R1, [candidat])
    assert _cmd(env, "prepare", "--run", R1) == 0
    assert (_rapport(env, R1)["deja_connus"], _rapport(env, R1)["nouveaux"]) == (0, 1)
    ignores = [ligne for ligne in capsys.readouterr().out.splitlines() if "ignoré(s)" in ligne]
    assert len(ignores) == 1 and "SUIVI_LEADS.csv" in ignores[0]


def test_lots_run_refuse_un_run_deja_finalise_sans_prendre_le_verrou(env, capsys):
    """Même identifiant repris par erreur le soir : refusé AVANT de prendre le verrou et d'ouvrir
    le dossier aux agents (qui écraseraient les JSON bruts du run fini) ; l'identifiant suivant,
    que conseille le message, passe aussitôt."""
    _lot(env, R1, [_candidat("Ecole Alpha")])
    assert _cmd(env, "prepare", "--run", R1) == 0
    _scored(env, R1, [_post("Ecole Alpha")])
    assert _cmd(env, "finaliser", "--run", R1) == 0
    capsys.readouterr()
    code = _cmd(env, "lots", "--run", R1)
    out, err = capsys.readouterr()
    assert _verrou(env)["etat"] == "libre"
    assert "dossier du run" not in out  # rien à coller dans les prompts des agents
    assert code == 2
    assert "déjà finalisé" in err and "JJ-MM-AAAA-n" in err
    assert _cmd(env, "lots", "--run", f"{R1}-2") == 0
    v = _verrou(env)
    assert (v["etat"], v["run"]) == ("pris", f"{R1}-2")
    assert _cmd(env, "verrou", "liberer", "--run", f"{R1}-2") == 0
    assert _cmd(env, "lots", "--run", R1, "--forcer") == 0


def test_lots_run_refuse_un_run_prepare_par_un_autre_poste(env, capsys):
    env.poste("PC-B")
    _lot(env, R1, [_candidat("Ecole Alpha")])
    assert _cmd(env, "prepare", "--run", R1) == 0
    verrou.liberer(str(env.donnees), R1)  # PC-B a fini sa journée sans finaliser
    env.poste("PC-A")
    capsys.readouterr()
    code = _cmd(env, "lots", "--run", R1)
    assert _verrou(env)["etat"] == "libre"
    assert code == 3
    assert "préparé sur le poste PC-B" in capsys.readouterr().err
    assert _cmd(env, "lots", "--run", R1, "--forcer") == 0
    assert (_verrou(env)["etat"], _verrou(env)["poste"]) == ("pris", "PC-A")


def test_poste_run_signale_un_run_deja_finalise(env, capsys, monkeypatch):
    _sans_registre(monkeypatch)
    _ecrire_csv(env.donnees / "historique" / f"DELTA_{R1}.csv", COLS, [_post("Ecole Alpha")])
    assert _cmd(env, "poste", "--run", R1) == 2
    assert any(ligne.startswith("BLOQUANT") and "déjà finalisé" in ligne
               for ligne in capsys.readouterr().out.splitlines())
    assert _cmd(env, "poste", "--run", R2) == 0


def test_une_base_disparue_avant_l_ecriture_bloque_sans_repli_sur_un_classeur_vide(
        env, capsys, monkeypatch):
    """Le Drive applique un renommage (ou l'Explorateur déplace le classeur) entre la lecture de la
    base et l'écriture : jamais de repli sur un classeur vide, qui perdrait labels et leads."""
    _scored(env, R1, [_post("Ecole Alpha"), _post("Ecole Beta", score=4)])
    assert _cmd(env, "finaliser", "--run", R1) == 0
    base = _classeur(env, R1)
    vrai = run_mod._anterieurs

    def anterieurs(*a, **kw):
        lignes = vrai(*a, **kw)
        base.unlink()
        return lignes

    monkeypatch.setattr(run_mod, "_anterieurs", anterieurs)
    _scored(env, R2, [_post("Ecole Gamma")])
    capsys.readouterr()
    code = _cmd(env, "finaliser", "--run", R2)
    assert not _classeur(env, R2).exists()
    assert not (env.donnees / "historique" / f"DELTA_{R2}.csv").exists()
    assert _tmp_restants(env) == []
    assert code == 2
    assert f"prospection_{R1}.xlsx" in capsys.readouterr().err


def test_le_master_migre_passe_avant_les_delta_au_nom_libre(env):
    """Migration sans classeur zéro : MASTER.csv (labels humains) et DELTA des runs locaux au nom
    libre. Le MASTER se lit d'abord : ses labels et son ordre font foi ; un DELTA, exporté avant
    toute saisie, n'a pas de label. En ordre lexical, « DELTA_… » passerait avant « MASTER »."""
    hist = env.donnees / "historique"
    _ecrire_csv(hist / "MASTER.csv", COLS, [
        _post("Ecole Beta", validation="NON", motif="hors zone"), _post("Ecole Alpha")])
    _ecrire_csv(hist / "DELTA_run1.csv", COLS, [_post("Ecole Beta")])
    _ecrire_csv(hist / "DELTA_run2.csv", COLS, [_post("Ecole Gamma")])
    _scored(env, R1, [_post("Ecole Delta")])
    assert _cmd(env, "finaliser", "--run", R1) == 0
    assert [(p["auteur"], p["validation"], p["motif"]) for p in _onglet(_classeur(env, R1))] == [
        ("Ecole Beta", "NON", "hors zone"), ("Ecole Alpha", None, None),
        ("Ecole Gamma", None, None), ("Ecole Delta", None, None)]


def test_le_master_exporte_passe_avant_une_autre_copie_du_master(env):
    """« MASTER - copie.csv » (copie de l'Explorateur, plus ancienne) passerait avant MASTER.csv en
    ordre lexical : c'est MASTER.csv, l'export de finaliser, qui fait foi."""
    hist = env.donnees / "historique"
    _ecrire_csv(hist / "MASTER - copie.csv", COLS, [_post("Ecole Beta")])
    _ecrire_csv(hist / "MASTER.csv", COLS, [_post("Ecole Beta", validation="NON", motif="hors zone")])
    _scored(env, R1, [_post("Ecole Delta")])
    assert _cmd(env, "finaliser", "--run", R1) == 0
    assert [(p["auteur"], p["validation"]) for p in _onglet(_classeur(env, R1))] == [
        ("Ecole Beta", "NON"), ("Ecole Delta", None)]


def test_refinaliser_conserve_aussi_les_labels_de_l_onglet_delta(env):
    """L'onglet DELTA est celui qu'on lit en premier (docs/06) : un label qui y est saisi survit à
    une refinalisation, et passe dans le CSV DELTA réécrit."""
    _scored(env, R1, [_post("Ecole Alpha"), _post("Ecole Beta", score=4)])
    assert _cmd(env, "finaliser", "--run", R1) == 0
    chemin = _classeur(env, R1)
    wb = openpyxl.load_workbook(chemin)
    ws = wb[f"DELTA_{R1}"]
    auteurs = [r[COLS.index("auteur")] for r in ws.iter_rows(min_row=2, values_only=True)]
    ligne = auteurs.index("Ecole Beta") + 2
    ws.cell(row=ligne, column=COLS.index("validation") + 1, value="NON")
    ws.cell(row=ligne, column=COLS.index("motif") + 1, value="hors zone")
    wb.save(chemin)
    assert _cmd(env, "finaliser", "--run", R1) == 0
    delta = {p["auteur"]: (p["validation"], p["motif"]) for p in _onglet(chemin, f"DELTA_{R1}")}
    assert delta == {"Ecole Alpha": (None, None), "Ecole Beta": ("NON", "hors zone")}
    lignes = _lignes_csv(env.donnees / "historique" / f"DELTA_{R1}.csv")
    beta = [r for r in lignes[1:] if r[COLS.index("auteur")] == "Ecole Beta"]
    assert [(r[COLS.index("validation")], r[COLS.index("motif")]) for r in beta] == [
        ("NON", "hors zone")]


def test_finaliser_prend_le_verrou_avant_d_ecrire(env, monkeypatch):
    """Verrou absent : `finaliser` le prend lui-même (commande « finaliser »), avant d'écrire."""
    _scored(env, R1, [_post("Ecole Alpha")])
    vus = []
    vrai = verrou.liberer

    def liberer(dossier, *a, **kw):
        v = json.loads((env.donnees / "verrou.json").read_text(encoding="utf-8"))
        vus.append((v["etat"], v["poste"], v["run"], v["commande"]))
        return vrai(dossier, *a, **kw)

    monkeypatch.setattr(verrou, "liberer", liberer)
    assert _cmd(env, "finaliser", "--run", R1) == 0
    assert vus == [("pris", "PC-A", R1, "finaliser")]


def test_un_verrou_pris_ailleurs_entre_le_controle_et_l_ecriture_arrete_tout(
        env, capsys, monkeypatch):
    """PC-B prend le verrou après le contrôle d'entrée de PC-A : la prise, juste avant les
    écritures, l'arrête (code 3), sans classeur ni DELTA."""
    _scored(env, R1, [_post("Ecole Alpha")])
    env.poste("PC-B")
    verrou.prendre(str(env.donnees), R2, "lots")
    env.poste("PC-A")
    monkeypatch.setattr(verrou, "occupants", lambda *a, **kw: [])  # contrôle d'entrée passé
    code = _cmd(env, "finaliser", "--run", R1)
    assert not _classeur(env, R1).exists()
    assert not (env.donnees / "historique" / f"DELTA_{R1}.csv").exists()
    assert code == 3
    assert "PC-B" in capsys.readouterr().err


def test_les_anterieurs_suivent_l_ordre_des_dates_et_non_l_ordre_lexical(env):
    # en ordre lexical, « DELTA_01-01-2030 » passerait avant « DELTA_25-12-2029 »
    hist = env.donnees / "historique"
    _ecrire_csv(hist / f"DELTA_{R0}.csv", COLS, [_post("Ecole Zeta")])
    _ecrire_csv(hist / f"DELTA_{R1}.csv", COLS, [_post("Ecole Eta")])
    _scored(env, R2, [_post("Ecole Delta")])
    assert _cmd(env, "finaliser", "--run", R2) == 0
    assert [p["auteur"] for p in _onglet(_classeur(env, R2))] == [
        "Ecole Zeta", "Ecole Eta", "Ecole Delta"]


def test_ni_un_delta_posterieur_ni_celui_du_run_ne_sont_reinjectes(env, capsys):
    """Seuls les runs STRICTEMENT antérieurs fournissent des lignes antérieures : ni un run
    postérieur, ni le DELTA du run lui-même (une refinalisation le réécrit)."""
    hist = env.donnees / "historique"
    _ecrire_csv(hist / f"DELTA_{R3}.csv", COLS, [_post("Ecole Future")])
    _ecrire_csv(hist / f"DELTA_{R2}.csv", COLS, [_post("Ecole Retiree du scoring")])
    _scored(env, R2, [_post("Ecole Delta")])
    assert _cmd(env, "finaliser", "--run", R2) == 0
    auteurs = [p["auteur"] for p in _onglet(_classeur(env, R2))]
    assert "Ecole Future" not in auteurs
    assert "Ecole Retiree du scoring" not in auteurs
    assert auteurs == ["Ecole Delta"]
    assert "réinjectées depuis l'historique : 0" in capsys.readouterr().out


@pytest.mark.parametrize("run", ["run-libre", "2030-01-01", "01-01-2030-1"])
def test_finaliser_partage_refuse_un_identifiant_de_run_invalide(env, capsys, run):
    _scored(env, run, [_post("Ecole Alpha")])
    code = _cmd(env, "finaliser", "--run", run)
    assert list((env.donnees / "classeurs").iterdir()) == []
    assert list((env.donnees / "historique").iterdir()) == []
    assert not (env.donnees / "verrou.json").exists()
    assert code == 2
    assert "identifiant de run invalide" in capsys.readouterr().err


def test_finaliser_partage_refuse_sortie(env, capsys):
    """Un run n'écrit que ses propres fichiers : pas de classeur hors de classeurs/."""
    _scored(env, R1, [_post("Ecole Alpha")])
    ailleurs = env.tmp / "ailleurs.xlsx"
    code = _cmd(env, "finaliser", "--run", R1, "--sortie", str(ailleurs))
    assert not ailleurs.exists()
    assert not _classeur(env, R1).exists()
    assert not (env.donnees / "historique" / f"DELTA_{R1}.csv").exists()
    assert code == 2
    assert "--sortie" in capsys.readouterr().err


def test_sans_pyyaml_le_message_de_config_reste_celui_d_avant(tmp_path):
    """Sans PyYAML, la garde de config.py (« PyYAML est requis : pip install … ») parle, en mode
    local comme ailleurs, au lieu d'une trace Python levée par un `import yaml` placé plus tôt."""
    racine = Path(__file__).resolve().parent.parent
    script = ("import runpy, sys; sys.modules['yaml'] = None; "
              "sys.argv = ['prospection.run', 'lots']; "
              "runpy.run_module('prospection.run', run_name='__main__')")
    env = dict(os.environ, PYTHONPATH=str(racine))
    p = subprocess.run([sys.executable, "-c", script], cwd=str(tmp_path), env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=60)
    assert "Traceback" not in p.stderr
    assert "PyYAML est requis" in p.stderr
    assert p.returncode != 0


# --- proprietaire.json et écritures refusées (revue de code) ------------------------------------

def test_un_proprietaire_reenregistre_avec_bom_reste_lisible(env, capsys, monkeypatch):
    """Le Bloc-notes ajoute un BOM : comme le verrou, `proprietaire.json` doit rester lisible."""
    _lot(env, R1, [_candidat("Ecole Alpha")])
    assert _cmd(env, "prepare", "--run", R1) == 0
    f = env.donnees / "runs" / R1 / "proprietaire.json"
    f.write_text(f.read_text(encoding="utf-8"), encoding="utf-8-sig")
    assert _cmd(env, "prepare", "--run", R1) == 0
    res = poste.verifier(str(env.depot), str(env.donnees), run=R1)
    assert [r.niveau for r in res if r.libelle == "run"] == [poste.OK]


def test_proprietaire_ecrit_par_un_temporaire_puis_replace(env, monkeypatch):
    """Écriture atomique : une écriture coupée ne laisse jamais un proprietaire.json tronqué."""
    _lot(env, R1, [_candidat("Ecole Alpha")])
    vrai, cibles = os.replace, []

    def replace(src, dst):
        cibles.append(os.path.basename(str(dst)))
        return vrai(src, dst)

    monkeypatch.setattr(os, "replace", replace)
    assert _cmd(env, "prepare", "--run", R1) == 0
    assert "proprietaire.json" in cibles
    assert _tmp_restants(env) == []


def test_une_autre_erreur_d_ecriture_laisse_le_run_non_finalise(env, capsys, monkeypatch):
    """Drive démonté, disque plein : pas de trace Python, code 2, run non marqué finalisé."""
    _scored(env, R1, [_post("Ecole Alpha")])
    vrai = os.replace

    def replace(src, dst):
        if str(dst).endswith(".xlsx"):
            raise OSError(28, "plus de place sur le disque", str(dst))
        return vrai(src, dst)

    monkeypatch.setattr(os, "replace", replace)
    code = _cmd(env, "finaliser", "--run", R1)
    assert not (env.donnees / "historique" / f"DELTA_{R1}.csv").exists()
    assert _tmp_restants(env) == []
    assert code == 2
    assert "pas marqué finalisé" in capsys.readouterr().err
