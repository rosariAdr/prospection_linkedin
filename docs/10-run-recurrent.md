# 10 — Relancer un run (profil déjà en place)
> `09-prompt-demarrage.md` sert à **amorcer un nouveau profil**. Ce document-ci est le mode
> opératoire d'un run de routine, avec les commandes exactes.

## 0. Pré-requis, à vérifier avant de lancer quoi que ce soit

- [ ] **GO explicite** de la personne. Un run ne démarre jamais sans.
- [ ] La config présente et à jour (blacklist relue) : `data/config.yaml` en mode local,
      `config.yaml` du dossier de données en mode partagé (§7).
- [ ] Ordinateur allumé, Chrome ouvert, extension connectée, session LinkedIn active.
- [ ] `pip install -r requirements.txt`.
- [ ] Mode partagé : `python -m prospection.run poste --run <id>` ne signale aucun `BLOQUANT`
      (§7).

## 1. Cadrer

Trois décisions changent le livrable — les poser, ne pas les supposer :

| Décision | Options |
|---|---|
| Fenêtre | `past-week` (7 j) · `past-month` + coupure (il n'existe pas de filtre « 2 semaines ») |
| Mots-clés | tous · noyau prioritaire seul · liste resserrée sur un besoin précis |
| Annonces non datées | conservées « échéance à qualifier » (défaut) · pénalisées · exclues |

## 2. Répartir et scraper

```bash
python -m prospection.run lots --run 24-09-2026 --agents 3
```

La première ligne annonce le mode : `données : local — …` ou `données : partagé — …`. Avec
`--run`, la commande crée le dossier du run et affiche deux chemins absolus, `dossier du run` et
`config`. Ce sont eux qu'on colle dans le prompt des agents, tels quels. En mode partagé, elle
valide aussi l'identifiant du run, refuse un run déjà finalisé (code 2) ou préparé sur un autre
poste (code 3), puis prend le verrou (§7). Sans `--run`, elle ne fait que répartir les
mots-clés.

Trois agents, **dans un seul bloc d'appels** — un appel par message produit une exécution
séquentielle et triple la durée. Chaque agent : son propre onglet, la recette
`docs/04-recette-scraping.md`, et son JSON écrit **au fur et à mesure** dans
`<dossier du run>/<LOT>.json` (schéma au §12 de la recette).

Pendant le run : une tâche par lot, un point de progression tous les 5 mots-clés, et une
alerte immédiate si une déconnexion dépasse 5 minutes (§13 de la recette).

## 3. Préparer le lot à scorer

```bash
python -m prospection.run prepare --run 24-09-2026 --jours 21
```

Produit `<dossier du run>/a_scorer.json` (dédupliqué, fenêtré) et `rapport_prepare.json`
(rendement par mot-clé, mots-clés sans résultat, organisations déjà en suivi). Comme
`lots --run`, la commande affiche le mode, puis le dossier du run et la config. En mode partagé,
elle prend ou rafraîchit le verrou, et refuse un run déjà finalisé (§7).

Le rendement par mot-clé n'est pas décoratif : c'est lui qui sert à recomposer le noyau
prioritaire et à retirer les mots-clés stériles de `search_plan.lots`.

## 4. Scorer et rédiger

Découper `a_scorer.json` en lots de 50 environ, un agent par lot (aucune limite d'agents
parallèles hors LinkedIn). Chaque agent lit `docs/03-scoring-et-regles.md`,
`docs/05-messages.md` et la config (chemin affiché par `prepare`), puis écrit
`<dossier du run>/scored_<LOT>.json`.

**Champs attendus en sortie** — la liste exacte est `prospection/workbook.py::COLS`. Deux
pièges récurrents :

- **`cle_contenu` doit être recopiée telle quelle** depuis `a_scorer.json`. C'est l'empreinte du
  texte brut ; sans elle, la ligne sera invisible à la déduplication du run suivant. Le build
  vous avertit si elle manque.
- **Seuls les posts conservés** figurent dans la sortie. Les exclus n'y sont pas.

## 5. Finaliser

```bash
# mode local
python -m prospection.run finaliser --run 24-09-2026 \
    --base data/prospection_precedent.xlsx
# mode partagé : --base est facultatif, la base est calculée (§7)
python -m prospection.run finaliser --run 24-09-2026
```

Cette commande applique un **filet de sécurité automatique** avant tout :

1. les organisations blacklistées (`blacklist.organisations`) sont écartées, quel que soit leur
   score, et la ligne écartée est imprimée ;
2. les organisations en observation sont conservées mais préfixées d'un avertissement ;
3. les lignes sous `seuil_conservation` sortent du livrable ;
4. les garde-fous tournent — longueurs, salutations, coordonnées en commentaire public,
   cohérence mail, cohérence seuil, une seule candidature par organisation. **En cas d'échec,
   rien n'est écrit** et le détail s'affiche.

Puis le classeur est construit (MASTER + `DELTA_<date>` + SUIVI_LEADS).

- **Mode local** : le classeur et les CSV sont exportés dans `data/` — ce sont eux que relit la
  déduplication du run suivant.
- **Mode partagé** : `classeurs/prospection_<run>.xlsx`, puis `historique/DELTA_<run>.csv`. Le
  DELTA est écrit en dernier : il marque le run finalisé, et c'est lui que relit la
  déduplication du run suivant. Aucun `MASTER.csv` ni `SUIVI_LEADS.csv`. La commande affiche le
  nombre de lignes réinjectées depuis l'historique, puis libère le verrou.

## 6. Livrer

- Le **delta** se lit en deux minutes, le **MASTER** est la référence.
- Résumer : couverture (n/n mots-clés), entonnoir (bruts → uniques → conservés → leads), le top
  du lot, et **les arbitrages tranchés** — un doublon d'organisation, une exclusion discutable,
  une organisation en observation retenue.
- Dire ce qui n'a pas marché : mots-clés stériles, incidents, limites connues.

## 7. Poste et données partagées (plusieurs PC)

GitHub porte le code, et chaque PC le clone. Les données vivent dans **un dossier hors du
dépôt**, synchronisé entre les PC : Google Drive pour ordinateur, par exemple
`G:\Mon Drive\prospection\donnees`. Ce dossier est désigné par `--donnees` ou par la variable
`PROSPECTION_DONNEES`. Sans l'un ni l'autre, c'est le **mode local**, inchangé : `data/` et
`runs/` sous la racine du dépôt, sans verrou.

Chaque commande annonce son mode en première ligne. `--donnees` se place avant ou après la
sous-commande, et passe avant la variable. Un chemin relatif se lit depuis le répertoire
courant. Un dossier introuvable (Drive non monté), non initialisé, situé dans le dépôt ou dans
un arbre git : message clair, code 2.

| Dans le dossier de données | Rôle |
|---|---|
| `config.yaml` | la config du profil, source unique de vérité |
| `historique/` | les `DELTA_<run>.csv` écrits par `finaliser`, et le MASTER migré. Ajout seul |
| `runs/<run>/` | JSON des agents, `a_scorer.json`, `scored_*.json`, `proprietaire.json` |
| `classeurs/` | `prospection_<run>.xlsx`, un par run |
| `verrou.json` | le verrou de run |
| `.prospection-donnees` | le marqueur du dossier : ne pas le supprimer |
| `LISEZMOI.md` | les règles de ce chapitre, en bref |

Un run n'écrit que ses propres fichiers : son dossier de run, `historique/DELTA_<run>.csv` et
`classeurs/prospection_<run>.xlsx`. Il ne touche jamais aux fichiers d'un autre run.

### Mettre en place un PC

1. Installer Google Drive pour ordinateur. Rendre le dossier de données « Disponible hors
   connexion » (clic droit sur le dossier, dans l'Explorateur).
2. Cloner le dépôt et installer les dépendances :
   ```powershell
   git clone <url du dépôt>
   cd prospection_linkedin
   pip install -r requirements.txt
   ```
3. Poser la variable, pour l'utilisateur :
   ```powershell
   [Environment]::SetEnvironmentVariable('PROSPECTION_DONNEES', 'G:\Mon Drive\prospection\donnees', 'User')
   ```
   Une apostrophe dans le chemin s'écrit doublée (`''`), une apostrophe typographique aussi
   (`’’`) : PowerShell la prend pour un délimiteur. La commande affichée par
   `initialiser-donnees` les double déjà.
4. **Redémarrer** Claude, les terminaux et GitKraken. Une variable « User » n'atteint que les
   processus lancés après elle : un terminal déjà ouvert ne la voit pas.
5. Contrôler le poste :
   ```powershell
   python -m prospection.run poste
   ```
   Code 0 : le PC peut lancer un run. Code 2 : au moins une ligne `BLOQUANT`, à corriger d'abord.

À défaut de variable, passer `--donnees "G:\Mon Drive\prospection\donnees"` à chaque commande.

`poste [--run R]` affiche une ligne par contrôle, `OK`, `AVERTISSEMENT` ou `BLOQUANT` :

- Python ≥ 3.10, `openpyxl` et `yaml` ;
- le mode et, en partagé, le dossier : présent, hors de tout arbre git, marqueur, droit
  d'écriture ;
- sous Windows, une variable posée pour l'utilisateur mais pas encore vue par ce processus :
  avertissement « redémarrez l'application et les terminaux » ;
- `data/MIGRE_VERS_PARTAGE.txt` présent en mode local : `BLOQUANT` ;
- la config, chargeable. En mode partagé, c'est `config.yaml` du dossier de données, et
  `--config` est `BLOQUANT`, comme il est refusé par `lots`, `prepare` et `finaliser` ;
- l'historique : fichiers reconnus, lignes, clés recalculées depuis les JSON bruts des anciens
  runs. Un fichier illisible est `BLOQUANT`. Des DELTA sans aucun JSON brut avertissent : leurs
  clés datent d'avant le correctif #3, des doublons sont possibles ;
- les copies en conflit : `BLOQUANT` dans `historique/`, dans `classeurs/` et sur la config,
  avertissement ailleurs ;
- le verrou. Avec `--run R`, `BLOQUANT` s'il est tenu par un autre poste ou par un autre run ;
- avec `--run R` en mode partagé, le run lui-même : identifiant hors format, run déjà finalisé
  ou préparé sur un autre poste, `BLOQUANT`. C'est ce que `lots --run` refuserait ;
- le classeur le plus récent ;
- le code : branche, commit, âge du dernier `fetch`, retard sur l'amont. Une branche autre que
  `main` ou `dev`, ou un `fetch` de plus d'un jour, avertit (`git pull --ff-only`). Git n'est
  jamais bloquant.

La racine des données n'est affichée qu'une fois, et le nom du profil jamais (« profil
chargé »), pas plus que le nom du fichier de config s'il n'est pas `config.yaml`. La sortie
nomme quand même le poste et des chemins : **ne jamais la coller dans une PR ou une issue.**

### Migrer les données (une fois, depuis le PC qui les a)

```powershell
python -m prospection.run initialiser-donnees --vers "G:\Mon Drive\prospection\donnees"
```

La commande :

- refuse un `--vers` situé dans le dépôt ou dans un arbre git, avant de créer quoi que ce soit
  (code 2). Un lecteur non monté (Google Drive pour ordinateur arrêté) est annoncé comme tel ;
- crée `config.yaml`, `historique/`, `runs/`, `classeurs/`, `LISEZMOI.md` et le marqueur
  `.prospection-donnees`, posé en dernier ;
- copie la config de `data/` sous le nom `config.yaml` ;
- copie dans `historique/` les CSV d'historique de `data/` (MASTER, DELTA : ils ont une colonne
  `auteur`). Un export `SUIVI_LEADS.csv` n'est pas migré ;
- copie les JSON de `runs/<run>/` du dépôt vers `runs/<run>/` du dossier de données. Ce sont
  eux qui permettent de recalculer les clés de déduplication des anciens runs : sans eux, des
  doublons reviennent ;
- copie le classeur zéro dans `classeurs/` : le `prospection_<JJ-MM-AAAA>.xlsx` le plus récent
  de `data/`, ou celui de `--classeur FICHIER` ;
- dépose `data/MIGRE_VERS_PARTAGE.txt` : en mode local, les commandes s'arrêtent désormais
  (code 2) au lieu de lire un `data/` périmé ;
- nomme, ligne par ligne (« non migré »), les autres fichiers de `data/` laissés sur place :
  notes, listes, classeurs plus anciens que le classeur zéro. Les copier à la main dans le
  dossier de données si un autre PC en a besoin ;
- affiche un récapitulatif chiffré, puis la commande PowerShell qui pose la variable. **Elle ne
  pose aucune variable elle-même.**

Elle copie, elle ne déplace pas : les fichiers de `data/` et `runs/` restent en place, et ne
sont plus lus. Elle n'écrase jamais rien : un fichier déjà présent est signalé (« déjà
présent ») et laissé tel quel. On peut donc la relancer, après une copie interrompue par
exemple. `--depuis` et `--runs` changent les dossiers source.

