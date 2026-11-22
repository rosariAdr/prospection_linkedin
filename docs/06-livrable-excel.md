# 06 — Le classeur de suivi

Un **unique classeur Excel** sert à la fois de base de données, d'interface de feedback et de CRM
léger. Un seul fichier, ouvrable, filtrable et annotable sans outil supplémentaire.

## Colonnes des onglets de données (`MASTER`, `DELTA_*`)

| # | Colonne | Contenu |
|---|---|---|
| 1 | `post_extrait` | 1-2 phrases factuelles résumant l'annonce |
| 2 | `url_post` | Permalien — jamais l'URL de recherche |
| 3 | `url_profil_auteur` | `/in/…` ou `/company/…` |
| 4 | `auteur` | Nom affiché |
| 5 | `date` | Date relative du post (`2 j`, `1 sem`) |
| 6 | `mail` | Adresse trouvée dans le texte, sinon vide |
| 7 | `taux_horaire` | Montant, ou **`à déterminer`** |
| 8 | `localisation` | Zone / hors zone / distanciel / non précisé |
| 9 | `score_pertinence` | Score numérique |
| 10 | `mot_cle_recherche` | Le mot-clé qui a remonté le post (mesure le rendement) |
| 11 | `batch` | Run d'origine |
| 12 | `type_opportunite` | `annonce directe` / `réseau / vivier` / `à qualifier` |
| 13 | `deal_breaker` | Filtre déclenché (vide si aucun) |
| 14 | `commentaire_scoring` | **Détail du calcul** — indispensable pour corriger |
| 15-19 | les 5 textes | commentaire, note 200, note 300, message LinkedIn, mail |
| 20 | `cle_contenu` | **empreinte du texte brut du post** — c'est elle qui permet de dédupliquer les runs suivants, les URLs `lnkd.in` n'étant pas stables. Calculée au harvest, transportée par `a_scorer.json`, **à recopier telle quelle par les agents de scoring**. |
| 21 | `validation` | **Vide, menu OUI/NON** — à remplir par l'humain |
| 22 | `motif` | **Vide, texte libre** — à remplir par l'humain |

## Onglet `SUIVI_LEADS`

`lead | organisation | annonce | url_post | contact | mail | type_opportunite | score |
statut_lead | <les 5 textes> | notes`

Statuts : `À contacter → Contacté → Relancé → En discussion → RDV/Entretien → Gagné | Perdu/Sans réponse`

## Mise en forme

- Arial 10, en-têtes blancs sur `1F3864`.
- **Colonnes à remplir par l'humain** : en-tête doré `BF8F00`, cellules `FFF2CC`. Le signal visuel
  « ici c'est à toi » évite d'avoir à expliquer le mode d'emploi.
- Score : vert `C6EFCE` au-dessus du seuil de rédaction, jaune `FFEB9C` au-dessus du seuil de
  conservation. Jamais colorié si un filtre est déclenché.
- URLs en hyperliens cliquables, `freeze_panes="A2"`, `auto_filter` sur toute la plage,
  `wrap_text` sur les colonnes longues uniquement, listes déroulantes sur `validation` et `statut_lead`.

## Pièges openpyxl (rencontrés en conditions réelles)

- **`delete_rows` est peu fiable** : il a laissé 283 lignes fantômes sur un nettoyage. Pour retirer
  des lignes, **reconstruire l'onglet de zéro** (lire les valeurs → nouvel onglet → réappliquer
  styles, hyperliens et validations).
- Une `DataValidation` doit être **ré-ajoutée sur la plage étendue** après chaque ajout de lignes.
- Recharger et réécrire le classeur préserve les labels humains tant qu'on ne recrée pas l'onglet.

## Livraison

- Sur un run récurrent : le **delta** (lecture en 2 minutes) et le **MASTER** (référence).
- Archiver en parallèle une **copie CSV** du MASTER et du suivi de leads dans l'espace projet :
  c'est ce qui permet à une future conversation de reprendre le fil sans le classeur.
- ⚠️ **Publier un .xlsx sur Google Drive par upload base64 échoue** au-delà de ~35 000 caractères.
  Passer par un export CSV converti en Google Sheets — au prix des menus déroulants et des
  couleurs, que l'on recrée en 10 secondes côté Sheets (Données → Validation des données).
