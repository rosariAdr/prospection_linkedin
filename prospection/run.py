"""Orchestration d'un run, en deux temps.

Le scoring et la rédaction sont faits par des agents entre les deux commandes : ce sont les
seules étapes qui demandent du jugement, tout le reste est déterministe et scripté.

    python -m prospection.run prepare   --run 23-09-2026 --jours 21
    …  (les agents scorent runs/23-09-2026/a_scorer.json → scored_*.json)  …
    python -m prospection.run finaliser --run 23-09-2026

`prepare`   : lit les JSON des agents de scraping, filtre par date, déduplique contre
              l'historique, écrit `a_scorer.json` et le rendement par mot-clé.
`finaliser` : relit les `scored_*.json`, passe les garde-fous, construit le classeur et
              exporte les CSV d'archive.
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import sys
from typing import Any

from . import __version__, config as cfg_mod
from .dedup import Historique, charger_candidats, dedupliquer, rendement_par_mot_cle
from .verify import controler
from .workbook import COLS, COLS_LEADS, construire

RACINE_RUNS = "runs"


def _dossier_run(run: str) -> str:
    d = os.path.join(RACINE_RUNS, run)
    os.makedirs(d, exist_ok=True)
    return d


def _historique(racine: str, run_courant: str) -> Historique:
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
            if os.path.basename(f).startswith(("a_scorer", "scored_", "rapport")):
                continue
            n += h.ajouter_run(f)
    print(f"historique : {n} lignes lues, {len(h.contenus)} clés de contenu, {len(h.auteurs)} auteurs")
    return h


def cmd_prepare(args: argparse.Namespace) -> int:
    cfg = cfg_mod.charger(args.config, racine=args.racine)
    d = _dossier_run(args.run)
    bruts_fichiers = [
        f for f in sorted(glob.glob(os.path.join(d, "*.json")))
        if not os.path.basename(f).startswith(("a_scorer", "scored_", "rapport"))
    ]
    if not bruts_fichiers:
        print(f"Aucun JSON d'agent dans {d}/ — rien à préparer.", file=sys.stderr)
        return 1

    candidats = charger_candidats(bruts_fichiers)
    hist = _historique(args.racine, args.run)
    gardes, rap = dedupliquer(candidats, hist, jours_max=args.jours)

    sortie = os.path.join(d, "a_scorer.json")
    with open(sortie, "w", encoding="utf-8") as fh:
        json.dump(gardes, fh, ensure_ascii=False, indent=1)

    rendement = rendement_par_mot_cle(candidats)
    rapport = {
        "run": args.run, "version": __version__, "fichiers": [os.path.basename(f) for f in bruts_fichiers],
        "jours_max": args.jours, "bruts": rap.bruts, "hors_fenetre": rap.hors_fenetre,
        "deja_connus": rap.deja_connus, "doublons_internes": rap.doublons_internes,
        "nouveaux": rap.nouveaux, "meme_organisation": rap.meme_organisation,
        "rendement_par_mot_cle": rendement,
        "mots_cles_sans_resultat": [k for k in cfg.mots_cles if k not in dict(rendement)],
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
    return 0


def cmd_finaliser(args: argparse.Namespace) -> int:
    cfg = cfg_mod.charger(args.config, racine=args.racine)
    d = _dossier_run(args.run)
    fichiers = sorted(glob.glob(os.path.join(d, "scored_*.json")))
    if not fichiers:
        print(f"Aucun scored_*.json dans {d}/", file=sys.stderr)
        return 1

    posts: list[dict[str, Any]] = []
    for f in fichiers:
        with open(f, encoding="utf-8") as fh:
            x = json.load(fh)
        posts += x["posts"] if isinstance(x, dict) and "posts" in x else x
    print(f"{len(fichiers)} fichier(s) de scoring, {len(posts)} lignes")

    # F4 : filet de sécurité automatique — une organisation blacklistée ne passe jamais
    retires = [p for p in posts if cfg.est_blacklistee(p.get("auteur"))]
    posts = [p for p in posts if not cfg.est_blacklistee(p.get("auteur"))]
    for p in retires:
        print(f"  écarté (F4 blacklist) : {p.get('auteur')} (score {p.get('score_pertinence')})")
    for p in posts:
        if cfg.est_en_observation(p.get("auteur")):
            p["commentaire_scoring"] = (
                "⚠ organisation EN OBSERVATION (F4) : dernière tentative avant blacklist. "
                + str(p.get("commentaire_scoring") or "")
            )

    sous_seuil = [p for p in posts if not cfg.conserver(p.get("score_pertinence") or 0)]
    posts = [p for p in posts if cfg.conserver(p.get("score_pertinence") or 0)]
    if sous_seuil:
        print(f"  {len(sous_seuil)} ligne(s) sous le seuil de conservation, retirées du livrable")

    anomalies = controler(posts, seuil_redaction=cfg.seuil_redaction)
    if anomalies:
        print("GARDE-FOUS EN ÉCHEC :", file=sys.stderr)
        for a in anomalies:
            print("  ⚠ ", a, file=sys.stderr)
        return 2

    sortie = args.sortie or os.path.join("data", f"prospection_{args.run}.xlsx")
    os.makedirs(os.path.dirname(sortie) or ".", exist_ok=True)
    stats = construire(
        posts, run=args.run, sortie=sortie, base=args.base, seuil_redaction=cfg.seuil_redaction
    )
    print(" ".join(f"{k}={v}" for k, v in stats.items()), "->", sortie)

    if not args.sans_csv:
        _exporter_csv(sortie, args.run)
    return 0


def _exporter_csv(chemin_xlsx: str, run: str) -> None:
    """Archive CSV : c'est ce qui permet à une future session de reprendre sans le classeur."""
    import openpyxl

    wb = openpyxl.load_workbook(chemin_xlsx)
    for onglet, nom in (("MASTER", "MASTER"), ("SUIVI_LEADS", "SUIVI_LEADS"),
                        (f"DELTA_{run}", f"DELTA_{run}")):
        if onglet not in wb.sheetnames:
            continue
        cible = os.path.join("data", f"{nom}.csv")
        with open(cible, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            for r in wb[onglet].iter_rows(values_only=True):
                w.writerow(["" if v is None else v for v in r])
        print("  csv ->", cible)


def cmd_lots(args: argparse.Namespace) -> int:
    """Imprime la répartition des mots-clés entre agents, prête à coller dans les prompts."""
    cfg = cfg_mod.charger(args.config, racine=args.racine)
    for i, lot in enumerate(cfg.lots(args.agents)):
        print(f"\n--- lot {chr(65 + i)} ({len(lot)} mots-clés) ---")
        print(" · ".join(lot))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="prospection.run", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--racine", default=".", help="racine du dépôt (défaut : .)")
    ap.add_argument("--config", default=None, help="chemin du YAML de config")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("prepare", help="dédupliquer et préparer le lot à scorer")
    p.add_argument("--run", required=True, help="identifiant du run, ex. 23-09-2026")
    p.add_argument("--jours", type=float, default=None, help="fenêtre en jours (défaut : aucune)")
    p.set_defaults(func=cmd_prepare)

    p = sub.add_parser("finaliser", help="construire le classeur à partir des scored_*.json")
    p.add_argument("--run", required=True)
    p.add_argument("--base", default=None, help="classeur existant à compléter")
    p.add_argument("--sortie", default=None)
    p.add_argument("--sans-csv", action="store_true")
    p.set_defaults(func=cmd_finaliser)

    p = sub.add_parser("lots", help="répartir les mots-clés entre agents")
    p.add_argument("--agents", type=int, default=3)
    p.set_defaults(func=cmd_lots)

    args = ap.parse_args(argv)
    if args.racine != ".":
        os.chdir(args.racine)
        args.racine = "."
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
