# 10 — Relancer un run (profil déjà en place)
> `09-prompt-demarrage.md` sert à **amorcer un nouveau profil**. Ce document-ci est le mode
> opératoire d'un run de routine, avec les commandes exactes.

## 0. Pré-requis, à vérifier avant de lancer quoi que ce soit

- [ ] **GO explicite** de la personne. Un run ne démarre jamais sans.
- [ ] `data/config.yaml` présent et à jour (blacklist relue).
- [ ] Ordinateur allumé, Chrome ouvert, extension connectée, session LinkedIn active.
- [ ] `pip install -r requirements.txt`.

## 1. Cadrer

Trois décisions changent le livrable — les poser, ne pas les supposer :

| Décision | Options |
|---|---|
| Fenêtre | `past-week` (7 j) · `past-month` + coupure (il n'existe pas de filtre « 2 semaines ») |
| Mots-clés | tous · noyau prioritaire seul · liste resserrée sur un besoin précis |
| Annonces non datées | conservées « échéance à qualifier » (défaut) · pénalisées · exclues |

## 2. Répartir et scraper

```bash
python -m prospection.run lots --agents 3
```

Trois agents, **dans un seul bloc d'appels** — un appel par message produit une exécution
séquentielle et triple la durée. Chaque agent : son propre onglet, la recette
`docs/04-recette-scraping.md`, et son JSON écrit **au fur et à mesure** dans
`runs/<date>/<LOT>.json` (schéma au §12 de la recette).

Pendant le run : une tâche par lot, un point de progression tous les 5 mots-clés, et une
alerte immédiate si une déconnexion dépasse 5 minutes (§13 de la recette).

## 3. Préparer le lot à scorer

```bash
python -m prospection.run prepare --run 24-09-2026 --jours 21
```

Produit `runs/<date>/a_scorer.json` (dédupliqué, fenêtré) et `rapport_prepare.json` (rendement
par mot-clé, mots-clés sans résultat, organisations déjà en suivi).

Le rendement par mot-clé n'est pas décoratif : c'est lui qui sert à recomposer le noyau
prioritaire et à retirer les mots-clés stériles de `search_plan.lots`.

## 4. Scorer et rédiger

Découper `a_scorer.json` en lots de 50 environ, un agent par lot (aucune limite d'agents
parallèles hors LinkedIn). Chaque agent lit `docs/03-scoring-et-regles.md`,
`docs/05-messages.md` et `data/config.yaml`, puis écrit `runs/<date>/scored_<LOT>.json`.

**Champs attendus en sortie** — la liste exacte est `prospection/workbook.py::COLS`. Deux
pièges récurrents :

- **`cle_contenu` doit être recopiée telle quelle** depuis `a_scorer.json`. C'est l'empreinte du
  texte brut ; sans elle, la ligne sera invisible à la déduplication du run suivant. Le build
  vous avertit si elle manque.
- **Seuls les posts conservés** figurent dans la sortie. Les exclus n'y sont pas.

## 5. Finaliser

```bash
python -m prospection.run finaliser --run 24-09-2026 \
    --base data/prospection_precedent.xlsx
```

Cette commande applique un **filet de sécurité automatique** avant tout :

1. les organisations blacklistées (`blacklist.organisations`) sont écartées, quel que soit leur
   score, et la ligne écartée est imprimée ;
2. les organisations en observation sont conservées mais préfixées d'un avertissement ;
3. les lignes sous `seuil_conservation` sortent du livrable ;
4. les garde-fous tournent — longueurs, salutations, coordonnées en commentaire public,
   cohérence mail, cohérence seuil, une seule candidature par organisation. **En cas d'échec,
   rien n'est écrit** et le détail s'affiche.

Puis le classeur est construit (MASTER + `DELTA_<date>` + SUIVI_LEADS) et les CSV exportés dans
`data/` — ce sont eux que relit la déduplication du run suivant.

## 6. Livrer

- Le **delta** se lit en deux minutes, le **MASTER** est la référence.
- Résumer : couverture (n/n mots-clés), entonnoir (bruts → uniques → conservés → leads), le top
  du lot, et **les arbitrages tranchés** — un doublon d'organisation, une exclusion discutable,
  une organisation en observation retenue.
- Dire ce qui n'a pas marché : mots-clés stériles, incidents, limites connues.

## Si Chrome se déconnecte en cours de route

Attendre 45-90 s, `list_connected_browsers` → `select_browser` → `tabs_context_mcp`, reprendre
**au mot-clé suivant**. Les JSON déjà écrits sont conservés, `prepare` les relira. Si l'absence
dure : prévenir, programmer une re-vérification avec un **nombre de tentatives borné**, et ne
jamais boucler en silence.