Migrer **avec** un classeur zéro, nommé `prospection_JJ-MM-AAAA.xlsx` : sous un autre nom,
`finaliser` ne le prend jamais comme base. Sans classeur zéro, le premier `finaliser` part d'un
classeur vide. Le MASTER est alors reconstruit depuis l'historique : `MASTER.csv` d'abord, dont
les labels et l'ordre font foi, puis les DELTA des anciens runs. Sont perdus les labels saisis
après le dernier export CSV, et les leads des anciens runs n'entrent pas dans SUIVI_LEADS.

Nouveau profil, sans config : `--gabarit` copie `templates/config-profil.example.yaml`, annoncé
« GABARIT copié : à remplir avant tout run ». Sans config, sans `--gabarit` et sans CSV
d'historique, la commande refuse (code 2).

### Règles entre plusieurs PC

- **Dossier « Disponible hors connexion »** sur chaque PC. Un fichier « en ligne uniquement »
  ne se lit pas sur un PC hors connexion : la commande s'arrête en le nommant (code 2). Jamais
  de repli silencieux sur un historique vide.
- **Attendre que Drive soit « à jour »** avant de changer de PC. Sinon l'autre PC lit un verrou
  ou un classeur périmé, et le Drive fabrique des copies en conflit.
- **Un seul poste de run planifié à la fois** ([`07-automatisations.md`](07-automatisations.md)
  §3).
