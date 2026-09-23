# Core 2 — Réservation et réconciliation des PK dans le graphe d'objets, avant tout flush

**Nature** : fonctionnalité

> **Reprise — où en est ce plan**
> Tranche en cours : T3 — le pont session : maxima réels et preuve de bout en bout.
> Dernière case cochée : T2.8 (point d'arrêt atteint le 23/09 — réconciliation livrée : 11 scénarios verts au total, ruff zéro, baseline intacte ; commit en attente du go de Rachid). Leçon du jour consignée : une boucle mutuelle exige `foreign_keys=[...]` explicite sur chaque relation, sinon l'erreur de configuration casse tout le registre.
> Laissé cassé (voulu) : les deux tests rouges de `tests/test_seed.py` spécifient `seed()` — ils attendent les points 3 (Shape API) et 4 (génération de champs) ; ils doivent échouer À L'IDENTIQUE (par `NotImplementedError`) à chaque point d'arrêt de ce plan. Tout autre échec est une régression.
> Règle de travail du 23/09 : je ne committe plus rien. Chaque tranche finie et verte s'arrête sur un point d'arrêt — je remets le message de commit, Rachid committe (ou délègue), et la suite n'attaque qu'à son go.

## Ce que ce plan construit — et ce qu'il ne construit pas

Le point 2 de la roadmap est le cœur battant de la librairie : rendre l'invariant **vrai par construction**. Concrètement : des objets liés existent dans la mémoire Python (une `User` alice, des `Post` dont `post.author` pointe vers alice) — le moteur **réserve** une PK pour chaque objet qui n'en a pas, puis **réconcilie** : il recopie la PK de chaque parent dans les colonnes FK de ses enfants. Résultat vérifiable **avant tout flush** (le moment où SQLAlchemy écrit en base) : `post.author_id == alice.id`, sans qu'une seule ligne n'ait touché la base.

C'est exactement ce que polyfactory ne fait pas (FK aléatoires) et ce qui tuait faker-sqlalchemy. C'est aussi la première moitié du money-shot de la lib — la seconde moitié (construire le graphe depuis une forme déclarée) est le point 3.

Ce plan ne construit pas : `seed()` ne bouge pas (décision Rachid du 23/09 — la Shape API du point 3 la branchera), aucune génération de champs (`name`, `title` — point 4, Faker ; les tests remplissent à la main), aucune résolution de cycles à l'insertion (point 7 — l'invariant tient déjà en mémoire sur une boucle mutuelle, l'INSERT différé viendra plus tard), aucun async (point 8).

L'API cible :

```python
from seedgraph.boundary import existing_maxima
from seedgraph.reconciliation import reconcile_graph

objects = [alice, bob, post1, post2, comment]     # construits par l'appelant (le point 3 fera ça depuis une forme)
reconcile_graph(objects)                          # base vide : PK réservées à partir de 1
reconcile_graph(objects, existing_maxima=existing_maxima(session, User))
# alice.id == 13 (au-dessus du max existant), post1.author_id == alice.id — AVANT tout flush
```

## Passe 1 — `bdd.qa-amigo` : les règles métier, une par une, et les décisions produit

La passe a posé les deux vrais embranchements produit à Rachid (périmètre ; politique anti-collision) et chassé les cas limites avec les sept lunettes — deux d'entre elles ont mordu : la frontière base-existante (parents persistants, collisions) et les états d'objet (transient sans PK, persistant avec PK réelle). Les scénarios vivent dans ce plan et descendent dans `tests/test_reconciliation.py` au fil des tranches.

### Les règles métier

- **R1** — L'invariant se construit dans le graphe d'objets, avant tout flush : la cohérence se prouve sans écrire une ligne en base.
- **R2** — Tout objet dont la PK n'est pas posée reçoit une PK réservée : déterministe, dans l'ordre fourni par l'appelant, un compteur par table et par colonne PK.
- **R3** — Une PK déjà réelle n'est jamais écrasée : l'objet existe, on le respecte (le compteur l'ignore, il ne regarde que les maxima).
- **R4** — Les réservations commencent au-dessus du maximum existant fourni, colonne par colonne ; sans maxima, à partir de 1 (tranché par Rachid — une PK en collision avec une row existante est rejetée par la base, vérifié le 23/09).
- **R5** — Toute relation posée est réconciliée : les colonnes FK locales reçoivent les valeurs de PK du parent lié — depuis le côté enfant (`post.author`) comme depuis le côté collection (`user.posts`), de façon idempotente.
- **R6** — Les parents partagés sont la norme : plusieurs enfants pointent vers le même parent, qui ne reçoit jamais deux réservations.
- **R7** — Les FK composites sont réconciliées colonne par colonne, chaque composante vers sa contrepartie.
- **R8** — Seules les relations adossées à une contrainte FK sont réconciliées — même vérité-de-terrain que Core 1 : les contraintes déclarées, jamais les joins custom.
- **R9** — Le moteur est pur : aucune session, aucun SQL, aucun flush dans `reconciliation.py` ; la lecture des maxima existants vit dans `boundary.py`, seul module qui touche une session.
- **R10** — Un parent lié hors du graphe fourni, dont la PK n'est pas posée, lève `PendingParentError` qui nomme la relation : explicite, jamais de clôture implicite.
- **R11** — Une PK non entière sur un objet à réserver lève `UnsupportedPrimaryKeyError` : la génération de valeurs appartient au point 4, pas ici.
- **R12** — Le résultat est déterministe de bout en bout : mêmes objets, mêmes maxima → mêmes valeurs (principe 4 du README).
- **R13** — `seed()` ne bouge pas, `__init__.py` n'exporte rien de nouveau ; les deux tests rouges restent la spécification des points 3-4.

### Les décisions produit, et qui a tranché

| Décision | Qui a tranché, quand | Le motif |
| --- | --- | --- |
| Moteur seul, `seed()` intact | Rachid, le 23/09/2026 — question de cette passe | L'ordre de la roadmap : la Shape API (point 3) construit le graphe et branche `seed()` ; ici on livre le moteur avec ses propres scénarios, comme Core 1 |
| Réservations au-dessus du max existant | Rachid, le 23/09/2026 — question de cette passe | Principe 6 (« existing rows are usable as parents ») + preuve du lab : une PK en collision est rejetée en `IntegrityError` ; commencer à 1 casserait sur toute base non vide |
| FK composites incluses dans ce point | Le plan, réversible | Le wedge : sqlseed échoue dessus (notes de session §3) ; une tranche dédiée la couvre |
| Liaison par les relations posées, pas par des FK posées à la main | Le plan | Le graphe d'objets est la vérité (principe 2) ; une FK sans relation n'a rien à réconciler |
| Les deux côtés d'une paire réconciliés (idempotent) | Le plan | Vérifié : MANYTOONE et ONETOMANY exposent les mêmes paires de colonnes, aboutissent aux mêmes valeurs |
| PK non entière → erreur explicite, pas de génération | Le plan | La génération de champs est le point 4 ; inventer une valeur ici serait de la généralité spéculative |
| Parent pendante hors graphe → erreur, pas de clôture implicite | Le plan | Explicite > silencieux, l'identité même de la lib ; construire le graphe appartient à la Shape API |
| `metadata_of` promu public dans topology | Le plan | La coercition modèle-ou-metadata devient le style maison, partagée par boundary |
| Témoin négatif de collision conservé comme scénario | Le plan | Prouve empiriquement que la politique max est porteuse — l'argument de défense du point 2 |

## Passe 2 — `acceptance-testing-maker` : les verbes, les pilotes, les exclusions

### Les verbes du langage des scénarios

| Verbe | Ce qu'il dit | Il vit dans quels noms de tests |
| --- | --- | --- |
| réserver | les PK des objets sans identité reçoivent une valeur, toujours la même | `assigns_ids_above_existing_maxima`, `starts_at_one_without_maxima`, `reserve_composite_pk_per_column`, `is_deterministic` |
| réconcilier | les FK des enfants reçoivent les PK de leurs parents liés | `copies_parent_pk_into_fk_columns`, `supports_shared_parents`, `from_the_collection_side`, `reconcile_composite_fk_pairs_each_column` |
| respecter | une PK réelle existe déjà : on ne la touche pas, on la réutilise | `never_overwrites_a_real_pk`, `reuses_a_persistent_parent_real_pk` |
| refuser | un graphe bancal lève une erreur qui nomme le coupable | `pending_parent_outside_graph_raises`, `unsupported_pk_type_raises` |
| prouver | la base vivante accepte le graphe réconcilié, contraintes actives | `full_flow_flushes_without_fk_violation`, `composite_flow_flushes`, `without_maxima_collides_at_flush` |

### Les pilotes : qui rejoue quoi

Deux pilotes cette fois — contrairement à Core 1, la preuve exige une vraie base :

- **Pilote « objets purs en mémoire »** : les tranches T1 et T2 entières. Des objets ORM transients construits à la main, zéro session, zéro base — la réservation et la réconciliation se prouvent sur des valeurs, pas sur des écritures. Retour attendu : la seconde.
- **Pilote « session SQLite vivante »** : les tranches T3 et T4. SQLite en mémoire avec **application des FK vraiment active** — l'écouteur `PRAGMA foreign_keys=ON` enregistré **avant** la première connexion (leçon du lab : après, il ne s'applique jamais à la connexion déjà poolée), et `commit()` pour que les données de préparation survivent à la fermeture de session. Ce pilote prouve l'invariant bout en bout : pré-existant → réserver au-dessus → réconcilier → flush → zéro violation.

### Les exclusions, avec leur motif

- Intégration via `seed()` — exclue : point 3, décision Rachid du 23/09 ; les deux tests rouges restent la spécification.
- Faker / champs NOT NULL — exclus : point 4 ; les tests remplissent `name="alice"` à la main.
- Flush d'une boucle mutuelle — exclu : point 7 ; l'invariant tient déjà en mémoire (scénario T2.6 sans flush), l'INSERT différé viendra avec le support des cycles.
- PostgreSQL / séquences — exclu, **limitation documentée** : des ids explicites n'avancent pas les séquences PG (un auto-insert ultérieur peut collider) ; matrice de test SQLite only, à rouvrir en point de roadmap dédié.
- PK non entières (UUID, texte) — exclues : génération de valeurs = point 4 ; ici : erreur explicite.
- Property-based (Hypothesis), benchmarks, async — exclus : mêmes motifs que Core 1 (déterminisme table-driven, O(n) par construction, point 8).

## Passe 3 — `craft-coach` : où vit chaque règle, les frontières, les noms

### Où vit chaque règle métier

| Règle | Elle vit où | Elle est figée par |
| --- | --- | --- |
| R1 invariant avant flush | `reconcile_graph()` dans `src/seedgraph/reconciliation.py` + l'oracle de test | tous les scénarios T2 + T3.3 |
| R2 + R4 réservation déterministe au-dessus du max | `_reserve_primary_keys()` (compteurs par table/colonne) | T1.1, T1.2, T1.4, T4.1 |
| R3 jamais écraser une PK réelle | le garde dans `_reserve_primary_keys()` | T1.3 |
| R5 réconciliation des deux côtés | `_reconcile_foreign_keys()` (paires `local_remote_pairs`, vérifiées) | T2.1, T2.3 |
| R6 parents partagés | aucune PK réservée deux fois — les compteurs par table | T2.2 |
| R7 + composites | `_reconcile_foreign_keys()` colonne par colonne | T4.1, T4.2, T4.3 |
| R8 relations adossées à une contrainte | le filtre de `_reconcile_foreign_keys()` sur les relations dont les colonnes locales sont des colonnes de contrainte | mécanique vérifiée à l'implémentation, comme Core 1 |
| R9 moteur pur / adaptateur séparé | `reconciliation.py` sans session ; `boundary.py` seul à en toucher une | l'import lui-même + T3.2 |
| R10 parent pendante hors graphe | `PendingParentError` levée par `_reconcile_foreign_keys()` | T2.5 |
| R11 PK non entière | `UnsupportedPrimaryKeyError` levée par `_reserve_primary_keys()` | T1.5 |
| R12 déterminisme de bout en bout | compteurs + ordre fourni ; l'oracle re-vérifie | T1.4 + T3.3 |
| R13 seed() intact | rien ne change dans `__init__.py` ni `tests/test_seed.py` | le pytest complet à chaque point d'arrêt |

### Ce qui ne doit pas fuir où

- `reconciliation.py` ne connaît que des instances ORM et leur introspection mapper : jamais de session, jamais de SQL exécuté, jamais de flush. Le jour où une session entre dans ce fichier, la frontière est cassée.
- `boundary.py` est le seul module qui touche une session — il lit, il ne réserve ni ne réconcilie jamais.
- Aucune génération de champs nulle part : `name`, `title`, `body` sont remplis par l'appelant (les tests à la main, la Shape API au point 3, Faker au point 4).
- L'oracle d'invariant (`assert_referentially_consistent`) vit dans `tests/`, pas dans `src/` : c'est le jugement du test, pas une API.
- `topology.py` ne bouge pas, à une exception près : `_metadata_of` devient public `metadata_of` (T3.1), parce que `boundary` en a besoin — le style maison « modèle ou metadata » se partage.
- `__init__.py` n'exporte rien de nouveau : `__all__` reste `["__version__", "seed"]`.

### Les noms — et les rejets

- `seedgraph/reconciliation.py` — retenu : le vocabulaire même du README (« PK reservation/reconciliation »). Rejetés : `pk.py` (jargon), `reserve.py` / `reconcile.py` (chacun la moitié du métier).
- `reconcile_graph(objects, existing_maxima=None) -> None` — retenu : « graph » est l'identité de la lib ; mutation en place, retourne `None`. Rejetés : `prepare(objects)` (flou), `reconcile(objects)` (oublie la réservation), un retour de compteur (personne ne le consomme).
- `seedgraph/boundary.py` + `existing_maxima(session, source) -> dict[str, dict[str, int]]` — retenu : le principe 6 du README s'appelle littéralement « stop at the boundary » ; ce module lit ce qui existe à la frontière. Rejetés : `maxima.py` (jargon), `session_utils.py` (fourre-tout). Clés : `table.key` → {colonne PK : max, 0 si vide}.
- `UnsupportedPrimaryKeyError` — retenu : nomme la maladie (ce type de PK ne se réserve pas). Rejeté : `InvalidPKError` (vague).
- `PendingParentError` — retenu : le parent lié n'a pas de PK et n'est pas du graphe fourni. Rejeté : `OrphanParentError` (l'orphelin, c'est l'enfant sans parent — ici c'est l'inverse).
- Internes : `_reserve_primary_keys`, `_reconcile_foreign_keys` — un verbe chacun, aucun ne dépasse le module.
- `metadata_of` (ex-`_metadata_of`) — la coercition maison modèle-ou-metadata, désormais publique et partagée.

## Passe 4 — `cd-enforcer` : les tranches, leur ordre, leurs preuves — et le nouveau protocole d'arrêt

Quatre tranches, dans cet ordre : **T1 réserver** (moteur pur) → **T2 réconcilier** (moteur pur) → **T3 prouver en base** (le pont session) → **T4 composites**. T1 avant T2 parce qu'une FK réconciliée copie une PK qui doit déjà exister ; T3 après T2 parce qu'elle prouve en base ce que le moteur fait déjà en mémoire ; T4 en dernier parce qu'elle complète un socle déjà prouvé.

Chaque tranche est livrable seule : additive, sans drapeau (chaque fonction est entière à sa tranche — `reconcile_graph` existe dès T1, sa moitié réconciliation atterrit à T2), testée verte avant l'arrêt.

**Le protocole d'arrêt (règle de travail du 23/09)** : à chaque tranche finie et verte, je m'arrête — code et tests prêts pour UN commit atomique, message de commit remis, et je n'attaque la tranche suivante qu'au go de Rachid, qui committe lui-même. L'atomicité code+tests est préservée ; seul l'acteur change.

- **Preuve que T1 se livre seule** : les scénarios de réservation verts sur des objets purs ; commit purement additif (`reconcile_graph` importable et utile dès l'arrêt) ; rien d'existant ne bouge.
- **Preuve que T2 se livre seule** : l'invariant tient en mémoire sur tous les scénarios de liaison, parents partagés compris, et les deux refus (`PendingParentError`, parents persistants respectés) sont nommés.
- **Preuve que T3 se livre seule** : la preuve de bout en bout avec FK actives — pré-existant commité, réservations qui continuent au-dessus, flush sans violation — plus le témoin négatif qui prouve que la politique max est porteuse ; `metadata_of` promotion incluse.
- **Preuve que T4 se livre seule** : composites réservés colonne par colonne, réconciliés colonne par colonne, flush composite sans violation ; la case roadmap du README cochée dans le même commit.
- **La baseline rouge, assumée** : `python -m pytest` sortira non-vert tant que les points 3-4 ne seront pas livrés — même clause que Core 1 : les deux tests de `seed()` échouent À L'IDENTIQUE (par `NotImplementedError`), jamais autrement. Pré-alpha, aucun utilisateur.
- **Rituel avant chaque point d'arrêt** : pytest ciblé tout vert ; pytest complet = exactement les deux rouges connus ; `ruff check src tests` à zéro.

## Notes techniques — vérifiées en vrai le 23/09/2026 (SQLAlchemy 2.0.54, venv du projet)

- Les paires de colonnes existent telles quelles : `Post.author` (MANYTOONE) → `[(author_id, id)]` ; `User.posts` (ONETOMANY) → `[(id, author_id)]` ; composite `OrderItem.order` → `[(k1, k1), (k2, k2)]`. La réconciliation se lit dans ces paires, côté par côté, de façon idempotente.
- Poser une PK à la main sur un objet transient (`alice.id = 11`) puis flusher insère l'id explicite — la voie est libre.
- **Piège FK SQLite** : l'écouteur `connect` qui pose `PRAGMA foreign_keys=ON` doit être enregistré **avant** la première connexion (donc avant `create_all`) — sinon le pragma ne s'applique jamais à la connexion déjà poolée, et les violations passent en silence. Tombé dessus au lab ; les fixtures font dans l'ordre.
- Une `Session` refermée sans `commit()` **annule tout** (rollback automatique) : les fixtures qui veulent persister des rows de préparation commitent explicitement.
- FK fantôme → `IntegrityError` ; **PK réservée en collision avec une row existante → `IntegrityError`** — la preuve empirique derrière la décision max de Rachid.
- `inspect(obj).persistent` distingue une row chargée d'un transient (dont la PK est `None`) — le moteur s'en sert pour « jamais écraser ».
- Cascade `save-update` : ajouter un parent à la session tire ses enfants liés — les tests font `add_all` quand même, pas de dépendance à la cascade.
- **Limite connue, documentée** : sur PostgreSQL, des ids explicites n'avancent pas les séquences — un auto-insert ultérieur peut collider. Hors périmètre, à rouvrir en point dédié.

## Tranche 1 — réserver les PK (moteur pur)

Chaque scénario s'écrit rouge d'abord (le module n'existe pas : `ImportError`), puis passe au vert. Aucune base n'est ouverte dans cette tranche.

- [x] T1.1 — `test_reserve_assigns_ids_above_existing_maxima` : trois `User` sans PK, `existing_maxima={"users": {"id": 10}}` → ids 11, 12, 13, dans l'ordre fourni — rouge d'abord
- [x] T1.2 — `test_reserve_starts_at_one_without_maxima` : mêmes objets, `existing_maxima=None` → 1, 2, 3
- [x] T1.3 — `test_reserve_never_overwrites_a_real_pk` : un objet du lot a déjà `id=999` → il reste à 999, les autres sont réservés normalement
- [x] T1.4 — `test_reserve_is_deterministic_across_rebuilds` : reconstruire le même input deux fois → exactement les mêmes valeurs (principe 4)
- [x] T1.5 — `test_unsupported_pk_type_raises` : un modèle à PK `Text` sans valeur → `UnsupportedPrimaryKeyError`, le message nomme la table et la colonne
- [x] T1.6 — point d'arrêt : remettre le message de commit `feat(reconciliation): reserve deterministic primary keys above existing maxima` et attendre le go — pytest ciblé vert, pytest complet = les deux rouges connus à l'identique, ruff à zéro

## Tranche 2 — réconcilier les FK depuis les liens (moteur pur, avant tout flush)

L'invariant en miniature vit ici : `post.author_id == alice.id` alors qu'aucune base n'a vu passer quoi que ce soit.

- [x] T2.1 — `test_reconcile_copies_parent_pk_into_fk_columns` : `post.author = alice` posé → `post.author_id == alice.id` après `reconcile_graph`, SANS flush — rouge d'abord
- [x] T2.2 — `test_reconcile_supports_shared_parents` : un auteur, trois posts ; un comment dont `author` ∈ users → toutes les FK pointent vers les PK réservées des mêmes parents
- [x] T2.3 — `test_reconcile_from_the_collection_side` : lien posé depuis le parent (`user.posts = [...]`) → les FK des enfants sont posées quand même (côté ONETOMANY)
- [x] T2.4 — `test_reconcile_reuses_a_persistent_parent_real_pk` : un parent à PK réelle 17 (chargé ou pré-rempli) → FK = 17, le parent intact — la frontière du principe 6
- [x] T2.5 — `test_pending_parent_outside_graph_raises` : `post.author` pointe vers un objet hors de la liste fournie, sans PK → `PendingParentError`, le message nomme la relation
- [x] T2.6 — `test_reconcile_mutual_references_without_flush` : deux objets liés dans les deux sens → les deux FK sont posées, l'invariant tient en mémoire (le flush d'une boucle attend le point 7)
- [x] T2.7 — l'oracle `assert_referentially_consistent(objects)` : pour chaque contrainte FK de chaque table, la valeur posée est la PK d'un objet du graphe, lié par la relation — utilisé par tous les scénarios ci-dessus
- [x] T2.8 — point d'arrêt : remettre le message de commit `feat(reconciliation): reconcile FK columns from linked parents before any flush` et attendre le go — rituel identique

## Tranche 3 — le pont session : maxima réels et preuve de bout en bout

La tranche qui prouve. SQLite en mémoire, FK **réellement** actives (écouteur avant `create_all`), commits pour persister les rows de préparation.

- [ ] T3.1 — refactor : `_metadata_of` devient `metadata_of` publique dans `topology.py` (aucun comportement change ; couvert par les tests existants de Core 1) — rouge d'abord : `boundary` ne peut pas l'importer
- [ ] T3.2 — `test_existing_maxima_reads_real_maxima` : des rows commitées → `existing_maxima(session, User)` rend `{"users": {"id": 12}, ...}` ; table vide → 0
- [ ] T3.3 — `test_full_flow_flushes_without_fk_violation` : pré-existant commité (users jusqu'à 12) → construire à la main alice, bob, posts, comments → `existing_maxima` → `reconcile_graph` → oracle → `add_all` → `flush` : zéro `IntegrityError`, comptes exacts, ids réservés qui continuent au-dessus de l'existant
- [ ] T3.4 — `test_seeding_without_maxima_collides_at_flush` : le témoin négatif — même base non vide, réservation SANS maxima (à partir de 1) → le flush lève `IntegrityError` : la politique max est porteuse, la preuve est dans le test
- [ ] T3.5 — point d'arrêt : remettre le message de commit `feat(boundary): read existing maxima and prove the full flow flushes clean` et attendre le go — rituel identique

## Tranche 4 — les composites, de bout en bout

La complétude différenciante : sqlseed échoue ici, seedgraph non.

- [ ] T4.1 — `test_reserve_composite_pk_per_column` : trois `Order` sans PK, maxima par colonne → `(k1, k2)` reçoivent (11, 21), (12, 22), (13, 23) — un compteur par colonne, des tuples uniques — rouge d'abord
- [ ] T4.2 — `test_reconcile_composite_fk_pairs_each_column` : `order_item.order = order1` → `order_item.k1 == order1.k1` ET `order_item.k2 == order1.k2`
- [ ] T4.3 — `test_composite_flow_flushes` : bout en bout sur session avec FK actives : orders + order_items réconciliés → flush sans violation
- [ ] T4.4 — case roadmap cochée dans le README (`- [x]` PK reservation/reconciliation) — partie du même commit
- [ ] T4.5 — point d'arrêt final : remettre le message de commit `feat(reconciliation): cover composite primary keys end to end` et attendre le go — rituel identique, puis archivage du plan dans `ai/plans/done/`

## Vérifications locales — avant chaque point d'arrêt

```bash
source .venv/bin/activate
python -m pytest tests/test_reconciliation.py   # la tranche courante : tout vert
python -m pytest                                # exactement les deux rouges connus (NotImplementedError), rien d'autre
ruff check src tests                             # zéro alerte
```
