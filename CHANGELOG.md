# Journal des modifications

Format : [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/).

## [Unreleased]

### Corrigé
- `finaliser` refuse une ligne conservée sans permalien (`url_post` vide ou URL de recherche) et un
  score positif sans `commentaire_scoring` (PL-06). L'avertissement « en observation » (F4) est
  désormais ajouté au commentaire après les garde-fous : il ne masque plus un score non tracé.
- Le garde-fou téléphone des commentaires publics repère aussi le format international (`+33`,
  `0033`) (PL-18).
- `prepare` lit `mots_cles_non_traites` : il signale un run incomplet, et un mot-clé jamais cherché
  ne passe plus pour « sans résultat » (PL-17). Les mots-clés se comparent sans tenir compte de la
  casse ni des accents.
- `docs/03` situait la blacklist dans `data/blacklist.md`, alors que le code la lit dans
  `data/config.yaml` (PL-05).
- Le README et la section [1.0.0] annonçaient une intégration continue anti-fuite qui n'a jamais
  existé (PL-08).
- `AGENTS.md` §7 décrit l'état réel : initialisation, source de vérité, règles contrôlées par le
  code ou procédurales (PL-03, PL-04, PL-06).
- Les clés de déduplication (`cle_contenu`, `cle_secours`) et la clé `__doneKeys` du harvester
  portent sur le corps du post seul, coupé après le dernier horodatage : un post recapturé une
  semaine plus tard (date relative et lien `lnkd.in` changés) est reconnu, et le second post d'un
  même auteur n'est plus sauté en silence (PL-01, PL-15). Les clés déjà enregistrées dans un MASTER
  ou un CSV ne correspondent plus ; seules celles tirées des JSON bruts de `runs/` sont
  recalculées (voir `docs/04`).
- `scripts/harvester.js` ne se termine plus par des restes de bloc Markdown, qui le rendaient
  invalide en JavaScript.

### Ajouté
- `tests/test_run.py` : tests fonctionnels de `prepare` et `finaliser` sur un faux dépôt temporaire
  (PL-10).
- Intégration continue GitHub Actions (`.github/workflows/porte.yml`) : la porte tourne à chaque PR
  vers `dev` ou `main` et à chaque push sur ces branches, sous Python 3.10 et 3.13.
  `tests/test_anti_fuite.py` la fait échouer si une donnée personnelle (`data/`, `runs/`, classeur,
  export) ou une copie de travail `.claude/` est suivie par git (PL-08).
- **Données partagées entre plusieurs PC** (`prospection/emplacements.py`) : `--donnees <dossier>`
  (avant ou après la sous-commande) ou la variable `PROSPECTION_DONNEES` désignent un dossier hors
  du dépôt, synchronisé par un Drive. Chaque commande annonce son mode en première ligne ; sans
  l'un ni l'autre, le mode local est inchangé. Un dossier situé dans le dépôt ou dans un arbre git
  est refusé. Mode opératoire : `docs/10-run-recurrent.md` §7.
- `initialiser-donnees --vers <dossier>` crée le dossier partagé (`config.yaml`, `historique/`,
  `runs/`, `classeurs/`, marqueur) et y copie la config, les CSV d'historique, les JSON des runs et
  le dernier classeur, sans rien écraser. Il dépose `data/MIGRE_VERS_PARTAGE.txt`, qui arrête
  ensuite le mode local, et affiche la commande qui pose la variable, sans la poser (toute
  apostrophe du chemin doublée, typographique comprise). Un lecteur non monté est annoncé comme
  tel.
- `poste [--run R]` contrôle un PC avant un run (Python, dépendances, dossier de données, variable
  sous Windows, config, historique, copies en conflit, verrou, run visé, classeur, état du code) :
  une ligne `OK`, `AVERTISSEMENT` ou `BLOQUANT` par contrôle, code 2 s'il y a un bloquant. Elle ne
  nomme jamais le profil, ni un fichier de config autre que `config.yaml`.
- Verrou de run sur le dossier partagé (`prospection/verrou.py`) : pris par `lots --run`,
  rafraîchi par `prepare` et `finaliser`, libéré par `finaliser` ; occupé, code 3. `verrou
  statut|prendre|liberer` pour un run abandonné. Il couvre l'oubli, pas la course à la seconde.
  Une libération refusée par le Drive laisse le run finalisé (code 0) et donne la commande
  `verrou liberer --run R` à relancer.
