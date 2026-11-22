# 04 — Recette technique d'extraction LinkedIn (Claude in Chrome)
> Validée sur ~900 posts et 5 runs (août-septembre 2026). C'est la partie la plus fragile du
> système : **ne pas improviser une autre méthode**, les approches naïves échouent en silence (§6).

## 0. Pourquoi c'est compliqué

L'interface LinkedIn 2026 utilise un **DOM virtualisé** : seules quelques cartes de post existent
dans le DOM à un instant donné, et les identifiants d'activité (`urn:li:activity:...`) **ne sont
pas présents dans le HTML**.

- Impossible de récupérer les permaliens par lecture du DOM.
- `window.scrollTo()` et `scrollIntoView()` ne déclenchent aucun chargement.
- Il faut **scroller à la molette** (événement natif) et **harvester au fur et à mesure**.
- Le permalien s'obtient via le menu « … » → « Copier le lien », en **interceptant le presse-papiers**.

## 1. Initialisation (une fois par agent)

1. Charger les outils en **un seul** appel ToolSearch :
```
select:mcp__claude-in-chrome__tabs_context_mcp,mcp__claude-in-chrome__navigate,mcp__claude-in-chrome__computer,mcp__claude-in-chrome__tabs_create_mcp,mcp__claude-in-chrome__tabs_close_mcp,mcp__claude-in-chrome__javascript_tool,mcp__claude-in-chrome__browser_batch,mcp__claude-in-chrome__select_browser,mcp__claude-in-chrome__list_connected_browsers
```
2. `list_connected_browsers` → relever le `deviceId`.
   ⚠️ **Le deviceId change à chaque session Chrome.** Ne jamais le coder en dur dans une
   procédure durable ; le relire et l'injecter dans le prompt des agents au moment du run.
3. `select_browser` avec ce deviceId.
4. `tabs_create_mcp` → **son propre onglet**. Utiliser ce `tabId` pour tous les appels suivants.

## 2. URL de recherche

```
https://www.linkedin.com/search/results/content/?keywords=<MOTS_ENCODES>&datePosted=%22past-week%22
```
- Filtres disponibles : `past-24h`, `past-week`, `past-month`. **Il n'existe pas de filtre
  « 2 semaines »** → utiliser `past-month` puis couper sur la date relative (§8).
- Encoder : espace `%20`, `é` `%C3%A9`, `è` `%C3%A8`, `à` `%C3%A0`.
- Vérifier qu'on est bien sur les résultats **Posts** (et non Personnes / Emplois).

> On cherche des **posts**, pas des offres d'emploi : les besoins de vacation et de mission sont
> publiés en post et presque jamais déposés en offre formelle. C'est là qu'est l'avantage — pas
> de file de candidature, et la réactivité fait la différence.

## 3. Le harvester

**Le code fait foi dans [`scripts/harvester.js`](../scripts/harvester.js)** — il n'est pas recopié
ici pour qu'il n'existe qu'un seul exemplaire à maintenir. L'injecter **verbatim** via
`javascript_tool`, sans le reformater.

**Ce qu'il fait, et pourquoi chaque morceau est là :**
- `Clipboard.prototype.writeText` est **remplacé** pour capturer le permalien que LinkedIn copie
  dans le presse-papiers — on ne peut pas le lire autrement.
- `__doneKeys` évite de retraiter une carte recyclée par le conteneur virtualisé. Sa clé porte
  sur le **corps du post** (`__corpsOf`, ce qui suit le dernier horodatage) : calculée sur la
  carte entière, elle se remplissait d'en-tête quand le titre de l'auteur est long, et le second
  post du même auteur sur la page était sauté en silence.
- Le **pré-filtre `__isCand`** évite d'ouvrir un menu et d'attendre 1,8 s pour un post
  manifestement hors sujet : c'est ce qui rend le run tenable en temps.
- Les rejetés sont conservés en version compacte (`__R`) pour vérifier a posteriori que le
  pré-filtre n'a pas sur-exclu.
- `__lastStamp` prend la **dernière** occurrence d'un nombre suivi de « • » (voir §8) ;
  `__dateOf` (la date) et `__corpsOf` (la coupe du corps) s'en servent tous les deux.
- Le bouton de menu est repéré par son `aria-label`, seul élément stable de l'interface.

**Les seules choses à adapter à un autre profil ou à une autre langue :**
| À adapter | Où |
|---|---|
| Verbes de recrutement + noms de rôles | les deux regex de `__isCand` |
| Unités de la date relative (`min\|h\|j\|sem\|mois\|an`) | le motif de `__lastStamp` et `MOTIF_HORODATAGE` (`prospection/dates.py`), si l'interface n'est pas en français : sans elles, ni la date ni la coupe du corps ne fonctionnent |
| `"menu de commandes"` → `"control menu"` | interface LinkedIn en anglais |
| `/Copier le lien/i` → `/Copy link/i` | idem |

