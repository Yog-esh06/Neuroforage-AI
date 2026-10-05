# Knowledge graph

Code: `ai/extraction/{entities,relationships,values,tables}.py`, `knowledge/{builder,graph,traversal}.py`.

## Model

* **Entity** (`entities`): canonical node, merged across documents by `(canonical_name, type)`; aliases, normalised
  attributes (amount, ISO date), mention count.
* **Mention** (`entity_mentions`): where an entity occurs — document, chunk, page, character span, extraction method.
* **Relationship** (`entity_relationships`): typed directed edge with `document_id`, `chunk_id`, `page_number`,
  the **evidence sentence**, confidence and method. A relationship cannot exist without evidence.

Types: PERSON, ORG, LOCATION, DATE, MONEY, PRODUCT, TECHNOLOGY, CONTRACT, REGULATION, EVENT, METRIC.

## Extraction (deterministic first, no LLM)

| Source | Types |
|---|---|
| Parsers (`values.py`) | MONEY (symbols, ISO codes, k/M/B, lakh/crore), DATE (day/month/year precisions), durations (digits or words), percentages |
| Gazetteers / patterns | REGULATION (GDPR, HIPAA, SOX …), TECHNOLOGY, LOCATION, CONTRACT (named agreements and numbered references), EVENT, METRIC, PRODUCT |
| Org patterns | capitalised phrase + legal suffix(es) (`Globex Industries Ltd`), with role-title stripping (`Chief Executive Officer of Acme Corp` → `Acme Corp`) |
| Person patterns | titles (Dr., Ms.), "Name, CEO", "Signed by: Name" |
| spaCy NER (optional) | PERSON/ORG/GPE/EVENT/LAW where rules did not already claim the span (`python -m spacy download en_core_web_sm`) |

Bare references such as "this Agreement" resolve to the document's first explicitly named contract so that
`Acme Corp —party_to→ Master Services Agreement` is captured even when the sentence never repeats the full name.

## Relationships (`relationships.py`)

For every ordered entity pair in a sentence, the connecting text is matched against a typed rule table
(`signed`, `party_to`, `paid`, `billed`, `worth`, `expires_on`, `effective_from`, `complies_with`, `operates_in`,
`works_for`, `supplies`, `acquired`, `uses`, `offers`, `governed_in`, `penalty_of`, `counterparty_of` …). Details that make
the extraction safer than naive co-occurrence:

* passive constructions are handled (`$2M payable by Acme` → `Acme paid $2M`);
* if another party appears between the two mentions, location/contract verbs are not attributed across it
  (`Acme …, and Globex …, headquartered in Singapore` does **not** make Acme operate in Singapore);
* confidence decays with distance; unmatched informative pairs become low-confidence `co_occurs_with` (hidden by default
  in the explorer).

Limitations: no coreference beyond contract references and no dependency-parse relations; relation recall depends on the
rule table. Both are documented extension points.

## Graph service

`KnowledgeGraph` materialises a NetworkX `MultiDiGraph` from the tables (rebuilt lazily after ingestion/deletion).
Capabilities: entity lookup (exact / prefix / token-overlap), relationship lookup per entity with evidence, BFS multi-hop
expansion with relation filters, shortest simple paths with per-step evidence, visualisation subgraphs, chunk neighbourhood
scoring for retrieval, and statistics. The explorer UI is React Flow: click a node for the inspector (documents, mentions,
relationships, evidence), click an edge to read the sentence and open the page.