- Mode partagé : identifiant de run strict (`JJ-MM-AAAA`, ou `JJ-MM-AAAA-n` avec n ≥ 2) ; un run
  n'écrit que ses propres fichiers (`runs/<run>/`, `historique/DELTA_<run>.csv`,
  `classeurs/prospection_<run>.xlsx`), par un temporaire puis un remplacement, le DELTA en
  dernier. `finaliser` calcule sa base (`--base` facultatif) et le MASTER (base, plus lignes
  d'historique manquantes filtrées par F4, plus run courant), et affiche le nombre de lignes
  réinjectées, 0 en régime normal. Un fichier illisible, une copie en conflit dans `historique/`,
  dans `classeurs/` ou sur la config, un classeur postérieur ou ouvert dans Excel, une base
  disparue avant l'écriture bloquent (code 2). Refinaliser garde les labels du MASTER, de
  SUIVI_LEADS et de l'onglet DELTA du run. La config est `config.yaml` du dossier de données :
  `--config` est refusé.
- `lots --run R` crée le dossier du run et affiche, comme `prepare`, les chemins absolus du dossier
  du run et de la config, à coller dans les prompts des agents. En mode partagé, comme `prepare`,
  il refuse un run déjà finalisé (code 2) ou préparé sur un autre poste (code 3), sauf `--forcer`.
- Les CSV d'historique se lisent en `utf-8-sig` : un BOM ajouté par Excel ne masque plus la
  première colonne. Les fichiers de travail `~$…` et `….tmp` ne sont jamais lus.
- `tests/test_anti_fuite.py` et `.gitignore` refusent aussi les fichiers d'un dossier partagé
  (segments `runs`, `historique`, `classeurs`, `verrou*.json`, marqueurs), toute config
  `config*.yaml` sauf un gabarit `templates/<nom>.example.yaml`, et les PDF. `tests/conftest.py` retire `PROSPECTION_DONNEES` de l'environnement de
  chaque test. Nouveaux tests : emplacements, verrou, poste, migration, lignes d'historique
  antérieures, et un scénario sur plusieurs PC, en données fictives dans un dossier temporaire.

## [1.0.0] — 2026-09-24

Première version versionnée. Le dépôt passe d'un ensemble de documents à un process exécutable.

### Corrigé
- **La déduplication contre l'historique ne fonctionnait pas.** La clé de contenu était calculée
  sur `post_extrait`, qui est une reformulation écrite au scoring et non le texte brut du post :
  aucune correspondance n'était donc possible. Une colonne `cle_contenu` (empreinte du texte brut,
  posée au harvest) est désormais transportée jusqu'au classeur.
- **Le MASTER dédupliquait par auteur seul.** Une école publiant une seconde annonce n'entrait
  jamais, et deux homonymes fusionnaient. La déduplication suit maintenant
  `cle_contenu` → `url_post`, l'auteur ne servant plus qu'à signaler un doublon d'organisation.
- **Le parseur de date relative n'existait qu'en JavaScript** et était réécrit à la main à chaque
  run. Il est désormais dans `prospection/dates.py`, avec le test du piège « 3 ans d'expérience ».
- `08-retour-experience.md` : tableau à en-tête de 3 colonnes et lignes de 2.

### Ajouté
- `prospection/` : package Python (clés, dates, config, dédup, garde-fous, classeur, orchestration).
- `python -m prospection.run prepare|finaliser|lots` — l'enchaînement complet est scripté ; seuls
  le scoring et la rédaction restent confiés à des agents.
- **Filet de sécurité F4** : `finaliser` écarte automatiquement toute organisation blacklistée,
  quel que soit son score. C'est ce qui manquait le 03/09/2026, quand une organisation blacklistée
  est ressortie à 12 points.
- `tests/` : 45 tests couvrant les clés, les dates, la déduplication, les garde-fous et le classeur.
- Garde-fous supplémentaires : corps de mail rédigé sans adresse dans le post, messages rédigés
  sous le seuil (ou absents au-dessus), deuxième candidature pour une même organisation.
- `docs/10-run-recurrent.md` : mode opératoire d'un run de routine, avec les commandes.
- `data/README.md`, `requirements.txt`, `LICENSE`.

### Modifié
- **Source unique de vérité** : la grille de scoring, les seuils, la blacklist et le search plan
  vivent dans `data/config.yaml`. Les documents expliquent, ils ne recopient plus.
- Le harvester n'est plus dupliqué entre `scripts/harvester.js` et la recette : le fichier fait foi.
- `.gitignore` inversé : **tout `data/` et `runs/` est exclu**. Le dépôt porte la méthode, jamais
  les données — les posts collectés contiennent des noms et des adresses de personnes tierces.
