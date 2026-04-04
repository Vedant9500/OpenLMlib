# Plan: LMlib — Cross-Project Knowledge & Research Library for LLMs

## TL;DR
Build a local, filesystem-based knowledge library where AI models can store and retrieve research findings, solutions, and design decisions across projects. Start with a simple schema + SQLite + semantic search, then progressively add retrieval ranking, quality gates, and multi-index search. Integration with Glassbox as first proof-of-concept.

## Research Recheck (Mar 2026)
- Storage: SQLite FTS5 provides built-in full-text search and BM25 ranking; FAISS is a similarity search library; HNSWlib provides an embedded ANN alternative; sqlite-vss shows FAISS "IDMap2" usage for stable IDs. (Sources: https://www.sqlite.org/fts5.html, https://github.com/facebookresearch/faiss, https://github.com/nmslib/hnswlib, https://github.com/asg017/sqlite-vss)
- Retrieval deltas: Anthropic Contextual Retrieval reports reduced top-20 retrieval failure rate by 35% with contextual embeddings, 49% with contextual BM25, and 67% with reranking; CRAG adds a retrieval evaluator plus decompose-then-recompose filtering; Lost in the Middle shows models use long contexts unevenly (start/end favored). (Sources: https://www.anthropic.com/news/contextual-retrieval, https://arxiv.org/abs/2401.15884, https://arxiv.org/abs/2307.03172)
- Quality gates/eval: RAGAS provides reference-free RAG evaluation including faithfulness; KILT evaluates provenance/citation. (Sources: https://arxiv.org/abs/2309.15217, https://arxiv.org/abs/2009.02252)
- Prompt injection: OWASP LLM01 details prompt injection types and mitigations (constraint, segmentation, least privilege, HITL, red-teaming); OpenAI safety best practices emphasize adversarial testing, limiting inputs/outputs, and HITL; indirect prompt injection is demonstrated in real systems. (Sources: https://genai.owasp.org/llmrisk/llm01-prompt-injection/, https://developers.openai.com/api/docs/guides/safety-best-practices, https://arxiv.org/abs/2302.12173)

---

## Storage Architecture & Format Decision (Evidence-Based)

**Note:** The research papers I reviewed focused on **retrieval quality**, not storage backends. However, production RAG systems (Chroma, LlamaIndex, LangChain) standardize on **hybrid storage**: separating concerns into metadata (structured DB), embeddings (fast vector store), and content (flexible format).

**Key Decisions:**

1. **SQLite vs. Alternatives?**
   - SQLite FTS5 provides full-text search and BM25 ranking for local keyword search. (Source: https://www.sqlite.org/fts5.html)
   - Portable, no service deps, ACID guarantees; validate with local benchmarks as the corpus grows.
   - Migration path: Postgres + pgvector if corpus or concurrency grows. (Source: https://github.com/pgvector/pgvector)

2. **Vector Storage Format?**
   - FAISS provides efficient similarity search with multiple index tradeoffs. (Source: https://github.com/facebookresearch/faiss)
   - Use stable vector IDs (IndexIDMap2 or explicit mapping) to avoid row-order drift; sqlite-vss defaults to "Flat,IDMap2" as an example. (Source: https://github.com/asg017/sqlite-vss)
   - HNSWlib is a lightweight ANN alternative with incremental updates and filtering. (Source: https://github.com/nmslib/hnswlib)

3. **Content Format: JSON Files?**
   - Human-readable for debugging; git-friendly for versioning
   - Separates large text from metadata query path (keeps DB lean)
   - SQL schema stays simple (id, confidence, timestamp, embedding_id)
   - Future-proof: schema evolution doesn't require migrations

4. **Embedding Storage Format?**
   - Use pickle (numpy serialization) for FAISS compatibility
   - Alternative: HDF5 for larger scales (Phase 4+)
   - Caching strategy: load-once on startup; rebuild monthly

**Performance Targets (Phase 1-3, validate locally):**
- Metadata query: target <1ms at 1k findings (warm cache)
- Vector similarity (1k findings): target <5-10ms, index dependent
- Keyword search: target <10ms at 1k findings
- Combined retrieve + rank: target <20ms at 1k findings

**Measurement Plan:**
- Report p50/p95 latency, cold vs warm cache, dataset size, k, index type/params, and hardware
- Track recall/precision alongside latency and update targets after benchmarking

---

## Risk Mitigation: Context Rot, Retrieval Noise, Hallucinated Memories

Three systemic risks threaten knowledge libraries. The roadmap addresses each with multi-layer defenses:

### Risk 1: Context Rot (Outdated/Contradictory Findings Accumulate)

**The Problem:**  
Early research had flawed assumptions. Six months later, a better solution was found. But the library still returns the flawed finding first with high confidence, and the model copies broken code.

**Defense Stack:**
- **Phase 1:** Write-gate validates on entry; requires evidence + reasoning
- **Phase 3:** Contradiction detector flags findings that conflict; block only on high-confidence contradictions
- **Phase 4:** Reranking deprioritizes low-confidence findings (flawed ones drift down)
- **Phase 5:** Monthly maintenance: staleness tracking (>3 months = review), consolidation (merge duplicates), feedback loop (agent logs "this failed" → finding confidence decreases)
- **Phase 6:** Knowledge graph with "contradicts" edges; query returns contradiction warnings

**Concrete Implementation:**
- Before ANY write: If new finding contradicts existing (>0.8 similarity, different claim) → flag for review; block only with high-confidence contradiction (NLI/LLM entailment) or manual resolution
- Monthly job: For stale findings, agent re-validates ("Still true?") or archives
- On task failure: Agent tags related findings as "led_to_failure" → moved to review queue
- Metrics: Track % consolidated, % archived, "superseded by" chains

---

### Risk 2: Retrieval Noise (Too Many Irrelevant Results Overwhelm Context)

**The Problem:**  
Query "webpage routing" returns 20 results from 5 unrelated projects. Model wastes half its context window sorting through noise instead of solving the problem.

**Defense Stack:**
- **Phase 2:** Dual-index search (semantic + keyword); contextual preprocessing makes embeddings specific; **[GAP: add project/tag filtering]**
- **Phase 4:** Reranking (cross-encoder scores all for relevance), decomposition (filter noise from chunks), query expansion (clarify intent)
- **Phase 4:** Context packing with position-aware ranking (most relevant first/last, padding in middle)
- **Phase 4:** Limit to top-5 findings post-reranking

**Concrete Implementation:**
- Retrieval API accepts: `{"query": "...", "projects": ["glassbox"], "tags": ["web", "routing"], "confidence_min": 0.7}`
- Reranking via cross-encoder: 20 candidates → 10 → 5 (most relevant only)
- Decomposition: extract claim + evidence from each; filter low-relevance sections (~20% context saved)
- Metrics: Precision@5 (% correct), top-10 tokens used (track efficiency)

---

### Risk 3: Hallucinated Memories (Model Confidently Writes Wrong "Fixes")

**The Problem:**  
Claude hallucinates a caching pattern that "should work." Writes it to library with confidence=0.95. Next month, another model retrieves it, confidently applies it, and the code breaks. Poison propagates.

**Defense Stack:**
- **Phase 1:** Evidence validation (claim must match evidence semantically); confidence ≥ 0.6 required; reasoning field mandatory
- **Phase 1:** Evidence audit trail (track what each finding's derived from; enable forensics)
- **Phase 3:** Faithfulness evaluation (after retrieval, did model actually use findings or hallucinate?); track hallucination rate
- **Phase 3:** Novelty + contradiction check (suspicious claims flagged; reject only with high-confidence)
- **Phase 5:** Feedback incorporation (agent logs "tried pattern X, failed" → finding confidence decreases)
- **Phase 5:** Repeated failure → archive finding + log warning

**Concrete Implementation:**
```
Before write:
  1. Claim-evidence consistency check (cosine sim >0.7)
  2. Confidence ≥ 0.6 or reject
  3. Reasoning must be >50 chars (forces explanation)

After retrieval (Phase 3):
  1. Ask Claude: "Do your findings cite these sources?" → rate 0–1
  2. If avg_faithfulness <0.80 over time → library has hallucination problem
  
On task failure (Phase 5):
  1. Agent logs: "Tried pattern_X; failed: [reason]"
  2. Find related findings → tag "led_to_failure"
  3. Confidence *= 0.9; move to review queue
  4. If same finding fails 3x → archive with reason
```

**Metrics:**  
- Hallucination rate (% of answers that don't cite evidence)
- Novelty rejection rate (% writes rejected for contradiction)
- Failure feedback rate (% of tasks logging failures)
- Evidence audit reversal time (how fast can we fix propagated hallucination?)

---

## Phases

### Phase 1: Core Schema & Write Pipeline (Weeks 1–2)
Status: Complete (Mar 2026)
**Goal:** Establishes the data model, storage architecture, and writing fundamentals.

**Steps:**
1. Design SQLite schema: metadata table (id, project, claim, confidence, created_at, embedding_id, content_hash, status) + findings_text (tags, evidence, caveats, reasoning as JSON)
2. **[NEW - Risk Mitigation] Add evidence audit trail:** proposed_by, evidence_provided, reasoning_length, failure_log, confidence_history (track who said what when; enable forensics on hallucinations)
3. Add embedding model integration + caching (needed for write-gate and contextual chunking)
4. Set up vector store: FAISS index with stable IDs (IndexIDMap2) or HNSWlib fallback; initialize 384-dim index
5. Create file layout: `data/findings.db`, `data/embeddings.faiss`, `data/findings/` JSON directory
6. Implement SQLite + vector store sync: map `embedding_id` to stable vector ID; use tombstones + periodic rebuild/compaction
7. Build write-gateway: propose → **evidence_validation** → novelty/contradiction flagging (no hard block unless high-confidence) → store in DB + JSON + vector store → emit event
8. **[NEW - Risk Mitigation] Enforce submission requirements:** confidence ≥ 0.6 OR reject; reasoning >50 chars OR reject; evidence provided OR reject
9. Create CLI for initial manual additions (test with Glassbox findings)

**Key Design Decisions:**
- **Hybrid storage:** SQLite for metadata + FTS; FAISS for embeddings; JSON files for full content (splits concerns, keeps DB lean)
- Use JSON for serialization; plan for future versioning via content_hash field
- Include confidence field (0.0–1.0) and validity epoch (months before review)
- All writes logged for audit trail
- Embedding ID field maps to a stable vector ID (do not rely on FAISS row order)
- Content hash table field for version tracking (file-level git workflow)
- SQLite FTS5 virtual table on (claim, evidence, reasoning) for keyword search
- FAISS: start with Flat + IDMap2 for simplicity; move to IVF/HNSW after data grows and training data is available

**Relevant Files:**
- `lmlib/schema.py` — defines Knowledge unit, event models, validation
- `lmlib/db.py` — SQLite setup, metadata queries, FTS5 index
- `lmlib/vector_store.py` — **[NEW]** FAISS wrapper (index management, similarity search)
- `lmlib/embeddings.py` — Sentence Transformers wrapper + contextual preprocessing + caching
- `lmlib/write_gate.py` — validation logic (novelty, contradiction, schema)
- `lmlib/cli.py` — manual add/list commands

**Verification:**
- Create 10 test findings from Glassbox (e.g., "API response time optimization patterns")
- Verify SQLite metadata stores + retrieves correctly
- Verify FAISS index grows (row count matches findings count)
- Verify JSON files created in `data/findings/`
- Check write-gate rejects invalid submissions (missing evidence, low confidence, schema mismatch)
- Confirm DB + FAISS + files stay synchronized (embedding_id consistency)

---

### Phase 2: Basic Retrieval & Read Pipeline (Week 3)
Status: Complete (Apr 2026)
**Goal:** Enable semantic + keyword search without ranking; safe prompt injection.

**Steps:**
1. Reuse embedding model from Phase 1; add query embedding caching/batching
2. **[NEW] Implement contextual chunk preprocessing:** generate 50-100 token context per chunk, prepend before embedding and BM25 (Anthropic reports lower top-20 failure rate; validate locally)
3. Implement dual-index search: semantic (vector sim + cached embeddings) + lexical (SQLite FTS5)
4. Build retrieval CLI: query → combined results → rank by recency
5. **[NEW] Add content isolation layer:** treat retrieved content as untrusted data, keep it out of the system prompt, wrap in explicit delimiters, and validate structured outputs (OWASP LLM01)
6. **[NEW - Retrieval Noise Defense] Add project/tag/date filtering:** allow queries to filter findings by project, tags, or date range; if semantic search uses post-filtering, oversample to preserve recall
7. Integrate with Claude/Opus via safe context injection: retrieve top-5 results, pass as untrusted context with explicit delimiters
8. **[NEW - OPTIONAL] Add adaptive retrieval flag:** allow model to optionally decide IF retrieval is needed vs. using parametric knowledge (Self-RAG; can skip v1)
9. Test end-to-end: A model queries library, gets relevant findings

**Key Design Decisions:**
- Cache embeddings + preprocessed chunks in SQLite (avoid recomputing)
- Use BM25-style ranking for keyword matches (FTS5 rank/BM25)
- Contextual summaries generated on write; 50-100 tokens per chunk; Anthropic reports 35% lower top-20 failure rate for contextual embeddings and 49% when combined with contextual BM25
- Sanitization: treat library content as untrusted input; isolate it from system prompt; validate outputs and add injection tests (OWASP LLM01)
- No reranking yet; simple recency tiebreaker
- API layer (even if local) for future cloud migration
- Adaptive retrieval gated behind config flag (disable for v1, enable post-Phase 3)

**Relevant Files:**
- `lmlib/embeddings.py` — Sentence Transformers wrapper + contextual preprocessing + caching (stores in SQLite as row)
- `lmlib/vector_store.py` — FAISS index management, similarity search (target <5-10ms at 1k findings)
- `lmlib/retrieval.py` — dual-index search logic (FAISS semantic + FTS5 keyword)
- `lmlib/sanitization.py` — **[NEW]** prompt injection mitigation (escape, neutralize library content)
- `lmlib/api.py` — HTTP wrapper (FastAPI or simple Flask locally)
- `lmlib/client.py` — Claude integration snippet + safe injection pattern

**Verification:**
- Query for "optimization" → retrieve relevant Glassbox findings
- Verify both semantic (FAISS) and keyword (FTS5) paths work
- Check contextual preprocessing applied to chunks; inspect embeddings in FAISS index
- Test prompt injection: inject malicious content in finding → verify safe handling and no instruction following
- Measure retrieval latency (target: <20ms combined for ~1k findings)
- Verify contextual chunks improve retrieval accuracy vs. baseline (measure locally)
- Load FAISS index from disk; confirm similarity search matches expected results

---

### Phase 3: Quality Gates & Evaluation (Week 4)
Status: Complete (Apr 2026)
**Goal:** Ensure library quality; catch noisy or conflicting additions; measure retrieval fidelity.

**Steps:**
1. Implement novelty check: candidate vs. existing findings (embedding distance threshold)
2. Add contradiction detector: flag findings that conflict on core claims
3. Build confidence scoring: agent suggests confidence, validator can adjust
4. Create eval dataset: 20 Glassbox queries + expected finding IDs
5. Measure retrieval metrics: recall@5, recall@10, precision@5
6. **[NEW - Hallucinated Memories Defense] Add faithfulness evaluation:** measure if answers actually use retrieved context (RAGAS; reference-free)
7. **[NEW - Hallucinated Memories Defense] Add citation tracking:** log which findings were used in each query result; track provenance/citation accuracy over time
8. **[NEW - Context Rot Defense] Add validity window tracking:** mark findings with staleness flag if not re-validated in past 3 months
9. **[NEW] Add relevance-context alignment metric:** did retrieved findings match query intent?

**Key Design Decisions:**
- Novelty threshold: 0.85 embedding similarity = "similar existing finding"
- Contradiction flagged if similarity > 0.8 but conclusions differ
- Eval metrics stored alongside library for tracking drift
- Write-gated findings require min 0.6 confidence initially
- Faithfulness: use RAGAS for reference-free evaluation; calibrate with a small human-labeled set
- Relevance: embedding similarity between query and retrieved findings
- **[NEW - Context Rot Defense] Validity window:** default 3 months; findings older than window marked "pending_review"
- **[NEW - Citation Tracking] Usage ledger:** store (finding_id, query_id, cited=true/false, timestamp) for forensics; align with provenance practices (KILT)

**Relevant Files:**
- `lmlib/gate/novelty.py`
- `lmlib/gate/contradiction.py`
- `lmlib/evaluation.py` — RAGAS-lite metrics + **[NEW]** faithfulness + relevance scoring

**Verification:**
- Add 5 duplicate findings → reject all automatically
- Add 1 contradictory finding → flag and require manual review
- Run eval suite on 20 queries; target recall@5 ≥ 0.75
- Score faithfulness on 20 retrieved findings: target ≥ 0.80 (RAGAS)
- **[NEW] Verify citation tracking:** log findings used in queries; spot-check 10 results for citation accuracy
- **[NEW] Verify staleness tracking:** add finding, mark created_at = 3 months ago; query should flag "pending_review"
- Compare Phase 2 baseline + Phase 3 metrics to verify Phase 2 contextual preprocessing helped

---

### Phase 4: Reranking & Advanced Retrieval (Week 5)
Status: Complete (Apr 2026)
**Goal:** Improve ranking accuracy for larger corpus; filter noise; handle edge cases.

**Steps:**
1. Integrate reranker (Cohere API or local cross-encoder)
2. Implement query expansion: model rephrases queries before retrieval
3. **[NEW] Add document decomposition:** split retrieved findings into claim + evidence + caveats; filter out low-relevance sections (CRAG-style decompose-then-recompose)
4. Add result deduplication: merge similar findings across projects
5. Build context window optimizer: pack findings smartly into Claude's context (position-aware ranking per Lost in the Middle)
6. Add "reasoning trace": show why each finding was retrieved

**Key Design Decisions:**
- For now: use cross-encoder re-ranking if compute permits; else skip
- Query expansion as optional flag (cost/latency trade-off)
- Store reasoning trace in retrieval event for debugging
- Limit to top-20 chunks postranking to control context size

**Relevant Files:**
- `openlmlib/reranking.py` — **[NEW]** cross-encoder reranking + hybrid scoring
- `openlmlib/query_expansion.py` — **[NEW]** rule-based query expansion (Rewrite-Retrieve-Read)
- `openlmlib/decomposition.py` — **[NEW]** document decomposition (claim/evidence/caveats filtering)
- `openlmlib/packing.py` — **[NEW]** context window optimization (position-aware)
- `openlmlib/retrieval.py` — updated with `search_enhanced()`, deduplication, reasoning traces
- `openlmlib/settings.py` — updated with `Phase4Settings` dataclass
- `openlmlib/library.py` — updated with `retrieve_findings_enhanced()`
- `openlmlib/cli.py` — updated with `query-enhanced` command

**Verification:**
- Reranked results should score higher on eval metrics
- Compare latency: phase 2 vs. phase 4
- Manual spot-check: verify reasoning traces are sensible
- ✅ 55 new tests across 4 test files; 87 total tests passing

---

### Phase 5: Maintenance & Rot Prevention (Week 6)
Status: **Incomplete** — Not yet implemented
**Goal:** Keep library fresh and accurate over time; learn from task feedback.

**Steps:**
1. Implement staleness tracking: mark findings older than 3 months for review
2. Add periodic consolidation: merge very similar findings
3. Build summary generation: auto-generate summaries for clusters of findings
4. Create refresh workflow: agent re-validates old findings, updates confidence
5. **[NEW - Hallucinated Memories Defense] Add failure feedback incorporation loop:** 
   - Agent proposes library updates when task fails (Reflexion; e.g., "this caching pattern didn't work; log new learning")
   - When finding is cited in a failed task: tag "led_to_failure", confidence *= 0.9, move to review queue
   - After 3 failures on same finding: archive with forensic reason/evidence
6. **[NEW - Context Rot + Hallucinated Memories] Track re-validation results:** log outcomes when agent re-checks old findings (success/fail/uncertain)
7. **[NEW - OPTIONAL] Implement hot/warm/cold memory tiers:** recent findings cached aggressively; old findings warmed on-demand (MemGPT; improves latency for large corpus)
8. Archive outdated findings (don't delete; soft-remove with reason)

**Key Design Decisions:**
- Validity window: 3 months default, customizable per finding
- Consolidation runs monthly (or on-demand)
- Summaries cached and refreshed only if inputs change
- Archive maintains full history for audit/reversion
- **[NEW - Failure Feedback] Feedback loop:** agent tags findings as "led_to_failure" → flag for refresh + higher review priority; 3-strike archiving with reason
- **[NEW - Failure Tracking] Failure ledger:** store (finding_id, task_id, failure_reason, timestamp, confidence_before, confidence_after) for forensics
- Hot tier: last 30 days findings; warm: 30–90 days; cold: >90 days (if tiering implemented)

**Relevant Files:**
- `openlmlib/maintenance.py` — **[NEW, NOT YET CREATED]** staleness, consolidation, archiving
- `openlmlib/summary_gen.py` — **[NEW, NOT YET CREATED]** auto-summarization
- `openlmlib/refresh_agent.py` — **[NEW, NOT YET CREATED]** re-validation workflow + feedback incorporation
- `openlmlib/memory_tiers.py` — **[NEW, NOT YET CREATED, OPTIONAL]** hot/warm/cold caching
- `openlmlib/settings.py` — **[NEEDS UPDATE]** Phase5Settings dataclass
- `openlmlib/library.py` — **[NEEDS UPDATE]** maintenance functions
- `openlmlib/cli.py` — **[NEEDS UPDATE]** maintenance CLI commands

**Verification:**
- Create findings with 4-month-old timestamps → mark as stale
- Run consolidation on 10 similar findings → reduce to 3 unique
- **[NEW] Simulate failure feedback:** Mark 1 finding as "led_to_failure" 3 times → verify confidence reduced and finding archived with reason
- **[NEW] Verify failure ledger:** Spot-check 5 entries in failure ledger; confirm (finding_id, failure_reason, timestamp, confidence_delta) captured correctly
- Verify archive is queryable if needed

**Changes Made So Far:**
- None — Phase 5 has not been started yet. All files listed above need to be created/updated.

---

### Phase 6: Graph Index & Advanced Queries (Optional; Week 7+)
**Goal:** Answer "global" questions (themes, patterns, recommendations); hierarchical sensemaking.

**Steps:**
1. Build knowledge graph: nodes = findings, edges = related-to, contradicts, supports, evolves-from
2. Implement entity extraction: extract components, pain points, solutions from findings
3. **[NEW - GraphRAG-inspired] Add hierarchical aggregation:** extract entities → communities (clusters) → generate summaries at 3 levels (local finding, community, global theme)
4. Add ranking by centrality: findings that connect many others rank higher
5. Support path-based queries: "what led to this architecture choice?"
6. **[NEW] Query engine:** given user question, activate appropriate level (local/community/global) and aggregate answers
7. **[NEW] Pre-generate community summaries** at index write time (not query time) for performance

**Key Design Decisions:**
- Lightweight graph (not full GraphRAG; simpler for local system) but with hierarchical tiers
- Entities extracted on write; communities formed via modularity clustering
- Centrality + hierarchy recomputed monthly; summaries cached/refreshed on change
- Query routing: local query → find entities → search findings; global query → find communities → aggregate summaries

**Relevant Files:**
- `lmlib/graph.py` — graph construction, queries, hierarchy
- `lmlib/entity_extract.py` — entity recognition
- `lmlib/community_detect.py` — **[NEW]** clustering for hierarchy
- `lmlib/hierarchical_summarize.py` — **[NEW]** multi-level aggregation (local → community → global)

**Verification:**
- Query graph: retrieve all findings related to "API design"
- Path query: "findings that led to caching strategy"
- Verify entity extraction catches 80%+ of key concepts in test set

---

## Tech Stack Recommendation

### Storage Architecture: SQLite + FAISS + JSON (Hybrid Model)

**Why this specific combo?** (Not emphasized in papers; inferred from production RAG systems)

The papers didn't focus on storage backends, but production RAG systems standardize on hybrid storage: separating metadata (structured), vectors (specialized DB), and content (flexible):

- **SQLite:** Metadata + full-text search (FTS5); no service dependencies; single-file portability
- **FAISS:** Fast local vector similarity search (validate locally); Facebook Research; production-used
- **JSON files:** Large findings, human-readable, git-friendly, schema-flexible

**Performance vs. Alternatives (indicative targets; validate locally, <10k findings):**

| Approach | Metadata Query | Vector Search | Combined | Portability |
|----------|---|---|---|---|
| **SQLite + FAISS** | ~1ms | ~5ms | ~20ms | High ✓ |
| SQLite (vectors as BLOB) | ~1ms | ~50ms | ~60ms | High |
| SQLite + pgvector | ~2ms | ~10ms | ~25ms | Low (needs server) |
| Chroma (local) | N/A | ~10ms | ~25ms | Medium |

**Recommendation:** SQLite + FAISS for MVP; migrate to Postgres + pgvector if corpus > 50k.

---

### Storage Layout

```
d:\LMlib\data\
├── findings.db                 # SQLite: metadata (id, project, confidence, created_at) + FTS indices
├── embeddings.faiss           # FAISS: vector index (384-dim, all-MiniLM-L6-v2)
├── embeddings_cache.pkl       # Embedding matrix (numpy, serialized)
└── findings/                  # JSON files: full content
    ├── glassbox-001.json
    └── ...
```

**SQLite Schema (Phase 1):**
```sql
-- Metadata table (lean, indexed)
CREATE TABLE findings (
  id TEXT PRIMARY KEY,
  project TEXT,
  claim TEXT NOT NULL,
  confidence REAL,
  created_at TIMESTAMP,
   embedding_id INTEGER,  -- stable vector ID in index
  content_hash TEXT,     -- SHA256 for versioning
  status TEXT
);

-- Searchable fields (JSON arrays)
CREATE TABLE findings_text (
  id TEXT PRIMARY KEY,
  tags TEXT,      -- ["caching", "perf"]
  evidence TEXT,  -- ["load test", "profiling"]
  caveats TEXT,   -- ["redis required"]
  reasoning TEXT
);

-- Full-text search index
CREATE VIRTUAL TABLE findings_fts USING fts5(claim, evidence, reasoning);
```

**Each Finding as JSON File:**
```json
{
  "id": "glassbox-001",
  "claim": "API response times improved 40% with Redis caching",
  "evidence": ["load test results", "perf comparison"],
  "reasoning": "Tested on production traffic; 99th percentile: 45ms → 8ms",
  "caveats": ["Assumes distributed setup"],
  "full_text": "..."
}
```

---

### Full Component Breakdown

| Component | Choice | Rationale |
|-----------|--------|-----------|
| **Metadata Store** | SQLite (+ FTS5, JSON1 extensions) | Simple, no deps, built-in full-text search |
| **Vector Store** | FAISS (IndexIDMap2) or HNSWlib | Fast local search; stable IDs; no external service |
| **Content Storage** | JSON files | Human-readable, git-friendly, schema-flexible |
| **Embeddings Model** | Sentence Transformers (all-MiniLM-L6-v2) | Free, fast, 384-dim, locally cached |
| **Keyword Search** | SQLite FTS5 | Built-in, lightweight, proven for small corpus |
| **Reranking** | Cross-encoder (sentence-transformers) or skip for MVP | Local, optional Cohere for better quality (Phase 4) |
| **API** | FastAPI | Lightweight, async-ready, local testing |
| **LLM Integration** | Claude Opus via Anthropic SDK | Best available; safe context injection (keep retrieved content out of system prompt) |
| **Language** | Python | Consistency, ecosystem (transformers, faiss, sqlalchemy) |
| **Storage Root** | `d:\LMlib\data\` | Workspace-local, git-controllable |

---

## Relevant Files (Final Structure)

```
d:\LMlib\
├── lmlib/
│   ├── __init__.py
│   ├── schema.py                 # Knowledge unit, event models
│   ├── db.py                     # SQLite setup, queries, metadata operations
│   ├── vector_store.py           # FAISS wrapper (index, search, update)
│   ├── embeddings.py             # Sentence Transformers + contextual preprocessing
│   ├── retrieval.py              # Dual-index search (semantic via FAISS + keyword via FTS5)
│   ├── write_gate/
│   │   ├── novelty.py            # Duplicate detection
│   │   ├── contradiction.py      # Conflict flagging
│   │   └── validator.py          # General validation
│   ├── sanitization.py           # Prompt injection mitigation
│   ├── decomposition.py          # Document decomposition (Phase 4)
│   ├── reranking.py              # Cross-encoder reranking (Phase 4)
│   ├── packing.py                # Context window optimization
│   ├── evaluation.py             # Retrieval metrics (Phase 3)
│   ├── maintenance.py            # Rot prevention (Phase 5)
│   ├── graph.py                  # Knowledge graph (Phase 6, optional)
│   ├── api.py                    # FastAPI server
│   └── client.py                 # Claude integration examples
├── data/
│   ├── findings.db               # SQLite: metadata + FTS indices
│   ├── embeddings.faiss          # FAISS: vector index (384-dim)
│   ├── embeddings_cache.pkl      # Cached embeddings (numpy matrix, serialized)
│   └── findings/                 # JSON files: full content + reasoning
│       ├── glassbox-001.json
│       ├── glassbox-002.json
│       └── ...
├── config/
│   ├── settings.json             # Thresholds, model names, storage paths
│   └── eval_queries.json         # Eval dataset
├── tests/
│   ├── test_schema.py
│   ├── test_storage.py           # NEW: test SQLite + FAISS interaction
│   ├── test_retrieval.py
│   └── test_write_gate.py
└── README.md                     # Setup, usage, storage guide
```

---

## Verification Phases (Quality Checkpoints)

| Phase | Test | Success Criteria |
|-------|------|------------------|
| 1 | Store 10 Glassbox findings; retrieve by ID | All store/retrieve correctly; write-gate rejects invalid |
| 2 | Query "optimization" → get rank-ordered results | Top-5 results include ground truth; latency target <500ms |
| 3 | Add 5 duplicates; add 1 contradictory finding | All duplicates rejected; contradiction flagged |
| 4 | Compare reranked vs. non-reranked eval scores | Target recall@5 improves by ≥10%; latency target <1s |
| 5 | Create stale findings; run maintenance | Stale marked correctly; consolidation merges 10→3 |
| 6 | Query knowledge graph for themes | Path queries return coherent result set |

---

## Decisions & Scope Constraints

**In Scope:**
- Single-machine, local filesystem
- Pure research/findings (no sensitive data)
- LLM-first design (Claude queries, not human searches initially)
- Future-proofing for cloud/multi-project but not building it now

**Out of Scope (v1):**
- Multi-user access control  
- Cloud sync/backup (manual git if needed)
- Fine-tuning on domain data  
- Full multi-tenancy  
- Complex permission boundaries  

**Strategic Choices:**
1. **Start simple, scale retrieval quality first** → Don't build graph index until keyword + semantic works well
2. **Write-gate first** → Prevent garbage in; saves cleanup later
3. **Eval from Phase 3** → Measure quality early; easier to iterate
4. **Local-only initially** → Lower friction; migrate to API/cloud only if needed

---

## Further Considerations

1. **When to integrate with Glassbox?**
   - Phase 2: Use as test case (manual findings, one query)
   - Phase 3+: Glassbox agent auto-populates library on task completion

2. **How to handle API model costs?**
   - Phase 2–4: Use free local embedding model; skip Cohere reranking initially
   - Phase 4+: Option to enable Cohere if latency/quality demands

3. **Roadmap for multi-project expansion?**
   - Phase 1 schema already supports `project` field
   - Phase 6 graph index enables cross-project pattern discovery
   - No changes needed; just seed with more projects in Phase 3+

---

## Sources (Recheck)
- SQLite FTS5 (BM25 and full-text search): https://www.sqlite.org/fts5.html
- FAISS library: https://github.com/facebookresearch/faiss
- HNSWlib: https://github.com/nmslib/hnswlib
- sqlite-vss (FAISS IDMap2 usage example): https://github.com/asg017/sqlite-vss
- Contextual Retrieval (Anthropic, Sep 2024): https://www.anthropic.com/news/contextual-retrieval
- CRAG paper: https://arxiv.org/abs/2401.15884
- Lost in the Middle: https://arxiv.org/abs/2307.03172
- RAGAS: https://arxiv.org/abs/2309.15217
- KILT (provenance evaluation): https://arxiv.org/abs/2009.02252
- OWASP LLM01 Prompt Injection: https://genai.owasp.org/llmrisk/llm01-prompt-injection/
- OpenAI safety best practices: https://developers.openai.com/api/docs/guides/safety-best-practices
- Indirect prompt injection paper: https://arxiv.org/abs/2302.12173