## 4. Boucle par mot-clé

**a)** `browser_batch` unique : `navigate` (avec tabId) → `computer wait` 7 s → `javascript_tool`
avec le harvester.

**b)** Scroll + harvest, 3 à 5 fois dans un `browser_batch` :
```
computer scroll {coordinate:[370,400], scroll_direction:"down", scroll_amount:10, tabId}
computer wait 3s
javascript_tool: await window.__proc()
```
Arrêt quand `nouveaux` vaut 0 deux fois de suite, ou après 5 cycles. En `past-week`, 2-3 cycles
suffisent presque toujours ; en `past-month`, compter 5.

**c)** Récupération : rejetés en un appel (`JSON.stringify(window.__R)`), puis candidats **un par
un** (limite d'affichage ≈ 1000 caractères par appel), groupés par 8-10 dans un `browser_batch` :
```javascript
const p=window.__H[0]; JSON.stringify({i:0,a:p.auteur,pr:p.profil,l:p.link,d:p.date_rel,t:p.texte.substring(0,750)})
```

**d)** Pause ~20 s avant le mot-clé suivant.

## 5. Parallélisation

Jusqu'à **3 sous-agents simultanés** sur le même navigateur, chacun avec son propre onglet.
Mesuré : 45 mots-clés en **~1 h au lieu de ~3 h**. Au-delà de 3, les timeouts d'extension
augmentent nettement.

Consigne obligatoire dans le prompt de chaque agent :
> « D'autres agents travaillent en parallèle dans le même navigateur. Crée TON PROPRE onglet avec
> `tabs_create_mcp` et n'utilise QUE ce `tabId`. Ne ferme aucun autre onglet que le tien. »

**Découpage** : 6 à 15 mots-clés par agent. Chaque agent **écrit lui-même son JSON sur disque**
(`runs/<date>/L<n>.json`) et ne renvoie qu'un résumé de 3-5 lignes — sinon le contexte de
l'orchestrateur explose.

⚠️ **La parallélisation n'existe que si les appels `Agent` sont émis dans un seul et même bloc.**
Un appel par message = exécution séquentielle, même avec trois agents.

## 6. Approches qui NE fonctionnent PAS (testées)

| Tentative | Résultat |
|---|---|
| `[data-urn]`, `[data-chameleon-result-urn]`, `.feed-shared-update-v2` | Attributs absents de l'interface 2026 |
| Chercher `urn:li:activity` dans `outerHTML` | 1 seule occurrence sur toute la page |
| `window.scrollTo(0, document.body.scrollHeight)` | Aucun chargement (conteneur virtualisé) |
| `element.scrollIntoView()` / touche `End` | Idem |
| Intercepter `fetch`/XHR pour lire les réponses GraphQL | Réponses en RSC compressé, sans texte exploitable |
| `document.documentElement.style.zoom='0.3'` | Charge plus de posts mais casse les coordonnées de scroll |
| Screenshots pour lire les posts | Lent, coûteux, gèle le renderer après quelques appels |

## 7. Le permalien : point de fragilité n°1

**Depuis le 24/08/2026**, LinkedIn renvoie des **liens raccourcis `https://lnkd.in/p/XXXXXXXX`**
au lieu du permalien complet. Les liens fonctionnent, mais **la déduplication par URL s'effondre** :
le même post produit un code différent à chaque capture.

### Parade obligatoire : dédupliquer aussi par contenu
**Le code fait foi dans [`prospection/cles.py`](../prospection/cles.py)** (`cle_contenu`,
`cle_secours`) ; il n'est pas recopié ici. Principe : une empreinte de l'auteur et du début du
texte normalisé (sans accents, casse, ponctuation ni espaces), plus une empreinte du texte seul
qui rattrape les reposts par un autre auteur.

⚠️ **Les deux clés portent sur le corps du post seul**, coupé après le dernier horodatage
(`corps_du_post`, même motif que §8). Le `texte` du harvester est la carte entière : en-tête
compris, la clé changeait quand la date passait de « 3 j » à « 1 sem » (le post revenait au run
suivant), et un titre long confondait deux annonces du même auteur.

⚠️ **Historique d'avant ce changement** : les clés déjà enregistrées dans les colonnes
`cle_contenu` / `cle_secours` d'un MASTER ou d'un CSV ont été calculées sur la carte entière et
ne correspondent plus aux nouvelles. Seules les clés tirées des JSON bruts de `runs/` sont
recalculées automatiquement (`Historique.ajouter_run`).

Testée sur 226 candidats (août-septembre 2026, clé encore calculée sur la carte entière) :
**45 doublons correctement écartés** là où la dédup par URL en avait détecté **0**. À appliquer
même quand les permaliens fonctionnent.