- **Un run se finit sur le poste qui l'a préparé.** Le premier `prepare` écrit
  `runs/<run>/proprietaire.json`. `lots --run`, `prepare` ou `finaliser` lancés ailleurs sur ce
  run sortent en code 3. `--forcer` le reprend, une fois sûr que l'autre poste a arrêté.
- **Ne jamais supprimer une ligne du MASTER** : la passer en `validation=NON`. Une ligne
  supprimée revient depuis l'historique au `finaliser` suivant.
- **Les labels se saisissent dans le classeur le plus récent** de `classeurs/`. Le `finaliser`
  suivant part de lui : ses labels (`validation`, `motif`, `statut_lead`) passent dans le
  classeur du run. Un label saisi dans un classeur plus ancien est perdu pour la suite.
- **Fermer Excel avant `finaliser`** : un `~$prospection_<run>.xlsx` à côté du classeur arrête
  la commande (code 2).
- **Ne jamais coller la sortie de `poste`** dans une PR ou une issue.

### Le verrou

Il évite qu'un PC lance ou finalise un run pendant qu'un autre en a un en cours. En mode
partagé, il est automatique :

- `lots --run R` le prend au début du scraping ;
- `prepare` et `finaliser` le prennent ou le rafraîchissent ;
- `finaliser` le libère après succès. Si le Drive refuse à ce moment de réécrire `verrou.json`
  (fichier tenu par la synchronisation, un antivirus), le run reste finalisé, code 0, et un
  avertissement donne la commande à relancer une fois le Drive à jour :
  `verrou liberer --run R`. Sinon les autres postes restent bloqués jusqu'à expiration.

