# AGENTS.md — Conventions de travail (prospection-linkedin)

> **Source de vérité unique des conventions de ce dépôt.** Lue nativement par **Codex**, et par **Claude Code** via `CLAUDE.md`, qui l'importe (`@AGENTS.md`).
> **Socle commun** — les §0 à §6 sont le socle partagé par tous les projets : même texte partout, à quelques valeurs près (nom de la branche stable, contenu de la commande `porte`, outils de test), toutes rappelées en §7. La §7 est propre à ce dépôt.
> En cas de conflit entre ce fichier et le code : **s'arrêter et signaler**, ne jamais trancher en silence.

---

## 0. Règles pour les agents (Claude & Codex)

- **AGENTS.md fait foi.** Si une info manque (une règle, un choix d'archi, une valeur métier), **demander — ne jamais inventer**. Toute proposition de comblement est taguée `💡 [proposé — à valider]` dans la doc ou la PR.
- **Un agent = un ticket = une branche à la fois.** Deux agents ne travaillent jamais sur les mêmes fichiers en parallèle.
- **Revue croisée.** Faire relire le diff d'un agent par l'autre (ex. `/code-review` côté Claude) avant d'ouvrir la PR.
- **Commits : l'agent propose, le dev commite.** L'agent rédige le message de commit ; le dev le valide et commite lui-même (GitKraken). **Aucun footer `Co-Authored-By`.**
- **Jamais** de commit direct sur `main`/`dev`, **jamais** de `push`/`merge`/`tag` par un agent sans demande explicite.

### Plusieurs agents en parallèle

- **Le brief écrit le périmètre** : les fichiers que l'agent possède, et ceux auxquels il ne touche pas.
- **Un port de test par copie.** Chaque copie du dépôt (worktree) qui lance les tests fixe son port (`PORT_E2E=3101`, `3102`…). Sinon `reuseExistingServer` fait lire le serveur d'une autre copie, et la porte voit des tests verts sur un code qui n'est pas le sien.
- **Aucun relevé depuis une branche** (nombre de tests, couverture, compteurs) : il est périmé dès la fusion suivante. Les relevés se font une fois, sur `dev`, après la dernière fusion.
- **Fichiers partagés** (CHANGELOG, journal) : ajouter en fin de section ; un conflit se résout en gardant les deux côtés.
- **Numérotation partagée** (tickets, ADR) : le brief annonce le dernier numéro attribué, et on vérifie qu'un ID est libre avant de le poser. En cas de collision, celui qui est déjà fusionné garde son numéro.

---

## 1. Workflow Git

```
main  ← stable, taggué (vX.Y.Z) — PR depuis dev uniquement
  └── dev  ← intégration continue — PR depuis les branches de travail
        ├── feat/<TICKET_ID>      (ex. feat/dedup-url)
        ├── fix/<description>     (ex. fix/date-relative)
        └── chore/<description>   (maintenance, docs, deps, outillage)
```

- Pas de commit direct sur `main` ni `dev` → **tout passe par PR**.
- Une PR = un ticket (ou un lot cohérent de petits tickets liés).
- Branches de travail → `dev` : **squash merge**. `dev → main` : **merge classique** (préserve l'historique). Tag à chaque release.
- **Resync obligatoire après chaque `dev → main`** :
  ```bash
  git checkout dev && git merge --ff-only main && git push origin dev
  ```
  Check qui doit passer : `git log --oneline main..dev` **vide**.
- `wip:` autorisé pour un commit de session interrompue sur une branche de travail (squashé à la PR).

---

## 2. Conventional Commits

Format : `type(scope): description courte`

| Type | Quand l'utiliser |
|---|---|
| `feat` | nouvelle fonctionnalité visible |
| `fix` | correction de bug |
| `test` | ajout/modif de tests sans changement de code prod |
| `refactor` | restructuration sans changement de comportement |
| `chore` | maintenance, deps, scripts, config |
| `docs` | documentation seule |
| `style` | formatage (rien sur la logique) |
| `perf` | optimisation de performance |

Les **scopes** et la **langue des messages** sont propres au projet → voir §7.

---

## 3. Definition of Done (par type de ticket)

Vérifier **tous** les critères du type avant de fermer un ticket.

- **Feature (logique)** — code au pattern existant · **test unitaire** (logique pure) · **test fonctionnel** (action d'état) · **scénario** si la feature entre dans une boucle · **porte verte** (§5) · doc d'état à jour.
- **Feature (UI)** — respecte le design system / tokens · **smoke test de rendu** · pas de régression sur les écrans voisins · accessibilité minimum (`alt`, contraste) · capture si pertinent.
- **Bug fix** — **test de régression écrit AVANT le fix (TDD strict)** : il échoue d'abord, c'est ce qui prouve qu'il garde (§5) · tests verts après · stack trace originale notée dans le commit si pertinent.
- **Refactor** — tests existants verts (zéro changement de comportement) · pas de nouvelle dépendance injustifiée · taille du livrable stable (±5 %).
- **Data / contenu** — **test de structure** (champs requis, IDs uniques, références valides) · nommage cohérent (§7).
- **Docs / process** — markdown lisible · liens internes valides · CHANGELOG mis à jour si impact workflow.

---

## 4. Process de Pull Request

**Branche de travail → `dev`**
1. **Porte verte** (§5) sur la branche.
2. Push la branche (`git push -u origin <branche>`).
3. PR titrée **comme un commit** (`type(scope): …`).
4. Description = lien vers le ticket + changements clés + **comment tester** (étapes) + captures si UI. Une branche apporte ses tests, ou la PR dit pourquoi elle n'en a pas besoin.
5. Revue croisée (`/code-review` côté Claude) + auto-review du diff → **squash merge**.

**`dev → main` (release)**
1. `dev` porte une suite de features cohérente (pas un mix incomplet).
2. **🚦 Gate de release obligatoire** : porte verte sur `dev` + recette E2E du projet (§7) — sine qua non.
3. CHANGELOG : `[Unreleased] → [vX.Y.Z] - AAAA-MM-JJ`.
4. PR `dev → main` → **merge classique** → `git tag vX.Y.Z && git push --tags` → **resync `dev`** (§1).

---

## 5. Tests

**Pyramide** (unitaire → fonctionnel → scénarios → UI) :
- **Unitaire** — logique pure, testable sans mock (à côté du source).
- **Fonctionnel** — actions d'état / API (fichiers dédiés par domaine).
- **Scénarios** — multi-actions qui simulent un parcours réel.
- **UI** — rendu + navigation (smoke test obligatoire sur les flux critiques).

**Couverture visée** : logique pure ~90 % · le reste ≥ 80 % (au moins un test par action ou fonction publique) · UI = smoke + flux critiques.

**La porte — une seule commande avant toute fusion.**
- `porte` enchaîne tout ce qui doit être vert (lint/format, typage s'il y en a, tests, build, e2e) et **s'arrête à la première erreur**. Commande exacte : §7.
- On fusionne **parce que la porte est verte**, pas parce que le travail est fini — même pour un petit changement.
- Si un test échoue, on corrige le code — **jamais le test**, sauf à écrire pourquoi le test avait tort.
- La même commande tourne en local, dans le hook et en CI (§6) : ce qui est vert ici est vert là-bas.

**Une garde ne vaut que cassée au moins une fois.**
- Avant d'affirmer qu'un test protège quelque chose, le faire **échouer exprès** (casser le code ou l'attente), constater le rouge, puis rétablir.
- Obligatoire pour les **assertions négatives** (« n'apparaît pas », `toHaveCount(0)`, `not.toBeVisible()`, `assert x not in …`) : sur un mauvais sélecteur, elles passent à vide.

**E2E — Playwright (standard dès qu'il y a une interface).**
- Les parcours critiques se valident en **Playwright**, en vrai navigateur, et font partie de la porte.
- Tests **déterministes** : attendre les éléments (`await expect(locator)`), jamais de `waitForTimeout` fixe ; sélecteurs par rôle / `data-testid`, pas par classe CSS.
- Port paramétrable (`PORT_E2E`, §0) et serveur forcé en IPv4 (`127.0.0.1`) : sous Windows, `localhost` peut résoudre en `::1`.
- Parcours couverts et état du portage : §7.

---

## 6. Garde-fous (enforcement)

Les règles ci-dessus sont du *contexte* qu'un agent peut ne pas suivre. Pour les rendre **imposées** :

- **Pre-commit** : formatage + lint des fichiers indexés (outil et état : §7).
- **`/code-review`** (Claude Code) avant chaque PR — il lit ce fichier et `CLAUDE.md`.
- `💡 [proposé]` **Hook `PreToolUse`** pour imposer les règles dures : bloquer `git push` sur `main`/`dev`, refuser un nom de branche hors convention, et **exiger la porte verte avant un commit/merge**. (`/hooks` ou `.claude/settings.json`.)
- **CI** : exécute la même commande `porte` à chaque PR (état : §7).

---

## 7. Spécifique à ce dépôt (prospection-linkedin)

> **La seule section à remplacer pour réutiliser ce fichier dans un autre projet.**

- **Objet** : détecter les posts LinkedIn qui constituent une opportunité pour un profil, les scorer (filtres F1–F4, score tracé), produire des messages prêts à envoyer et un pipeline de suivi. Kit réutilisable (licence MIT) : seul `data/config.yaml` est propre à une personne.
- **Dépôt local, sans remote** : initialisé le 17 novembre 2026 comme le prévoit `init-repo.ps1` (tests verts, contrôle anti-fuite avant le premier commit, branches `main` + `dev`). Le commit initial est le seul commit direct sur `main`. `💡 [proposé]` créer le remote — privé ou public, `data/` et `runs/` n'y entrent jamais.
- **Stack** : Python ≥ 3.10, `openpyxl`, `PyYAML` ; tests `pytest` (`requirements-dev.txt`). Scraping par **Claude in Chrome**, dans la session LinkedIn de la personne ; `scripts/harvester.js` (le code injecté dans la page) fait foi.
- **Branche stable** : `main` ; intégration sur `dev`.
- **Porte** : `python -m pytest tests -q`. Chaque test correspond à un bug rencontré en production : un bug corrigé = un test de régression écrit avant le correctif (§3).
- **E2E** : sans objet, il n'y a pas d'interface. **Ne pas automatiser LinkedIn avec Playwright** : il faudrait saisir des identifiants, ce qui est interdit (ci-dessous). Le scraping reste dans la session Chrome de la personne.
- **CI / pre-commit** : aucun pour l'instant. `💡 [proposé]` la porte en GitHub Actions + le contrôle annoncé par le README : la CI échoue si un fichier de `data/` ou `runs/` entre dans l'index.
- **Scopes de commit** : `cles`, `dates`, `config`, `dedup`, `verify`, `workbook`, `run`, `harvester`, `templates`, `docs`, `tests`. Messages **en français**.
- **Données personnelles (non négociable)** : les posts collectés contiennent des noms, des profils et des adresses de **tiers qui n'ont pas consenti** à figurer dans un dépôt. `data/` et `runs/` ne vont **jamais dans git** (seuls `data/README.md`, `data/.gitkeep` et `runs/.gitkeep` y sont). Le dépôt porte la méthode, jamais les données.
- **Une seule source de vérité** : `data/config.yaml` (profil, filtres, grille de scoring, seuils, blacklist, search plan). Les scripts le lisent, les documents l'expliquent — rien n'y est recopié ailleurs : une configuration recopiée finit par diverger.
- **Règles non négociables** (détail dans `README.md`) :
  - **Aucune action publique automatique** — like, commentaire, publication, message, candidature : le système produit des brouillons, l'humain décide.
  - **Jamais de saisie d'identifiants LinkedIn**, sous aucun prétexte.
  - **Jamais de run sans GO explicite.** Un run interrompu reprend au mot-clé suivant, jamais depuis le début.
  - Toujours conserver le **permalien du post**, jamais l'URL de recherche.
  - Déduplication **par contenu et par URL**, systématiquement.
  - **Chaque score est tracé** : le détail du calcul figure en colonne.
  - **Ne jamais inventer** de fait sur la personne, ni promettre une compétence qu'elle n'a pas.
- **Pièges connus** (README) : la date relative (c'est la *dernière* occurrence suivie de `•` qui fait foi) · les liens raccourcis `lnkd.in/p/…`, différents à chaque capture · la fausse parallélisation (les appels d'agents se lancent dans **un seul bloc**) · la configuration recopiée.
- **Docs de référence** : `README.md` · `docs/01`…`10` (processus, config, scoring, recette de scraping, messages, classeur, automatisations, retour d'expérience, démarrer un profil, run récurrent) · `data/README.md` · `CHANGELOG.md`.