### Résolution des liens courts
Seulement pour les posts retenus : naviguer vers l'URL courte, lire l'URL finale (~5 s par lien).
Résoudre 100+ posts scorés 0 est du temps perdu.

## 8. Le filtrage par date

⚠️ **Ne jamais extraire la date par un simple `match(/(\d+)\s*(min|h|j|sem|mois|an)/)`** sur le
texte de la carte : le premier nombre rencontré est souvent celui du corps du post
(« 3 ans d'expérience », « +1 500 personnes formées »), ce qui écarte à tort des posts récents.
L'horodatage LinkedIn est **toujours suivi du séparateur `•`** — d'où le `(?=•)` et le choix de la
**dernière** occurrence dans `__lastStamp`, qu'utilisent `__dateOf` et `__corpsOf`.

**Date illisible ⇒ garder le post**, et filtrer en post-traitement.

## 9. Incidents

| Symptôme | Cause | Conduite à tenir |
|---|---|---|
| `did not respond in time` | Extension occupée / page lourde | Attendre 45 s, relancer le même appel |
| `extension disconnected` | Service worker Chrome redémarré | `sleep 45` → `list_connected_browsers` → `select_browser` → `tabs_context_mcp` → reprendre. **`window.__H` survit si la page n'a pas rechargé.** |
| `list_connected_browsers` → `[]` durablement | Chrome fermé / PC en veille | Ne pas boucler en silence : notifier, programmer une re-vérification (15-30 min), s'arrêter après N tentatives |
| Renderer gelé | Trop de screenshots | N'utiliser que `javascript_tool` |
| `[BLOCKED: Cookie/query string data]` | Le retour JS contient des tokens longs | Ne jamais renvoyer d'HTML brut ni `location.href` |
| Captcha / avertissement LinkedIn | Rythme trop soutenu | **Arrêter immédiatement**, noter les mots-clés restants, reprendre plus tard |

**Principe** : un run doit toujours pouvoir reprendre au mot-clé suivant. Écrire les résultats
intermédiaires sur disque après chaque lot.

## 10. Règles de sûreté (non négociables)

- ❌ Jamais de like, commentaire, republication, message ou candidature automatique.
- ❌ Jamais de clic sur un profil (coûteux, inutile, génère des « vues de profil »).
- ❌ Jamais de saisie d'identifiants. Si LinkedIn redirige vers `/uas/login`, s'arrêter et le dire.
- ✅ Seule interaction autorisée : menu « … » → « Copier le lien ».
- ✅ Fermer son onglet en fin de mission.

## 11. Adapter à un autre domaine

Trois points seulement sont spécifiques au cas « enseignement » :
1. Les **deux regex** de `__isCand` (verbes de recrutement + noms de rôles) ;
2. Les **libellés d'interface** si LinkedIn est en anglais (§3) ;
3. Les **mots-clés** (voir `02-config-profil.md`).

Tout le reste est réutilisable tel quel.

## 12. Fin de mission — schéma JSON attendu de chaque agent

Un agent de scraping ne renvoie **jamais** ses données dans sa réponse : il les écrit sur disque
et répond par un résumé de 3 à 5 lignes. Format du fichier, identique pour tous les lots :

```json
{
  "batch": "A",
  "date_run": "2026-09-23",
  "filtre": "past-month",
  "mots_cles_traites": ["formateur data", "..."],
  "mots_cles_non_traites": [],
  "nb_candidats": 122,
  "nb_rejetes": 85,
  "incidents": ["déconnexion extension après le mot-clé 5, reprise sans perte"],
  "candidats": [
    {"mot_cle": "formateur data", "auteur": "", "profil": "", "url_post": "",
     "date_rel": "3 j", "texte": "<750 caractères, INTÉGRAL, sans résumé ni paraphrase>"}
  ],
  "rejetes": [{"mot_cle": "", "a": "<auteur>", "e": "<extrait court>"}]
}
```

Les doublons entre mots-clés sont **conservés tels quels** : la déduplication est un
post-traitement (§7), pas le travail de l'agent.

## 13. Affichage de la progression (obligatoire)

Un run de 45 mots-clés dure une heure. Laisser la personne devant un écran muet pendant ce
temps-là est un défaut de conception, pas un détail :

- La **liste de tâches** porte une tâche par lot, pas une seule tâche « scraper ».
- Chaque agent **annonce sa progression** à l'orchestrateur sous la forme `lot A — 7/15 : formateur
  Power BI (3 candidats)`, au minimum tous les 5 mots-clés.
- L'orchestrateur **relaie une ligne de progression** à la personne à chaque lot terminé, et
  immédiatement en cas d'incident durable (déconnexion de plus de 5 minutes).
- À la fin du run, publier le **rendement par mot-clé** (nombre de candidats bruts) : c'est ce
  tableau qui sert à recomposer le noyau prioritaire et à retirer les mots-clés stériles.
