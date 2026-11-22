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