Verrou occupé : code 3, rien d'écrit. Il est occupé s'il est pris par un autre poste, par ce
poste pour un **autre** run, ou s'il est illisible. Sans activité depuis 12 h, il a expiré : il
est repris, avec un avertissement.

Pour un run abandonné, ou pour forcer :

```powershell
python -m prospection.run verrou statut [--run R]
python -m prospection.run verrou liberer --run R    # run abandonné, sur le poste qui le tenait
python -m prospection.run verrou liberer --forcer   # verrou d'un autre poste, sûr qu'il a arrêté
python -m prospection.run verrou prendre --run R [--ttl-heures N]
```

Libérer ne supprime pas `verrou.json` : il est réécrit avec `"etat": "libre"`, car un fichier
supprimé sur un Drive peut revenir. Une écriture refusée par le Drive sort en code 2 : attendre
que le Drive soit à jour, puis relancer. En mode local, `verrou` répond « sans objet ».
`lots`, `prepare` et `finaliser` acceptent aussi `--forcer`, qui passe outre le verrou, le
propriétaire du run, un run déjà finalisé et les contrôles d'ordre.

⚠️ **Ce n'est pas un verrou distribué.** Le Drive synchronise avec retard : deux PC qui le
prennent à la même seconde l'ont tous les deux, et le Drive en fait une copie
`verrou (1).json`. Le verrou couvre l'oubli — lancer un run sur le PC B alors que le PC A n'a
pas fini —, pas la course à la seconde. Toutes les copies `verrou*.json` sont lues : une copie
tenue par un autre poste bloque comme l'original.

### Identifiant de run et ordre des runs

En mode partagé, l'identifiant est strict : `JJ-MM-AAAA`, ou `JJ-MM-AAAA-n` avec n ≥ 2 pour un
second run le même jour (`24-09-2026-2`). Tout autre format sort en code 2, dès `lots --run`.
Le mode local garde un texte libre.

- `lots --run` ou `prepare` sur un run déjà finalisé (`historique/DELTA_<run>.csv` présent) :
  code 2, avant toute écriture, verrou compris. Prendre l'identifiant suivant, ou `--forcer`.
