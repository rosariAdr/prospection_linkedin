# 07 — Automatisations : cadences, planification, pannes

## 1. Le compromis

La réactivité est décisive (les décideurs retiennent souvent les premières réponses), mais scraper
45 mots-clés tous les jours est long et augmente le risque de restriction.

**Solution : la rotation.**
- Un **noyau prioritaire** de ~15 mots-clés (ceux qui produisent réellement) passe tous les jours.
- Une **rotation** de ~8-9 mots-clés parmi le reste complète chaque run ; cycle complet en 4-5 jours.
- Les mots-clés **stériles** (0 résultat sur plusieurs runs) passent en fréquence hebdo ou mensuelle.

> Le noyau prioritaire ne se devine pas : il se **mesure** après le premier run complet, en comptant
> les opportunités retenues par mot-clé (colonne `mot_cle_recherche`).

## 2. Les deux automatisations

**A. Veille périodique** — jours ouvrés, filtre `past-week` :
vérifier le navigateur → scraper noyau + rotation → dédupliquer contre le MASTER → scorer →
rédiger les messages des retenus → mettre à jour MASTER/SUIVI_LEADS + créer `DELTA_<date>` →
livrer (xlsx delta + MASTER + notification + résumé). Full-auto, aucun checkpoint bloquant.

**B. Découverte mensuelle** — deux fonctions, et c'est ce qui empêche le système de se scléroser :
1. **enrichir le vocabulaire** : recherches volontairement génériques (« recherche <rôle> »,
   « recrute <rôle> », « cherchons <rôle> », « appel à <rôle> ») → extraire les formulations
   réellement employées → proposer des mots-clés à ajouter, retirer les stériles ;
2. **ré-apprendre des labels** : relire les colonnes validation/motif remplies depuis le dernier
   passage, ré-ajuster règles et pondérations, produire un rapport des changements réversible.

## 3. Planification technique

Utiliser les **tâches planifiées côté serveur** (`create_trigger` / `send_later`), **jamais** un
planificateur interne à la session : une tâche planifiée dans la session disparaît quand la session
se termine, et la personne ne le voit jamais.

```yaml
create_trigger:
  name: "Veille LinkedIn quotidienne"
  cron_expression: "0 16 * * 1-5"    # ⚠️ UTC — 18h Paris en été = 16h UTC
  prompt: <instruction autonome et complète, --donnees compris en mode partagé>
  requires_local_device: true        # le run a besoin du Chrome de la personne
  notifications: {push: true, email: true}
```

⚠️ **Le prompt d'une tâche planifiée doit être auto-suffisant** : chaque déclenchement démarre une
session vierge. Il doit rappeler où trouver la config, la recette, le MASTER, et quoi livrer.

**Données partagées entre plusieurs PC** (`10-run-recurrent.md` §7) :

- **La tâche planifiée tourne sur un seul poste**, celui où Chrome et la session LinkedIn sont
  ouverts au créneau choisi. Ne pas planifier de run sur un second PC : le verrou l'arrête s'il
  est déjà synchronisé (code 3), mais deux postes qui démarrent avant que le Drive ait
  synchronisé le verrou le prennent tous les deux. Il couvre l'oubli, pas la course à la seconde.
- **Le prompt passe `--donnees` explicitement** à chaque commande
  (`--donnees "G:\Mon Drive\prospection\donnees"`), sans compter sur la variable : une session
  lancée avant que la variable soit posée ne la voit pas, et tomberait en mode local (arrêté par
  `MIGRE_VERS_PARTAGE.txt` sur le PC migré, sans config ailleurs).
- Le prompt commence par `python -m prospection.run poste --run <id>`, et s'arrête sur un
  `BLOQUANT`.

## 4. La dépendance au navigateur (contrainte majeure)

Le run n'aboutit que si l'ordinateur est allumé, Chrome ouvert, extension connectée et session
LinkedIn active. En mode partagé, il faut aussi le Drive démarré et à jour sur ce poste.
Choisir un créneau où c'est **certain** (fin de journée, pas 3 h du matin).

**Procédure de repli, à encoder dans chaque tâche planifiée :**
1. Vérifier la connexion navigateur.
2. Si absente : notifier, reprogrammer une vérification dans 15-30 min, **borner le nombre de
   tentatives** (ex. 6), et au run suivant **élargir la fenêtre** pour rattraper la période manquée.
   Ne jamais boucler indéfiniment sans notifier.
3. Si déconnexion en cours de run : attendre 45-90 s, reconnecter, reprendre au mot-clé suivant,
   jamais depuis le début.
4. En mode partagé, si `poste --run <id>` signale un `BLOQUANT` (Drive non monté, fichier
   « en ligne uniquement », verrou tenu ailleurs, run déjà finalisé ou préparé sur un autre
   poste) : notifier, ne pas lancer. Une reprise du même run garde le même identifiant : le
   verrou de ce poste est simplement rafraîchi. Un run déjà finalisé ne se reprend pas : prendre
   l'identifiant suivant (`JJ-MM-AAAA-n`).

⚠️ Un run resté inachevé garde le verrou. Sur le même poste, un run d'un **autre** identifiant
sort en code 3 tant que ce verrou n'a pas expiré (12 h sans activité). Finir le run inachevé, ou
le libérer : `python -m prospection.run verrou liberer --run <id inachevé>`.

> **Retour d'expérience** : les déconnexions (mises en veille du PC) ont été l'incident le plus
> fréquent, et de loin — bien avant les limitations LinkedIn, jamais atteintes. Une interruption a
> duré plusieurs heures ; le run a repris exactement au mot-clé suivant.

## 5. Indicateurs à suivre d'un run à l'autre

| Indicateur | Ce qu'il révèle |
|---|---|
| Posts bruts / nouveaux après dédup | Saturation de la fenêtre de recherche |
| % au-dessus du seuil de conservation | Calibrage du scoring (viser 10-20 %) |
| Opportunités retenues **par mot-clé** | Composition du noyau prioritaire |
| Mots-clés à 0 résultat | Candidats à la fréquence réduite |
| Filtres déclenchés, par règle | Règles à affiner, mots-clés à retirer |
| Délai entre publication et détection | Efficacité réelle de la cadence |
