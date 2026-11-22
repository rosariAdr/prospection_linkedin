# Journal des modifications

Format : [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/).

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
- `data/README.md`, `requirements.txt`, `LICENSE`, intégration continue GitHub Actions.

### Modifié
- **Source unique de vérité** : la grille de scoring, les seuils, la blacklist et le search plan
  vivent dans `data/config.yaml`. Les documents expliquent, ils ne recopient plus.
- Le harvester n'est plus dupliqué entre `scripts/harvester.js` et la recette : le fichier fait foi.
- `.gitignore` inversé : **tout `data/` et `runs/` est exclu**. Le dépôt porte la méthode, jamais
  les données — les posts collectés contiennent des noms et des adresses de personnes tierces.
