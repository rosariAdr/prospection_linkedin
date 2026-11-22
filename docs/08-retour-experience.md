# 08 — Retour d'expérience chiffré (cas réel, août-septembre 2026)
> Sert d'**étalon** : à quoi ressemblent des volumes normaux, où passe le temps, quelles décisions
> ont eu le plus d'impact.

## 1. Volumes réels

| Étape | Date | Mots-clés | Posts bruts | Uniques | Retenus | Leads créés |
|---|---|---|---|---|---|---|
| POC (past-month) | 13/08 | 4 | 76 | 76 | 12 | 12 |
| Run complet (past-month) | 14/08 | 45 | ~450 | 291 | 66 | +39 → **51** |
| Run hebdo (past-week) | 19/08 | 45 | 163 | 105 | 15 | +8 → **59** |
| Run hebdo (past-week) | 03/09 | 49 | 203 | 155 | 17 | +14 |

**Ratios à retenir :**
- En `past-month`, environ **1 post sur 4,4** dépasse le seuil ; en `past-week`, **1 sur 7**.
- **~86 % de bruit** sur un run hebdomadaire : c'est normal, pas un défaut de calibrage.
  Le flux hebdomadaire est structurellement plus bruité (autopromo, certifications perso, CV).
- La déduplication élimine **10 à 15 %** des posts à chaque run. Sans elle, le fichier se remplit
  de doublons dès le deuxième passage.
- Seules **7 opportunités sur 59** comportaient une adresse mail : **le canal LinkedIn
  (commentaire + invitation) est le canal principal, pas un complément.**

## 2. Les labels qui ont tout changé

21 lignes annotées au POC. Les **anomalies** ont produit l'essentiel des règles :

| Ligne | Score | Label | Motif | Règle induite |
|---|---|---|---|---|
| Référentiel non maîtrisé | **10** | NON | « notions que je ne connais pas » | Compétence hors périmètre = filtre absolu |
| Organisme relancé 2× | 9 | NON | « aucune réponse constructive » | Organisation non réactive → observation puis blacklist |
| Jury cybersécurité | 8 | NON | « pas mon domaine » | Domaine adjacent → **retirer le mot-clé** |
| Annonce pourvue | 4 | NON | « car trouvé » | Annonce close |
| Stats, Tanger | **2** | **OUI** | « si en ligne » | Hors zone ≠ exclusion si distanciel |
| Agence de mise à disposition | **4** | **OUI** | — | **Les viviers sont des cibles** |
| Maths, Québec | 4 | NON | « diplôme québécois nécessaire » | Diplôme local exigé |

> **4 des 9 anomalies sont des OUI à score faible.** Sans les labels, ces opportunités auraient
> été définitivement ignorées — dont deux qui ont créé une catégorie entière (« vivier »)
> représentant aujourd'hui près d'un lead sur cinq.

**Une règle n'est apparue qu'au 2ᵉ run** : le mot « intervenant » désigne aussi, dans le BTP, le
ferroviaire, la production et les RH, une *partie prenante* de projet. **18 posts** sur un seul run
relevaient de ce piège, soit ~18 % des faux positifs. Impossible à anticiper au cadrage — c'est
l'argument principal en faveur du run mensuel de découverte.

## 3. Performance technique

| Méthode | Durée |
|---|---|
| 45 mots-clés, sous-agents **séquentiels** | ~3 h |
| 45 mots-clés, **3 sous-agents parallèles** | **~1 h** |

⚠️ Piège : émettre les appels `Agent` **un par message** produit une exécution séquentielle même
avec trois agents. La parallélisation n'existe que si les appels sont dans **un seul bloc**.

**Incidents, par fréquence :**
1. **Déconnexions de l'extension Chrome** (veille du PC) — de loin le problème principal.
2. Timeouts `browser_batch` ponctuels — résolus par une attente de 45 s.
3. Renderer gelé après des screenshots répétés — évité en n'utilisant que `javascript_tool`.
4. **Aucun captcha, aucune restriction LinkedIn** sur ~900 posts consultés en 6 semaines.

## 4. Les corrections demandées par l'utilisateur (et ce qu'elles enseignent)

| Retour | Correction | Leçon générale |
|---|---|---|
| « Beaucoup de messages manquent » | Seuil de rédaction 8 → > 5 | Un seuil trop haut rend le livrable non actionnable |
| « Les lignes sous 3 me font perdre du temps » | Elles sortent du fichier | Le livrable doit être **court** |
| « Les colonnes portent à confusion » | Renommage explicite des 5 textes | Nommer par le canal, pas par le contenu |
| « Il y a trop de règles » | 15 règles → 6 (F1-F4, V1-V2) | Consolider sans casser la catégorisation |
| « Je n'aime pas les BTS, mais je les prenais pour le CA » | Malus −3 | **Un critère dépend du moment de l'année** |
| « Ne lance pas de run sans mon GO » | Checkpoint dur | L'autonomie se mérite, elle ne se suppose pas |

## 5. Ce que je referais différemment

1. **Labelliser plus tôt et plus large** : 21 labels ont suffi à produire 7 règles ; 30-40 auraient
   probablement révélé le faux positif lexical dès le premier run.
2. **Paralléliser dès le départ**, dans un seul bloc d'appels.
3. **Mesurer le rendement par mot-clé dès le POC** pour constituer le noyau prioritaire plus tôt.
4. **Prévoir la panne navigateur dès la conception**, avec notification, reprise et nombre de
   tentatives borné.
5. **Dédupliquer par contenu dès le départ**, sans attendre que les permaliens se cassent.
