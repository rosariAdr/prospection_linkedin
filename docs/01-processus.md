# 01 — Le processus en 5 phases

```
PHASE 0  Cadrage                    → ⏸ CHECKPOINT 1 : critères, blacklist, GO explicite
PHASE 1  POC (4 mots-clés)          → livrable Excel, colonnes validation/motif VIDES
         ⏸ CHECKPOINT 2             : labellisation OUI/NON + motif sur 20-25 lignes
PHASE 2  Induction des règles       → ⏸ mini-checkpoint : validation des règles déduites
PHASE 3  Run complet                → scraping + scoring + rédaction des messages
PHASE 4  Consolidation              → MASTER, SUIVI_LEADS, DELTA_<date>
PHASE 5  Automatisation récurrente  → veille périodique + découverte mensuelle
```

**Règle d'or : ne jamais sauter le CHECKPOINT 2.** Sans labels humains, le système reste un filtre
par mots-clés — c'est-à-dire un générateur de bruit.

---

## PHASE 0 — Cadrage ⏸ CHECKPOINT 1

Présenter la grille de scoring initiale, le search plan et les livrables. Puis demander :
1. les **critères d'acceptation** définitifs ;
2. la **blacklist initiale** ;
3. la **cadence** souhaitée ;
4. la **disponibilité de la machine** (le scraping passe par le Chrome de la personne).

Questions prioritaires, parce qu'elles changent tout le reste :
- Quel est le critère qui **disqualifie immédiatement** une opportunité, même parfaite ?
- Le **distanciel** change-t-il la donne géographique ?
- Y a-t-il des **organisations déjà approchées** (à retenter ? à exclure ?) ?

**Attendre un GO explicite avant toute navigation.**

## PHASE 1 — POC

**4 mots-clés seulement**, un par pilier du profil. Objectif : ~70-80 posts scorés en ~30 min.
Livrable : un classeur, onglet `POC`, trié par score, avec deux colonnes vides `validation`
(menu OUI/NON) et `motif` (texte libre).

> **Conserver toutes les lignes, y compris scorées 0.** Les exclusions sont aussi instructives que
> les inclusions pour l'induction.

## ⏸ CHECKPOINT 2 — Labellisation humaine

Au minimum **20 lignes** annotées : toutes celles au-dessus du seuil, plus quelques-unes à 0.
Ce checkpoint est **non bloquant dans le temps** : la personne le fait quand elle veut, le système
peut tourner entre-temps avec la grille initiale.

## PHASE 2 — Induction

Méthode complète dans `03-scoring-et-regles.md`. Produire : une grille de règles explicites, un
scoring ajusté, et les conséquences sur le search plan. Présenter pour validation, puis appliquer.

## PHASE 3 — Run complet

Tous les mots-clés, par lots, avec le scoring à jour. 2 à 3 sous-agents parallèles, un onglet
chacun, **appels émis dans un seul bloc**. Pause entre les lots. Reprenable au mot-clé suivant.

## PHASE 4 — Consolidation

| Onglet | Contenu |
|---|---|
| `MASTER` | Union dédupliquée, triée par score, colonnes validation/motif ouvertes |
| `DELTA_<date>` | Uniquement les nouveautés du run — ce qu'on lit en priorité |
| `SUIVI_LEADS` | Opportunités retenues + leurs 5 textes + `statut_lead` |
| `REGLES` / `GRILLE` | Règles appliquées et mode d'emploi de la labellisation |
| `BLACKLIST` | Exclusions et organisations en observation |

## PHASE 5 — Automatisation

Voir `07-automatisations.md` : veille périodique (rotation de mots-clés) + découverte mensuelle
(vocabulaire + ré-apprentissage des labels).

---

## Invariants, quel que soit le profil

1. **Aucune action publique automatique.** Le système produit des brouillons, l'humain décide.
2. **Toujours conserver le permalien du post**, jamais l'URL de recherche.
3. **Déduplication par URL *et* par contenu** (voir `04-recette-scraping.md` §7).
4. **Traçabilité du score** : chaque ligne porte le détail du calcul.
5. **Reprenabilité** : un run interrompu reprend au mot-clé suivant, jamais de zéro.
6. **Ne jamais inventer de faits** sur la personne dans les messages.
7. **Jamais de run sans GO explicite.**
