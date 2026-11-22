@AGENTS.md

<!-- CLAUDE.md = pointeur : les conventions et les règles du projet vivent dans AGENTS.md, lu aussi par Codex. Ne pas dupliquer de règle ici — l'ajouter dans AGENTS.md. Ci-dessous, uniquement les notes propres à Claude Code. -->

## Notes Claude Code

- **Commits** : ne jamais committer automatiquement. Proposer le message, laisser le dev committer (GitKraken). **Aucun `Co-Authored-By`** (AGENTS.md §0).
- **Avant d'ouvrir une PR** : `python -m pytest tests -q`, puis `/code-review`.
- **Runs** : le scraping passe par **Claude in Chrome**, dans la session LinkedIn de la personne. Jamais de run sans GO explicite ; les agents de scraping se lancent dans **un seul bloc** d'appels (sinon ils s'exécutent en séquence).
