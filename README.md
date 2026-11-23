# Prospection LinkedIn assistée

Détecter en continu les posts LinkedIn qui constituent une **opportunité pour un profil donné**,
les scorer selon des critères qui reflètent le jugement réel de la personne, et produire des
messages prêts à envoyer plus un pipeline de suivi.

Conçu et rodé entre août et septembre 2026 sur un cas réel — recherche de missions
d'enseignement pour un profil Data Analyst : ~1 200 posts consultés, 6 runs complets, 80 leads
produits. Un seul fichier est spécifique à une personne ; tout le reste est réutilisable tel quel.

```
Recherche LinkedIn par mots-clés
        │  scraping via Claude in Chrome — DOM virtualisé, interception du presse-papiers
        ▼
Posts bruts  ──►  runs/<date>/<LOT>.json
        │  python -m prospection.run prepare   (fenêtre temporelle + dédup contenu)
        ▼
a_scorer.json  +  rendement par mot-clé
        │  agents : filtres F1-F4, score tracé, 5 textes par opportunité retenue
        ▼
scored_*.json
        │  python -m prospection.run finaliser (filet F4, garde-fous bloquants, classeur)
        ▼
MASTER · DELTA_<date> · SUIVI_LEADS      ──►  colonnes validation / motif
        └──────────── les labels humains ré-induisent les règles du run suivant ───────────┘
```

Le point clé n'est pas le scraping : c'est la **boucle**. Un scoring défini a priori se trompe
toujours ; ce sont les labels humains qui le corrigent. Sur le cas réel, 4 des 9 anomalies
révélées par la première session de labellisation étaient des **OUI à score faible** — dont deux
ont créé une catégorie entière (« vivier ») qui représente aujourd'hui un lead sur cinq.

---

## Mise en route

```bash
pip install -r requirements.txt
cp templates/config-profil.example.yaml data/config.yaml   # puis remplir
python -m pytest tests -q
```

`data/config.yaml` est la **source unique de vérité** : profil, filtres, grille de scoring,
seuils, blacklist, search plan. Les scripts le lisent, les documents l'expliquent — rien n'y est
recopié ailleurs.

## Un run

```bash
python -m prospection.run lots --agents 3          # répartir les mots-clés
#   … les agents scrapent vers runs/<date>/<LOT>.json …
python -m prospection.run prepare   --run 24-09-2026 --jours 21
#   … les agents scorent a_scorer.json vers runs/<date>/scored_*.json …
python -m prospection.run finaliser --run 24-09-2026 --base data/prospection_precedent.xlsx
```

Mode opératoire détaillé : [`docs/10-run-recurrent.md`](docs/10-run-recurrent.md).

## Structure

```
prospection/        le package : clés, dates, config, dédup, garde-fous, classeur, orchestration
  cles.py           empreintes de déduplication (contenu, secours, URL)
  dates.py          lecture des dates relatives LinkedIn + fenêtrage
  config.py         chargement et validation de data/config.yaml
  dedup.py          déduplication d'un run contre l'historique
  verify.py         garde-fous bloquants avant livraison
  workbook.py       MASTER / DELTA / SUIVI_LEADS
  run.py            prepare · finaliser · lots
scripts/harvester.js  le code injecté dans la page LinkedIn — fait foi
docs/                 01 processus · 02 config · 03 scoring et induction des règles
                      04 recette de scraping · 05 messages · 06 classeur · 07 automatisations
                      08 retour d'expérience chiffré · 09 démarrer un profil · 10 run récurrent
templates/            le gabarit de configuration, anonymisé
tests/                45 tests — chacun correspond à un bug rencontré en production
data/  runs/          données réelles, non versionnées (voir data/README.md)
```

## Pré-requis

- **Claude Cowork** (desktop) avec l'extension **Claude in Chrome** connectée.
- Un **compte LinkedIn connecté** dans ce Chrome : le scraping passe par la session de la personne.
- L'ordinateur allumé et Chrome ouvert pendant les runs (~1 h pour 45 mots-clés).
- Python 3.10+.
- Aucun compte Premium, aucune API, aucune clé.

## Données personnelles

Les posts collectés contiennent des noms, des profils et des adresses de **personnes tierces** qui
n'ont pas consenti à figurer dans un dépôt. `data/` et `runs/` sont donc **entièrement exclus de
git** par le `.gitignore`. Un `git add -f` passerait le `.gitignore` : la porte le rattrape
(`tests/test_anti_fuite.py`, lancé en local et en intégration continue à chaque PR), mais aucun
hook pre-commit ne l'empêche encore au moment du commit. `git ls-files data runs` ne doit lister
que `data/README.md`, `data/.gitkeep` et `runs/.gitkeep`. Le dépôt porte la méthode, jamais les
données.

## Règles non négociables

- **Aucune action publique automatique** : pas de like, commentaire, publication, message ou
  candidature envoyés sans validation. Le système produit des brouillons, l'humain décide.
- **Jamais de saisie d'identifiants LinkedIn**, sous aucun prétexte.
- **Jamais de run sans GO explicite.**
- Toujours conserver le permalien du post, jamais l'URL de recherche.
- Déduplication par contenu **et** par URL, systématiquement.
- Chaque score est tracé : le détail du calcul figure en colonne.
- Ne jamais inventer de fait sur la personne, ni promettre une compétence qu'elle n'a pas.
- Un run interrompu reprend au mot-clé suivant, jamais depuis le début.

## Les quatre pièges qui coûtent le plus cher

1. **La date relative.** Un `match` naïf attrape « 3 ans d'expérience » dans le corps du post et
   écarte des annonces fraîches. L'horodatage est toujours suivi d'un `•`, et c'est la *dernière*
   occurrence qui fait foi.
2. **Les liens raccourcis.** Depuis août 2026, « Copier le lien » renvoie un `lnkd.in/p/XXXX`
   différent à chaque capture : la déduplication par URL détecte 0 doublon là où la déduplication
   par contenu en trouve 45 sur 226.
3. **La fausse parallélisation.** Trois agents lancés dans trois messages successifs s'exécutent
   en séquence. Les appels doivent être émis dans **un seul bloc**.
4. **La configuration recopiée.** Une grille de scoring présente dans trois fichiers finit par
   diverger, et une règle oubliée d'un côté ne s'applique plus nulle part.

## Licence

MIT — voir [LICENSE](LICENSE). Le kit est réutilisable pour n'importe quel profil et n'importe
quel type d'opportunité ; seul `data/config.yaml` change.
