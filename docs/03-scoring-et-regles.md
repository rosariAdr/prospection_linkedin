# 03 — Scoring et induction des règles intrinsèques
> Le cœur méthodologique. Un scoring défini a priori se trompe toujours ; c'est l'induction à
> partir de labels humains qui fait passer le système de « filtre à mots-clés » à « assistant qui
> applique mes critères ».

## 1. Architecture en deux couches

```
COUCHE 1 — FILTRES D'EXCLUSION (binaires, hors score)
  → si déclenché : la ligne ne figure PAS dans le livrable, quel que soit le score.

COUCHE 2 — SCORE ADDITIF
  → détermine la conservation et le déclenchement de la rédaction des messages.
```

Cette séparation est essentielle : un deal-breaker n'est **pas** un malus, sinon un post
« parfait sauf ce détail » finit quand même en haut de liste.

## 2. Les filtres (version Adrian — à recalibrer par profil)

**F1 — L'offre doit m'être adressée et être actionnable**
- annonce encore ouverte (ni « trouvé », ni « clôturé », ni « pourvu ») ;
- cherche un formateur / intervenant pédagogique / enseignant / vacataire — **pas** une partie
  prenante de chantier, de mission ou d'événement (BTP, ferroviaire, industrie, logistique, RH,
  événementiel). ⚠️ Piège le plus fréquent : le mot « intervenant » dans un autre secteur ;
- s'adresse **aux formateurs**, pas aux écoles : une agence qui propose ses formateurs aux
  établissements est un concurrent → exclusion. À distinguer du vivier (V1) ;
- joignable directement, sans inscription obligatoire sur une plateforme d'intermédiation ;
- une personne qui **cherche** un poste (CV, recherche d'alternance) → exclusion ;
- ce n'est pas une annonce (autopromo, témoignage, certification perso, article, pub) → exclusion.

**F2 — L'intervention doit être dans mon périmètre**
- domaines acceptés / refusés : voir `COMPETENCES` et `COMPETENCES_EXCLUES` dans la config ;
- public accepté : BAC+3 à BAC+5, formation professionnelle en entreprise ;
- public refusé : CAP, BP, BUT, DUT, scolaire primaire-secondaire, diplôme d'enseignement local
  exigé (CAPES, brevet québécois…). BTS accepté mais pénalisé (−3).

**F3 — Les conditions doivent être viables** (rémunération et distance se jugent **ensemble**)

| Situation | Taux minimum |
|---|---|
| Zone cible, ou distanciel | ≥ 45 €/h HT |
| Hors zone, présentiel obligatoire | ≥ 65 €/h HT (ou ≥ 450 €/j) |
| Hors pays | jamais en présentiel, même bien payé |

- **Taux non annoncé : pas d'exclusion.** Marquer `à déterminer` et poser la question dans le message.
- TTC ramené en HT (÷ 1,2) avant comparaison.
- Le distanciel ne rattrape pas un diplôme à obligation de présentiel.

**F4 — Historique** : blacklist + organisations « en observation » (une seconde chance avant
exclusion). La liste vit dans la config, section `blacklist` (`organisations` et
`en_observation`), et nulle part ailleurs. La config est `data/config.yaml` en mode local, le
`config.yaml` du dossier de données en mode partagé ; `lots --run` et `prepare` affichent son
chemin absolu (`10-run-recurrent.md` §7). C'est là que `prospection.run finaliser` la lit pour
écarter d'office une organisation blacklistée. Elle **doit être relue à chaque run** : une ligne
oubliée ici, et une organisation écartée ressort en tête du classement au run suivant. Un ancien
fichier `data/blacklist.md` n'est lu par aucun script : une organisation ajoutée seulement là
n'est jamais écartée.
⚠️ Le filet automatique compare la liste au champ `auteur` du post. Une organisation dont la
personne qui recrute publie sous son propre nom n'est donc écartée qu'au scoring.

## 3. La grille de score

> **La grille chiffrée vit dans la config, section `scoring`, et nulle part ailleurs.**
> Les scripts la lisent, ce document l'explique. Avant la v1.0 elle était recopiée dans trois
> fichiers : la dérive a fini par faire disparaître la blacklist des règles réellement
> appliquées, et une organisation blacklistée est ressortie en tête de classement (03/09/2026).

Ce que chaque critère cherche à capturer :

| Famille | Question posée | Poids typique |
|---|---|---|
| **Intention** | Le post cherche-t-il vraiment quelqu'un ? | le plus fort (+4) |
| **Adéquation métier** | Est-ce mon cœur de compétence ? | +3 |
| **Géographie** | Est-ce accessible ? zone / distanciel, cumulables | +2 (+2) |
| **Segment** | Le niveau du public correspond-il ? | +2 / +1, et un **malus** pour le niveau accepté à contrecœur |
| **Économie** | La rémunération est-elle annoncée et correcte ? | +2 |
| **Nature** | Vivier à intégrer ? Formation en entreprise ? | +2 chacun |
| **Actionnabilité** | Puis-je contacter quelqu'un directement ? | +1 |
| **Ampleur** | Ponctuel ou récurrent ? | +1 |

**Deux seuils**, eux aussi dans la config :
- `seuil_conservation` — en dessous, la ligne **ne figure pas** dans le livrable ;
- `seuil_redaction` — **strictement supérieur** : un score égal au seuil ne déclenche pas la
  rédaction des cinq textes.

> Les valeurs Adrian (3 et 5) ont été abaissées depuis 5 et 8, sur deux retours successifs :
> « beaucoup de messages manquent » (le seuil de 8 laissait la moitié des lignes retenues non
> actionnables) puis « les lignes sous 3 me font perdre du temps » (elles sortent du fichier).

**Un critère peut dépendre du moment de l'année.** Le malus BTS est passé de 0 à −3 une fois
l'emploi du temps mieux rempli. Relire la section `scoring` à chaque run complet.

## 4. Les trois types d'opportunité

Le **type** conditionne le message, pas seulement le score.

| Type | Définition | Traitement |
|---|---|---|
| `annonce directe` | Un besoin daté et identifié | Candidature ciblée |
| `réseau / vivier` | Une structure constitue un pool d'experts | Demande de référencement (message différent, pas d'urgence) |
| `à qualifier` | Opportunité conditionnée (distanciel, périmètre) | Le message **pose la question** avant de candidater |