- `finaliser` refuse un run plus ancien qu'un classeur déjà présent dans `classeurs/` (code 2) :
  on finalise dans l'ordre. `--forcer` passe outre.
- Refinaliser un run réécrit ses deux fichiers, et garde les labels déjà saisis dans son
  classeur : MASTER et SUIVI_LEADS, mais aussi `validation` et `motif` de l'onglet DELTA du
  run, ligne retrouvée par sa clé (contenu, URL, auteur + extrait). Le CSV DELTA réécrit les
  porte. En mode local, l'onglet DELTA est recréé à vide, comme avant.

### Ce que lisent `prepare` et `finaliser`

**`prepare`** déduplique contre `historique/*.csv` (MASTER et DELTA, reconnus à leur colonne
`auteur`), les JSON bruts des autres runs et le MASTER du classeur de base. Une copie en conflit
dans `historique/` est lue, avec un avertissement : l'union des clés est la plus prudente, mais
il faut la fusionner avant `finaliser`. Un export `SUIVI_LEADS.csv` posé dans `historique/`
n'est pas lu. Les fichiers de travail (`~$…`, `….tmp`) sont ignorés et nommés, dans
`historique/` comme dans le dossier du run. Un fichier illisible arrête tout (code 2).

En mode partagé, la config est `config.yaml` du dossier de données, la même pour tous les
postes : `--config` est refusé (code 2) par `lots`, `prepare` et `finaliser`.

**`finaliser`** fait tous ses contrôles et toutes ses lectures, puis toutes ses écritures. Il
s'arrête, code 2 et rien d'écrit, sur :

- une copie en conflit dans `historique/`, dans `classeurs/` ou sur la config
  (`config (1).yaml`) : la fusionner à la main avec l'original, puis supprimer la copie ;
- un classeur postérieur au run ;
- une base illisible : jamais de repli sur un classeur vide ou plus ancien. Une base disparue
  entre sa lecture et l'écriture (renommage appliqué par le Drive, déplacement) arrête aussi
  tout ;
- un classeur ouvert dans Excel ;
- un `--base` introuvable. Un `--base` hors de `classeurs/`, ou autre que la base calculée,
  exige `--forcer`. `--sortie` n'existe qu'en mode local.

**La base** se calcule : le classeur du run lui-même s'il existe (refinalisation), sinon le plus
récent strictement avant le run, par date. Aucun classeur : classeur vide, avec un
avertissement.

**Le MASTER est calculé** : la base, plus les lignes d'historique qui y manquent, plus le run
courant. Les lignes des runs antérieurs passent par le filtre F4 : une organisation blacklistée
n'est jamais réinjectée. Elles se lisent dans cet ordre : `MASTER.csv` migré, les autres CSV
sans run dans le nom, les DELTA des anciens runs au nom libre, puis les `DELTA_<run>.csv` des
runs strictement antérieurs, par date. Ni un run postérieur ni le run lui-même n'en
fournissent. Une ligne est déjà présente si sa `cle_contenu`, son URL (hors URL de recherche,
`search/results` dans le chemin) ou sa clé auteur + extrait est connue.

La commande affiche `réinjectées depuis l'historique : N`. **N vaut 0 en régime normal.** Un
autre nombre est un signal : une ligne supprimée à la main, un classeur d'un autre poste pas
encore synchronisé, ou le premier run après une migration sans classeur zéro.

Un `DELTA_<run>.csv` antérieur sans onglet `DELTA_<run>` dans la base est signalé : ses leads ne
figurent pas dans SUIVI_LEADS, et n'y sont jamais réinjectés (ils y entreraient « À contacter »
à tort).

Le classeur puis le DELTA s'écrivent par un temporaire `….tmp`, remplacé à la fin. Une écriture
refusée (fichier ouvert, Drive qui verrouille) ne marque pas le run finalisé : relancer
`finaliser`.

### Codes de sortie

| Code | Sens |
|---|---|
| 0 | succès |
| 1 | rien à traiter : aucun JSON d'agent, aucun `scored_*.json` |
| 2 | refus : garde-fou, emplacement des données, fichier illisible, contrôle bloquant |
| 3 | verrou occupé, ou run préparé sur un autre poste |

## Si Chrome se déconnecte en cours de route

Attendre 45-90 s, `list_connected_browsers` → `select_browser` → `tabs_context_mcp`, reprendre
**au mot-clé suivant**. Les JSON déjà écrits sont conservés, `prepare` les relira. Si l'absence
dure : prévenir, programmer une re-vérification avec un **nombre de tentatives borné**, et ne
jamais boucler en silence.
