# Core 1 — Topologie du graphe FK depuis les modèles : ordre topologique, détection de cycles

**Nature** : fonctionnalité

> **Reprise — où en est ce plan**
> Tranche en cours : aucune — le plan est terminé.
> Dernière case cochée : T2.11 (commit 8cc9796 — l'ordre et le refus sont livrés, 20 scénarios verts, case roadmap cochée dans le README).
> Laissé cassé (voulu) : les deux tests rouges de `tests/test_seed.py` — `test_seed_returns_consistent_graph` et `test_seed_persists_without_fk_violation` — spécifient `seed()`, qui attend les points 2 et 3 de la roadmap. Ils doivent rester rouges À L'IDENTIQUE (échec par `NotImplementedError`) à chaque commit de ce plan ; tout autre échec est une régression.

## Ce que ce plan construit — et ce qu'il ne construit pas

Le point 1 de la roadmap demande le cœur du moteur : partir des modèles SQLAlchemy de l'utilisateur (plus précisément de leur *metadata*, l'objet qui recense toutes les tables déclarées par les modèles), en déduire le graphe des dépendances par clé étrangère, le mettre en ordre topologique (un classement où toute table référencée vient avant les tables qui pointent vers elle — les parents d'abord), et détecter les cycles (les boucles de références qui rendent cet ordre impossible).

Ce plan ne construit pas le reste : `seed()` ne change pas (il lève toujours `NotImplementedError`), aucune réservation de PK (point 2), aucune Shape API (point 3), aucune résolution des cycles à l'exécution (point 7 — ici on les détecte et on les refuse proprement). Le module livré est le moteur que les points suivants consommeront ; il se teste directement, et c'est voulu.

L'API cible, toute petite :

```python
from seedgraph.topology import CyclicFKGraphError, dependency_graph, topological_order

dependency_graph(User)        # ou Base.metadata en entrée directe
# {"users": set(), "posts": {"users"}, "comments": {"users", "posts"}}

topological_order(User)       # ou Base.metadata
# [Table("users", ...), Table("posts", ...), Table("comments", ...)]  — parents d'abord

topological_order(metadata_avec_boucle_mutuelle)
# lève CyclicFKGraphError, avec exc.groups == (("departments", "employees"),)
```

## Passe 1 — `bdd.qa-amigo` : les règles métier, une par une, et les décisions produit

La passe a posé deux questions à Rachid (les deux vrais embranchements produit du module) et chassé les cas limites avec les sept lunettes du skill. Les scénarios consignés vivent dans ce plan et descendent dans `tests/test_topology.py` au fil des tranches — pas de fichier `.feature` dans ce repo.

### Les règles métier

- **R1** — La source d'entrée est le modèle ou son metadata : toute fonction publique accepte une classe mappée SQLAlchemy ou un objet `MetaData`, jamais un schéma SQL brut (principe 1 du README : model-first).
- **R2** — Une arête du graphe correspond à une contrainte de clé étrangère entre deux tables du même metadata ; une FK composite (plusieurs colonnes) compte pour une seule arête.
- **R3** — Une FK dont la table cible n'existe pas dans le metadata est ignorée : ni arête, ni erreur — la frontière s'arrête au metadata donné (vérifié le 22/09 : `sorted_tables` de SQLAlchemy plante sur ce cas ; seedgraph ne le fera pas).
- **R4** — Le graphe se construit toujours, même sur un schéma cyclique : une auto-référence apparaît comme arête vers soi-même, une arête `use_alter` apparaît comme arête ordinaire — rien n'est caché.
- **R5** — Une auto-référence ne bloque jamais l'ordre entre tables : le parent d'une ligne de la table en est une autre ligne — c'est un ordre de lignes, pas de tables (tranché par Rachid).
- **R6** — Une arête déclarée `use_alter=True` ne bloque pas l'ordre : l'utilisateur a dit « cette contrainte se posera après coup » ; on le croit (tranché par Rachid).
- **R7** — L'ordre est strictement parents d'abord : toute table référencée précède toute table qui la référence, sans exception.
- **R8** — L'ordre et le refus sont déterministes : même contenu de metadata → même sortie, quel que soit l'ordre de déclaration des tables ; les égalités se départagent alphabétiquement ; le contenu des groupes de boucle est trié.
- **R9** — Une boucle entre plusieurs tables sans échappatoire `use_alter` rend l'ordre strict impossible : `CyclicFKGraphError` lève alors, portant `.groups`, les groupes exacts de tables en boucle fermée.
- **R10** — L'erreur ne nomme que des coupables : les groupes contiennent uniquement les tables cycliques, jamais les tables saines du même metadata.
- **R11** — Aucun algorithme ne récursionne : 3000 tables en chaîne ou en anneau passent sans `RecursionError` (la récursion a tué faker-sqlalchemy — notes de session §3).
- **R12** — Deux tables de même nom dans deux schémas SQL distincts sont deux nœuds distincts.
- **R13** — Les cas limites sont définis : metadata vide → graphe vide et ordre vide ; deux FK d'une même table vers la même cible → une seule arête.
- **R14** — `seed()` et ses deux tests rouges ne bougent pas : cette tranche n'expose rien depuis `__init__.py`.

### Les décisions produit, et qui a tranché

| Décision | Qui a tranché, quand | Le motif |
| --- | --- | --- |
| L'auto-référence ne bloque pas l'ordre (visible dans le graphe, tolérée à l'ordonnancement) | Rachid, le 22/09/2026 — question de cette passe | Le parent d'une `Category` est une autre ligne de la même table : ordre de lignes, pas de tables ; principe du README « self-references are normal » |
| Une arête `use_alter=True` ne bloque pas l'ordre | Rachid, le 22/09/2026 — question de cette passe | Idiome SQLAlchemy déclaré par l'utilisateur lui-même ; « model-first » = respecter ce que les modèles déclarent |
| Boucle multi-tables sans échappatoire → erreur structurée, jamais d'ordre dégradé en silence | La roadmap (point 1 « detection », point 7 « support »), reprise par le plan | `sorted_tables` casse les boucles en silence avec un simple warning : l'échec silencieux est précisément l'ennemi que seedgraph existe pour tuer |
| Pas d'ordre de condensation (groupes de boucle ordonnés entre eux) dans cette tranche | Le plan, réversible au point 7 | Aucun consommateur avant le point 7 ; le construire maintenant serait de la généralité spéculative |
| Pas de filtrage « tables utiles au seed » | Le plan | C'est le travail de la Shape API (point 3) ; l'ordre du metadata complet reste un ordre valide pour toutes les tables |
| Les arêtes viennent des contraintes FK déclarées, pas des `relationship()` à `primaryjoin` custom | Le plan | La contrainte est la vérité de terrain de l'ordonnancement ; un join custom sans contrainte ne crée aucune colonne FK à réconcilier |
| `topological_order` rend des objets `Table`, pas des noms | Le plan | Les tranches suivantes itèrent leurs contraintes et colonnes ; le nom reste à un `t.name` d'appel |
| La base `SeedgraphError` naît avec la première exception | Le plan | Une ligne de code ; la famille `except SeedgraphError` existe dès le premier jour pour qui adopte le module tôt |

## Passe 2 — `acceptance-testing-maker` : les verbes, les pilotes, les exclusions

### Les verbes du langage des scénarios

| Verbe | Ce qu'il dit | Il vit dans quels noms de tests |
| --- | --- | --- |
| construire | le graphe des dépendances se lit depuis les modèles | `builds_edges_from_model_metadata`, `composite_fk_counts_as_one_edge`, `use_alter_edge_is_visible_in_graph` |
| ordonner | les parents viennent d'abord, toujours dans le même ordre | `puts_parents_first`, `is_deterministic_regardless_of_definition_order`, `respects_every_fk_edge`, `fk_free_metadata_sorts_by_name` |
| refuser | une boucle non déclarée lève une erreur qui nomme ses coupables | `raises_cyclic_fk_graph_error`, `lists_only_cyclic_tables` |
| ignorer | une FK vers une table absente ne crée ni arête ni drame | `fk_to_missing_target_table_is_ignored` |
| tolérer | l'auto-référence et le `use_alter` ne bloquent rien | `self_reference_does_not_block_order`, `use_alter_does_not_block_order` |

### Les pilotes : qui rejoue quoi

Un seul pilote rejoue tout : « l'appel direct en mémoire ». Les scénarios sont des fonctions pytest qui construisent des objets `MetaData` et appellent le module — zéro base de données, zéro session, zéro engine, la topologie est une lecture pure des modèles. Les `Table` du cœur SQLAlchemy suffisent comme fixtures ; l'ORM n'intervient que dans le scénario d'entrée par classe mappée (R1), ce qui évite les collisions de registre declarative entre tests. Temps de retour attendu : la seconde.

### Les exclusions, avec leur motif

- Pilote « session SQLAlchemy vivante » (SQLite en mémoire, comme `test_seed.py`) — exclu : la topologie ne touche jamais une base ; brancher SQLite testerait SQLite, pas notre ordre.
- Pilote « via `seed()` » — exclu : `seed()` reste `NotImplementedError` jusqu'aux points 2-3 ; ses deux tests rouges sont la spécification, pas le terrain de cette tranche.
- Fichiers Gherkin `.feature` — exclus : repo pytest pur ; le langage des scénarios vit dans les noms des tests (la convention du repo veut que le nom du test fige la règle).
- Property-based testing (Hypothesis) — exclu : les entrées sont des graphes déterministes construits à la main, le table-driven couvre ; le coût n'est pas justifié en pré-alpha.
- Benchmarks — exclus : les algorithmes sont O(tables + arêtes) par construction ; pas de budget de performance à défendre.
- Couverture multi-dialectes — exclue : aucun dialecte n'est impliqué, aucune base n'est ouverte.

## Passe 3 — `craft-coach` : où vit chaque règle, les frontières, les noms

### Où vit chaque règle métier

| Règle | Elle vit où | Elle est figée par |
| --- | --- | --- |
| R1 entrée modèle ou metadata | `src/seedgraph/topology.py`, `_metadata_of()` | T1.1 + T1.2 |
| R2 + R13 arêtes, composite, doublons, vide | `_declared_edges()` | T1.3 + T1.8 + T1.9 |
| R3 FK fantôme ignorée | `_declared_edges()` (try/except `NoReferencedTableError`) | T1.4 |
| R4 le graphe se construit toujours | `dependency_graph()` lui-même | T1.5 + T1.6 |
| R5 auto-référence tolérée à l'ordre | `_ordering_edges()` retire les arêtes vers soi-même | T2.5 |
| R6 `use_alter` non bloquant | `_ordering_edges()` retire les arêtes `use_alter` | T2.6 |
| R7 parents d'abord | `_kahn_order()` + le vérificateur de test | T2.1 + T2.3 |
| R8 déterminisme | départage alphabétique dans `_kahn_order()`, tri des groupes dans `_cyclic_groups()` | T2.2 |
| R9 refus des boucles non déclarées | `CyclicFKGraphError` (`.groups`) + `_cyclic_groups()` | T2.7 |
| R10 erreur ciblée | l'erreur est construite depuis les seuls groupes cycliques | T2.8 |
| R11 itératif partout | `_kahn_order()` et `_cyclic_groups()` sans un seul appel récursif | T2.9 + T2.10 |
| R12 schémas distincts | clés `table.key` partout | T1.7 |
| R14 `seed()` intact | rien ne change dans `__init__.py` ni `tests/test_seed.py` | le pytest complet à chaque commit |

### Ce qui ne doit pas fuir où

- `topology.py` ne connaît que des objets de schéma SQLAlchemy (`MetaData`, `Table`, `ForeignKeyConstraint`) — jamais de session, d'engine, de dialecte, de flush, de valeurs de PK, de génération de lignes, de forme (`relation=n`). Le jour où une de ces notions entre dans ce fichier, la frontière est cassée.
- Le vérificateur « parents d'abord » vit dans `tests/test_topology.py`, pas dans `src/` : c'est un oracle de test, pas une API.
- Pas de structure d'arête riche (contrainte, drapeau `use_alter`, colonnes) avant que le point 7 n'en ait besoin : `dependency_graph` rend des noms, un point c'est tout.
- `__init__.py` n'exporte rien de nouveau : `__all__` reste `["seed", "__version__"]`.

### Les noms — et les rejets

- `seedgraph/topology.py` — retenu : dit ce que le module calcule. Rejetés : `graph.py` (générique — le repo s'appelle déjà seedgraph), `fkgraph.py` (jargon), `ordering.py` (oublie la moitié du métier : les cycles).
- `dependency_graph(source) -> dict[str, set[str]]` — retenu : le vocabulaire standard du domaine. Rejeté : `fk_dependencies` (plus long, pas plus clair).
- `topological_order(source) -> list[Table]` — retenu : c'est exactement le retour. Rejetés : `sort_tables` (imiter SQLAlchemy brouille la marque), `insert_order` (l'ordre des objets du graphe précède l'ordre d'insertion — le nom mentirait dès le point 2).
- `CyclicFKGraphError` — retenu : nomme la maladie (une boucle dans le graphe des FK), pas l'entrée ni le symptôme. Rejeté : `CyclicMetadataError` (nomme l'entrée). Porte `.groups : tuple[tuple[str, ...], ...]`.
- `SeedgraphError` dans `src/seedgraph/exceptions.py` — la base de toutes les futures exceptions du package, une ligne de code.
- Internes : `_metadata_of`, `_declared_edges`, `_ordering_edges`, `_kahn_order`, `_cyclic_groups` — un verbe chacun, aucun ne dépasse le module.

## Passe 4 — `cd-enforcer` : les tranches, leur ordre, leurs preuves de livrabilité

Deux tranches, dans cet ordre : T1 (lire — le graphe), puis T2 (juger — l'ordre et le refus). T1 avant T2 parce que l'ordre et le refus se calculent sur le graphe ; l'inverse n'a aucun sens. Chaque tranche est une part livrable seule (un commit sur main, additive, sans drapeau de fonctionnalité — il n'y a rien d'incomplet exposé : chaque fonction est entière à sa tranche).

- **Preuve que T1 se livre seule** : tous les scénarios du graphe verts ; le commit est purement additif (`seed()` intact, `__init__` intact) ; le module est importable et utile à la minute du commit (diagnostic d'un schéma) ; `ruff` et pytest passent avec la baseline décrite ci-dessous.
- **Preuve que T2 se livre seule** : tous les scénarios d'ordre et de refus verts ; la case roadmap du README cochée dans le même commit (la documentation fait partie du commit, jamais du « plus tard ») ; aucune régression ; `ruff` et pytest baseline inchangée.
- **La baseline rouge, assumée** : `python -m pytest` sortira non-vert sur main pendant toute cette tranche, à cause des deux tests de `seed()` qui spécifient les points 2-3. C'est la spécification déclarée du repo (la docstring de `test_seed.py` : « The first red test ») — l'équivalent d'un test en attente d'implémentation, pas une régression cachée. Pré-alpha : aucun utilisateur, rien de publié. Le critère de non-régression est précis : ces deux tests échouent À L'IDENTIQUE (par `NotImplementedError`), jamais autrement.
- **Trunk-based** : tout part sur main directement, un commit par tranche, chaque commit tient dans une session courte. Pas de branche.
- **Rituel avant chaque push** : pytest + ruff en local ; après un pull, on rejoue avant de pousser.

## Notes techniques — vérifiées en vrai le 22/09/2026 (SQLAlchemy 2.0.54, venv du projet)

- `table.foreign_key_constraints` se parcourt sans résoudre les cibles ; résoudre `fk.column` lève `sqlalchemy.exc.NoReferencedTableError` quand la table cible n'existe pas dans le metadata → try/except, c'est la règle R3. Vérifié : `sorted_tables` de SQLAlchemy plante exactement sur ce cas.
- Une FK composite est UN seul objet `ForeignKeyConstraint` → une seule arête (R2). Vérifié.
- `constraint.use_alter` se lit directement (booléen) ; `sorted_tables` avec `use_alter=True` ordonne sans aucun warning — c'est bien l'idiome de déverrouillage. Vérifié.
- Les clés de nœuds sont `table.key` : `"categories"` sans schéma, `"app.shared"` avec — deux tables de même nom dans deux schémas ne se confondent pas (R12). Vérifié.
- `sorted_tables` casse les boucles mutuelles en silence (un simple `SAWarning`, les contraintes en boucle sont ignorées) : c'est exactement le comportement que seedgraph refuse — le refus explicite de T2 est un différenciateur, pas un détail.
- Kahn itératif avec file des tables prêtes triée par clé = l'ordre déterministe gratuit ; les groupes de boucle se calculent par composantes fortement connexes (les îlots de tables qui se référencent en boucle fermée) en version itérative — Kosaraju ou Tarjan avec pile explicite, la récursion est interdite (R11).
- Le contenu de chaque groupe est trié alphabétiquement, et les groupes sont triés entre eux → l'erreur elle-même est déterministe (R8 s'applique au refus aussi).

## Tranche 1 — le graphe FK se lit depuis les modèles

Chaque scénario s'écrit rouge d'abord (le test échoue avant l'implémentation, comme le fondateur `test_seed.py`), puis passe au vert. Le commit de fin de tranche est atomique : code et tests ensemble, jamais l'un sans l'autre.

- [x] T1.1 — `test_dependency_graph_builds_edges_from_model_metadata` : le schéma ORM `User ← Post ← Comment` (reconstruit dans `tests/test_topology.py`) donne exactement `{"users": set(), "posts": {"users"}, "comments": {"users", "posts"}}` — rouge d'abord : `seedgraph.topology` n'existe pas (ImportError)
- [x] T1.2 — `test_dependency_graph_accepts_metadata_object` : le même schéma passé en `Base.metadata` direct donne le même graphe (R1 : modèle OU metadata)
- [x] T1.3 — `test_composite_fk_counts_as_one_edge` : `order_items` porte une FK composite vers `orders` → une seule arête
- [x] T1.4 — `test_fk_to_missing_target_table_is_ignored` : `externals.ghost_id → ghosts.id`, table `ghosts` jamais déclarée → pas d'arête, aucune exception
- [x] T1.5 — `test_self_referential_fk_is_visible_in_graph` : `categories.parent_id → categories.id` → l'arête `categories → categories` est dans le graphe, aucune erreur
- [x] T1.6 — `test_use_alter_edge_is_visible_in_graph` : `departments.head_id → employees.id` avec `use_alter=True` → l'arête est dans le graphe (son non-blocage à l'ordre viendra en T2)
- [x] T1.7 — `test_same_name_in_two_schemas_is_two_nodes` : `"shared"` et `"app.shared"` coexistent → deux nœuds distincts, une arête de l'un pointe sur le bon
- [x] T1.8 — `test_two_fks_to_same_table_yield_one_edge` : une table avec `from_id` et `to_id` vers `users` → une seule arête
- [x] T1.9 — `test_empty_metadata_yields_empty_graph` : metadata sans aucune table → `{}`, sans erreur
- [x] T1.10 — commit atomique `feat(topology): build the FK dependency graph from model metadata` : code + tests dans le même commit, `ruff check src tests` vert, `python -m pytest tests/test_topology.py` tout vert, `python -m pytest` complet montre exactement les deux rouges connus, à l'identique

## Tranche 2 — l'ordre strict, et le refus explicite des boucles non déclarées

Même rituel : rouge d'abord, vert ensuite, commit atomique à la fin. Le refus d'une boucle non déclarée est le cœur métier de cette tranche — `sorted_tables` dégrade en silence, seedgraph refuse à voix haute et nomme les coupables.

- [x] T2.1 — `test_topological_order_puts_parents_first` : `User ← Post ← Comment` → `[users, posts, comments]` dans cet ordre exact — rouge d'abord : la fonction n'existe pas
- [x] T2.2 — `test_order_is_deterministic_regardless_of_definition_order` : deux metadata décrivant les mêmes tables, déclarées dans l'ordre inverse, avec des tables sans relation entre elles → le même ordre ; les égalités se départagent alphabétiquement
- [x] T2.3 — `test_order_respects_every_fk_edge` : sur un schéma riche (FK multiples, composite, deux schémas), le vérificateur de test confirme que chaque table référencée précède celles qui pointent vers elle
- [x] T2.4 — `test_empty_metadata_yields_empty_order` + `test_fk_free_metadata_sorts_by_name` : metadata vide → `[]` ; aucune FK → toutes les tables, par ordre alphabétique
- [x] T2.5 — `test_self_reference_does_not_block_order` : `Category` seule → `[categories]`, aucune erreur (décision produit du 22/09 : l'auto-référence est un ordre de lignes, pas de tables)
- [x] T2.6 — `test_use_alter_does_not_block_order` : `employees ↔ departments` avec `use_alter=True` sur `head_id` → un ordre est rendu, aucune erreur (décision produit du 22/09)
- [x] T2.7 — `test_undeclared_mutual_cycle_raises_cyclic_fk_graph_error` : la même boucle sans `use_alter` → `CyclicFKGraphError`, `exc.groups == (("departments", "employees"),)`, le message nomme les deux tables
- [x] T2.8 — `test_cycle_error_lists_only_cyclic_tables` : schéma sain + une boucle dans le même metadata → `.groups` ne contient que la boucle ; aucune table saine n'apparaît dans l'erreur
- [x] T2.9 — `test_deep_3000_table_chain_never_recurses` : 3000 tables générées en boucle, chacune référencée par la suivante → l'ordre est rendu, aucun `RecursionError`
- [x] T2.10 — `test_3000_table_ring_reports_cycle_without_recursion` : 3000 tables en anneau → l'erreur est rendue avec l'anneau complet dans `.groups`, aucun `RecursionError`
- [x] T2.11 — commit atomique `feat(topology): strict parent-first order with explicit cycle detection`, case roadmap du README cochée (`- [x]`) dans le même commit, `ruff check src tests` vert, `python -m pytest tests/test_topology.py` tout vert, pytest complet = les deux rouges connus, à l'identique

## Vérifications locales — à chaque commit

```bash
source .venv/bin/activate
python -m pytest tests/test_topology.py   # la tranche courante : tout vert
python -m pytest                          # exactement les deux rouges connus (NotImplementedError), rien d'autre
ruff check src tests                      # zéro alerte
```