## 5. Méthode d'induction (le checkpoint qui compte)

### Étape 1 — Trier les labels en 4 quadrants

|  | Score élevé | Score faible |
|---|---|---|
| **OUI** | ✅ le scoring fonctionne | 🔴 **critère sous-pondéré ou type manquant** |
| **NON** | 🔴 **deal-breaker caché** | ✅ le scoring fonctionne |

Les deux cases rouges sont les seules qui portent de l'information.

### Étape 2 — Interroger chaque anomalie

**NON à score élevé** → qu'est-ce qui disqualifie alors que tous les critères formels sont réunis ?
Presque toujours : une compétence exigée hors périmètre, une contrainte pratique, un historique
relationnel, ou un désintérêt pour le segment.

**OUI à score faible** → quel critère implicite rend l'opportunité acceptable ? Presque toujours :
une condition que la personne pose elle-même (« si c'est en ligne » → créer un **type**, pas monter
le score), ou une catégorie non modélisée (vivier, intermédiaire).

### Étape 3 — Formuler la règle
```
R<n> — <nom court> (<FILTRE | AJUSTEMENT DE SCORE | NOUVEAU TYPE>)
Test    : <condition vérifiable sur le texte du post>
Action  : <exclusion | +/-N points | affectation d'un type>
Origine : <label(s) ayant produit la règle>
```

### Étape 4 — Répercuter sur le search plan
Une règle de rejet systématique sur un thème ⇒ **retirer le mot-clé correspondant**. Gain double :
moins de bruit, moins de temps de scraping.

### Étape 5 — Consolider périodiquement
Le cas réel est passé de **15 règles (R1-R15) à 6** (F1-F4 + V1-V2) sans rien perdre : beaucoup de
règles induites sont des cas particuliers d'un même principe. Une grille de 15 règles n'est ni
mémorisable ni vérifiable ; une grille de 6 l'est.

## 6. Calibrage

- **Conservation** : le score que doit atteindre un post pour valoir la peine d'être lu.
- **Rédaction** : le score au-delà duquel on écrit les messages.
- Si des posts labellisés OUI tombent sous le seuil, c'est **un critère qui manque**, pas un seuil
  à baisser. Baisser un seuil augmente le bruit ; ajouter un critère augmente la précision.
- **Signal de bonne calibration** : 10 à 20 % des posts au-dessus du seuil de conservation.
  Au-delà de 30 % le scoring est laxiste ; en dessous de 5 % il est trop strict (ou les mots-clés
  sont mauvais).

## 7. Boucle de feedback permanente

1. Le MASTER garde deux colonnes ouvertes : `validation` (OUI/NON) et `motif` (texte libre).
2. La personne annote **quand elle veut** — le processus n'est jamais bloqué par cette étape.
3. À chaque run de découverte, relire les labels accumulés, proposer un ajustement des règles avec
   un **rapport des changements**, appliqué après accord.
4. Une organisation labellisée NON **deux fois avec le même motif** entre en blacklist.

> **Insister sur le champ `motif`, y compris quand la réponse est OUI.** Un OUI/NON seul ne permet
> quasiment aucune induction ; c'est le motif qui porte l'information (« OUI mais seulement en
> ligne », « NON car je ne connais pas cet outil », « NON car ils ne répondent jamais »).

## 8. Erreurs à éviter

- Confondre malus et filtre : un −5 laisse passer un post à 13, une exclusion non.
- Scorer sans tracer : sans `commentaire_scoring` détaillant le calcul, aucune correction possible.
- Traiter un vivier comme une annonce.
- **Pénaliser une information manquante** (taux, lieu) : marquer « à déterminer » et poser la
  question — c'est une opportunité de dialogue, pas un défaut.
- Sur-ajuster sur peu de labels : en dessous de ~15 labels, s'en tenir aux règles évidentes.
