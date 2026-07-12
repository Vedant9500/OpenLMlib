# Sequential Code Review Findings

Date: 2026-07-11  
Method: static review + targeted dynamic checks; each finding re-verified to reduce false positives.

**Re-verified 2026-07-12:** full pass against live sources; Part 9.1 reclassified (see Reanalysis section).

---

## Part 1 — Foundation

**Scope:** `openlmlib/schema.py`, `settings.py`, `db.py`, `file_lock.py`, `sanitization.py`, `write_gate.py`, `__init__.py`

### Confirmed

#### 1. Empty evidence can crash add path before structured rejection
- **Severity:** Medium  
- **Status:** Confirmed  
- **Refs:** `openlmlib/write_gate.py:97-115`, `openlmlib/write_gate.py:54-70`, `openlmlib/library.py:412-416`  
- **Evidence:**
  - `WriteGate.validate` appends `evidence is required` but continues into embedding when `embedder` is set.
  - `library.add_finding` pre-calls `gate._encode_claim_evidence(claim, evidence)` **before** `validate`.
  - Empty evidence becomes `encode([""])`. Verified: a strict embedder raising on empty text throws `RuntimeError` and never returns `status=rejected` with a clean issue list.
  - Also verified: even a non-throwing embedder is called twice for a request that will always be rejected.
- **Impact:** Failed writes can surface as unhandled exceptions instead of stable validation errors; wasted embedding work on invalid input.
- **Not a false positive because:** failure is on the live `add_finding` path, not a theoretical standalone unit-test only case.
- **Suggested fix:** short-circuit when `not evidence` (and other hard field errors) before any encode; do not pre-encode empty evidence in `library.add_finding`.

#### 2. Settings booleans reject JSON integers `0` / `1`
- **Severity:** Medium  
- **Status:** Confirmed  
- **Refs:** `openlmlib/settings.py:9-20`, `openlmlib/settings.py:165-196`  
- **Evidence:**
  - `_parse_bool` accepts only `bool` and a fixed set of strings.
  - Verified: `load_settings` with `"enabled": 1` / `0` raises `ValueError: Expected boolean value, got 1`.
  - Default payload uses real JSON booleans, so stock config is fine; hand-edited or tool-written numeric flags break load.
- **Impact:** Settings load aborts for otherwise valid JSON configs.
- **Not a false positive because:** reproduced end-to-end through `load_settings`, not only the helper.
- **Suggested fix:** treat `1`/`0` (and maybe other truthy ints carefully) as bools, or coerce with a clear warning.

#### 3. Interprocess lock never recovers empty / non-PID lock files
- **Severity:** Medium  
- **Status:** Confirmed  
- **Refs:** `openlmlib/file_lock.py:10-22`, `openlmlib/file_lock.py:48-64`  
- **Evidence:**
  - Stale reclaim only runs when owner PID parses **and** `_pid_is_alive` is false.
  - Verified: empty lock file → wait until timeout (`TimeoutError`).
  - Verified: non-integer contents (e.g. `not-a-pid`) → same timeout.
  - Crash after `O_CREAT|O_EXCL` but before PID write can leave such a lock.
- **Impact:** Cross-process writers (embeddings / vector store) can hard-fail for `timeout_sec` instead of recovering.
- **Not a false positive because:** dynamic timeout reproduced; reclaim branch is unreachable for these lock contents.
- **Suggested fix:** treat missing/invalid PID as reclaimable after age threshold, or always write PID atomically and reclaim unreadable locks after grace period.

#### 4. `_pid_is_alive` treats `PermissionError` as dead
- **Severity:** Low  
- **Status:** Confirmed (platform edge)  
- **Refs:** `openlmlib/file_lock.py:25-30`  
- **Evidence:**
  - `PermissionError` is a subclass of `OSError`; current code returns `False` for any `OSError`.
  - On Unix, `os.kill(pid, 0)` often raises `PermissionError` when the process **exists** but is not signalable by this user.
  - On this Windows environment, self-check works and missing PID raises `OSError` (treated as dead correctly).
- **Impact:** Multi-user shared filesystem could steal a live owner's lock.
- **Why kept:** real semantic bug in the alive-check contract; severity low for typical single-user OpenLMlib installs.
- **Suggested fix:** `except PermissionError: return True` (or inspect `errno` for `EPERM` vs `ESRCH`).

#### 5. `INSERT OR REPLACE INTO findings_fts` does not upsert by `id` (latent)
- **Severity:** Low (latent / maintainability)  
- **Status:** Confirmed latent, **not** an active production double-write today  
- **Refs:** `openlmlib/db.py:242-248`  
- **Evidence:**
  - FTS5 virtual table has no UNIQUE constraint on `id`; SQLite `INSERT OR REPLACE` only replaces on conflict with a real unique/primary key.
  - Forced second `INSERT OR REPLACE` with same `id` produced **2** FTS rows and duplicate search hits.
  - Current writers: only `insert_finding` writes FTS; second insert of same finding id fails on `findings` PK and the transaction rolls back, so FTS stays single-row in normal use.
  - No update path rewrites claim/evidence into FTS after insert; maintenance only changes status/confidence.
- **Impact today:** none under current call graph.  
- **Future risk:** any reindex/update helper using the same SQL will silently duplicate lexical hits.
- **Not over-reported as high** after re-check of call sites.
- **Suggested fix:** `DELETE FROM findings_fts WHERE id=?` then `INSERT`, or FTS delete command + insert; rename away from `OR REPLACE`.

### Reviewed and dropped (false positives / not bugs for Part 1)

| Initial suspicion | Why dropped |
|---|---|
| `_json_load` crashes on corrupt JSON | Real only for externally corrupted DB; all writers use `json.dumps`. Robustness nicety, not a confirmed functional defect in normal operation. |
| `cited` always `1` in `log_retrieval_usage` | Incomplete/unused column; no consumer depends on false values. Design debt, not a broken behavior. |
| Sanitization skips `domain` / paper fields | `render_untrusted_context` does not emit those fields; no active injection path in this renderer. |
| Schema / settings defaults / WAL pragmas | Consistent with tests and intended local-tool design. |
| `__init__.py` exports / version | No issue found. |

### Part 1 files with no confirmed defects
- `openlmlib/schema.py`
- `openlmlib/__init__.py`
- `openlmlib/sanitization.py` (for current render surface)

---

## Part 2 — Storage & embeddings

**Scope:** `openlmlib/library.py`, `embeddings.py`, `vector_store.py`, `packing.py`  
(Also touched call sites: `mcp_server.add_finding` → `library.add_finding`, CLI `rebuild-index`.)

### Confirmed

#### 1. `rebuild_vector_index` calls `encode(..., batch_size=32)` — TypeError
- **Severity:** High  
- **Status:** Confirmed  
- **Refs:** `openlmlib/library.py:95`, `openlmlib/embeddings.py:92`  
- **Evidence:**
  - `SentenceTransformerEmbedder.encode(self, texts)` has no `batch_size` parameter.
  - Verified: `encode(['a','b'], batch_size=32)` raises `TypeError: got an unexpected keyword argument 'batch_size'`.
  - Live callers: `cli.py` `rebuild-index` and setup path that invokes `rebuild_vector_index` whenever findings exist.
- **Impact:** Index rebuild fails hard on any non-empty library (empty library skips encode and may still “succeed”).
- **Not a false positive because:** signature mismatch is deterministic; not environment-dependent.
- **Suggested fix:** either drop `batch_size=` at the call site, or forward `**kwargs` / explicit `batch_size` into `self._model.encode`.

#### 2. Duplicate-finding guard crashes with `KeyError: similarity_rank`
- **Severity:** High  
- **Status:** Confirmed  
- **Refs:** `openlmlib/library.py:309-329`, `openlmlib/library.py:362-369`, `openlmlib/mcp_server.py:967-987`  
- **Evidence:**
  - `_check_duplicate_warning` returns `claim_similarity` and `fts_rank`, **not** `similarity_rank`.
  - `add_finding` does `duplicate_warning["similarity_rank"]` when building `status=duplicate_suggestion`.
  - Verified end-to-end construction path: `KeyError: 'similarity_rank'`.
  - MCP `add_finding` always passes `similar_findings` from `search_fts`, so high token-overlap claims hit this path in production MCP use.
- **Impact:** Instead of a structured duplicate suggestion, the tool/API errors; duplicate safety net is broken.
- **Not a false positive because:** key names mismatch is explicit in source; reproduced.
- **Suggested fix:** use `claim_similarity` (and optionally expose `fts_rank`), or add `similarity_rank` alias in the warning dict.

#### 3. Context packing trims after interleave → can drop higher-scored items
- **Severity:** Medium  
- **Status:** Confirmed  
- **Refs:** `openlmlib/packing.py:54-58`, `openlmlib/packing.py:69-81`, `openlmlib/retrieval.py:472-479`  
- **Evidence:**
  - `pack` sorts by score, then `_interleave_ends`, then `_trim_to_budget` walks the **reordered** list and stops at budget.
  - Verified with fixed 10-token items and `max_tokens=30`: output scores `[1.0, 0.8, 0.6]` — **second-best (0.9) dropped**, weaker mid/end items kept.
  - Used when enhanced retrieval enables `pack_context`.
- **Impact:** Under token pressure, context can prefer lower-relevance findings over higher ones purely due to position interleaving order.
- **Not a false positive because:** behavior matches code order; dynamic repro confirms second-best omission.
- **Suggested fix:** trim by score first (select top-N that fit budget), then interleave the survivors; or re-score trim priority independent of position order.

#### 4. Embedding cache multi-process save is last-writer-wins (can drop keys)
- **Severity:** Medium  
- **Status:** Confirmed  
- **Refs:** `openlmlib/embeddings.py:44-58`, lock usage does not merge disk state  
- **Evidence:**
  - `save()` serializes **in-memory** `_cache` only; it never reloads disk under the lock before write.
  - Verified: process A has `{a}`, process B has `{a,b}` after load+set; if A `save()`s after B, final file is `{a}` only — **key `b` lost**.
  - Lock prevents concurrent write corruption but not stale-memory overwrite.
- **Impact:** Concurrent CLI/MCP processes can silently shrink the embedding cache; extra re-encodes (correctness of vectors OK, performance/regression risk).
- **Not a false positive because:** reproduced with two `EmbeddingCache` instances on one path.
- **Suggested fix:** under lock, load latest disk payload, merge with in-memory updates, then write.

#### 5. `add_finding` exception path can delete a pre-existing finding with the same id
- **Severity:** Medium  
- **Status:** Confirmed (edge)  
- **Refs:** `openlmlib/library.py:381-388`, `openlmlib/library.py:513-515`  
- **Evidence:**
  - Collision check is only on `embedding_id` mapping to a **different** finding id.
  - If `finding_id` already exists, `db.insert_finding` fails with PK integrity error; `except` calls `db.delete_finding(conn, finding.id)`, which removes the **original** row (and FTS), then best-effort vector cleanup.
- **Impact:** Caller-supplied / retried ids can destroy an existing finding on a failed re-insert attempt.
- **Not a false positive because:** delete uses the same id that failed insert; no existence check before delete in the except path.
- **Suggested fix:** if id already exists, return a structured error before write; in except, only delete if this call inserted (or use transaction + only rollback new work).

### Reviewed and dropped (false positives / not bugs for Part 2)

| Initial suspicion | Why dropped |
|---|---|
| Vector flush lost on `add_finding` (old audit note) | Current code uses `maybe_flush(runtime, force=True)` after add/delete; prior finding is outdated for this path. |
| FAISS same-id double-add | `faiss` not installed in this env; numpy path overwrites cleanly; merge tests cover numpy. Not confirmed here. |
| Missing meta → dim 0 store | Intentional; `_load_store` / runtime recreate with settings dim when dim==0. |
| `.pkl` cache suffix vs JSON content | Misleading name only; load/save consistently use JSON text — works. |
| Packing interleave algorithm wrong for small N | Matches tests and documented “lost in the middle” placement; only trim-after-interleave is the bug. |
| Backup/restore path mapping | Uses explicit filenames + runtime shutdown; no defect confirmed in this pass. |

### Part 2 notes
- `vector_store.save_vector_store(..., merge_existing=True)` merge behavior for numpy is covered by tests and looks sound for add/delete pending sets.
- `build_contextual_chunk` duplicates claim/evidence/reasoning inside “Context:” prefix — quality/efficiency smell, not a functional error.

---

## Part 3 — Retrieval pipeline

**Scope:** `openlmlib/retrieval.py`, `query_expansion.py`, `decomposition.py`, `reranking.py`, `summary_gen.py`

### Confirmed

#### 1. Lexical hits drop `tags` / `evidence` / `reasoning` / `caveats`
- **Severity:** High  
- **Status:** Confirmed  
- **Refs:** `openlmlib/db.py:410-415`, `openlmlib/retrieval.py:531-554`, `openlmlib/retrieval.py:601-618`  
- **Evidence:**
  - `search_findings_filtered` SELECT is only `id, project, claim, confidence, created_at, status, rank`.
  - It joins `findings_text` for filters but does not select text columns.
  - `_to_result` then defaults missing fields to `[]` / `""`.
  - Verified pure-lexical path (empty vector store): item has `evidence=[]`, `tags=[]`, `reasoning=""`, `caveats=[]` even though DB has full text.
  - Semantic path is fine because `get_findings_by_embedding_ids` loads text fields.
- **Impact:** Keyword-only retrieval (cold index, FAISS miss, or lexical-only candidates) returns hollow findings; rerank/decompose/sanitize get no evidence/reasoning; users/MCP see incomplete results.
- **Not a false positive because:** reproduced with a real insert + empty vector store search.
- **Suggested fix:** SELECT and parse `ft.tags`, `ft.evidence`, `ft.reasoning`, `ft.caveats` (and domain/paper if needed) in `search_findings_filtered`, or hydrate via `get_finding` / batch text join after FTS.

#### 2. Archived (and non-active) findings still appear in retrieval
- **Severity:** High  
- **Status:** Confirmed  
- **Refs:** `openlmlib/db.py:410-425`, `openlmlib/retrieval.py:496-529`, `openlmlib/retrieval.py:660-686`, `openlmlib/maintenance.py` archive paths  
- **Evidence:**
  - Lexical SQL has no `status` predicate; filters only project/tags/dates/confidence.
  - Semantic path uses embedding lookup + `_passes_filters` — also no status check.
  - Verified: after `UPDATE findings SET status='archived'`, both FTS and `engine.search` still return the finding with `status='archived'`.
  - Archive is a soft-delete used by maintenance/CLI; retrieval ignores it.
- **Impact:** Soft-archived / pending_review-status rows keep polluting search and prompts.
- **Not a false positive because:** dynamic check returned archived hit; filter helpers have no status branch.
- **Suggested fix:** default to `status = 'active'` (or exclude `archived`) in FTS and `_passes_filters`; optional override filter if needed.

#### 3. Decomposition hard-caps at 5 findings, ignoring `final_k`
- **Severity:** Medium  
- **Status:** Confirmed  
- **Refs:** `openlmlib/decomposition.py:109-131`, `openlmlib/decomposition.py:152-169`, `openlmlib/retrieval.py:441-447`  
- **Evidence:**
  - `decompose_and_recompose(..., max_findings=5)` default is always used.
  - `_decompose` never passes `final_k` or candidate length.
  - Verified: 12 relevant candidates → recomposed length **5**.
  - Default enhanced path has `decompose=True`; later `candidates[:final_k]` cannot recover dropped items.
- **Impact:** Enhanced retrieval silently truncates below requested `final_k` when `final_k > 5`, or drops mid-ranked candidates before dedup/pack.
- **Not a false positive because:** default max is hardcoded and call site does not override it.
- **Suggested fix:** pass `max_findings=max(final_k, len(candidates))` or disable count cap when only section-filtering is intended.

#### 4. `max_context_tokens` API flag is ignored
- **Severity:** Medium  
- **Status:** Confirmed  
- **Refs:** `openlmlib/library.py:649-670`, `openlmlib/retrieval.py:29-30`, `openlmlib/retrieval.py:176-179`, `openlmlib/retrieval.py:462-488`  
- **Evidence:**
  - `retrieve_findings_enhanced(..., max_context_tokens=...)` sets `Phase4Options.max_context_tokens`.
  - `search_enhanced` never reads `options.max_context_tokens`.
  - `_pack_context` always uses `settings.phase4.packing.max_tokens`.
- **Impact:** Callers/MCP cannot override packing budget per request; parameter is dead.
- **Not a false positive because:** source has no use of `options.max_context_tokens` outside construction.
- **Suggested fix:** `ContextPacker(max_tokens=options.max_context_tokens or pack_settings.max_tokens)`.

#### 5. Query expansion can duplicate the original query (case-fold bug)
- **Severity:** Low  
- **Status:** Confirmed  
- **Refs:** `openlmlib/query_expansion.py:56-69`, `openlmlib/query_expansion.py:71-74`  
- **Evidence:**
  - Dedup set stores `v.strip().lower()`, but `include_original` checks `query.strip() not in seen` (case-sensitive).
  - Rule-based list already starts with the original query.
  - Verified: `expand('Hello Cache')` → `['Hello Cache', 'Hello Cache', 'Hello Cache caching strategy implementation']`.
  - Lowercase original does not double-insert the same string, but still wastes a variant slot when other transforms equal the original under normalization.
- **Impact:** Fewer distinct expanded queries than `max_variants` implies; redundant retrieval work when expansion is enabled.
- **Not a false positive because:** reproduced; branch condition is clearly case-mismatched with `seen`.
- **Suggested fix:** check `query.strip().lower() not in seen`, and/or skip re-insert when rule-based already included original.

### Reviewed and dropped (false positives / not bugs for Part 3)

| Initial suspicion | Why dropped |
|---|---|
| Double semantic oversample when rerank on | Intentional candidate widening before rerank. |
| Cross-encoder reloaded every `_rerank` call | Perf cost, not incorrect results; has fallback on error. |
| `pending_review` from age vs DB status | Age-based staleness flag is intentional; separate from archive status bug above. |
| `summary_gen` extractive quality | Heuristic by design; no functional crash/incorrect API contract found. |
| Hybrid score min-max flattening ties to 0.5 | Documented normalize edge case; ranking still stable via sort keys. |

### Part 3 notes
- Packing quality issue (trim-after-interleave) already recorded under Part 2; still applies when `pack_context=True` here.
- Reranker import/model failures correctly fall back to unre-ranked candidates.

---

## Part 4 — Runtime & CLI

**Scope:** `openlmlib/runtime.py`, `cli.py`, `maintenance.py`, `evaluation.py`, `usage_analytics.py` (+ library maintenance wrappers)

### Confirmed

#### 1. Consolidation claims to merge evidence/tags but only archives siblings
- **Severity:** High  
- **Status:** Confirmed  
- **Refs:** `openlmlib/maintenance.py:208-262`  
- **Evidence:**
  - Docstring: “merges evidence/tags from others. Archives the rest.”
  - Implementation: only `UPDATE findings SET status='archived', content_hash=...` for non-target rows; no read/merge of `findings_text`.
  - Verified: survivor keeps only its own tags/evidence after consolidate.
- **Impact:** Auto-consolidation silently loses sibling evidence/tags; knowledge is archived, not merged.
- **Not a false positive because:** behavior contradicts documented API and was reproduced.
- **Suggested fix:** load text rows, union tags/evidence/caveats into survivor (and JSON file), then archive; or change docstring and rename to “archive_duplicates”.

#### 2. `consolidate_group(keep_id=...)` ignores caller choice
- **Severity:** Medium  
- **Status:** Confirmed  
- **Refs:** `openlmlib/maintenance.py:221-235`  
- **Evidence:**
  - `target_id = keep_id or group.representative_id` is immediately overwritten by `target_id = best["id"]` (highest confidence).
  - Verified: requested `keep_id="keep-me"` (conf 0.5) → target became `drop-me` (conf 0.9); `keep-me` archived.
- **Impact:** Explicit keep preference is dead; callers cannot protect a lower-confidence canonical finding.
- **Suggested fix:** honor `keep_id` when provided; only fall back to max confidence when omitted.

#### 3. Consolidation overwrites `content_hash` with a non-hash marker
- **Severity:** Medium  
- **Status:** Confirmed  
- **Refs:** `openlmlib/maintenance.py:244-246`  
- **Evidence:**
  - Archived rows get `content_hash = f"consolidated_into_{target_id}"`.
  - Elsewhere `content_hash` is SHA-256 of content (`schema.compute_content_hash`).
  - Verified stored value: `consolidated_into_a` (not a hex digest).
- **Impact:** Breaks any integrity/dedup logic that trusts `content_hash` as a content digest; pollutes the field’s meaning.
- **Suggested fix:** store consolidation pointer in audit/`failure_log`/new column; leave `content_hash` as content hash or clear to `""`.

#### 4. `log_tool_selection` stores unknown correctness as incorrect (`0`)
- **Severity:** Medium  
- **Status:** Confirmed  
- **Refs:** `openlmlib/usage_analytics.py:161-176`  
- **Evidence:**
  - When `is_correct is None` and `expected_tool is None`, code still does `1 if is_correct else 0` → `0`.
  - Verified: insert with both None → `is_correct = 0`.
  - Reports treat `is_correct = 1` as correct; unknowns inflate error rate.
- **Impact:** Selection accuracy metrics are wrong unless every row has a known label.
- **Suggested fix:** store SQL `NULL` when unknown; aggregate with `WHERE is_correct IS NOT NULL`.

#### 5. `find_stale_findings(status_filter=...)` is effectively dead
- **Severity:** Low  
- **Status:** Confirmed  
- **Refs:** `openlmlib/maintenance.py:79-89`  
- **Evidence:**
  - Query hardcodes `AND f.status = 'active'`, then may add `AND f.status = ?` for `status_filter`.
  - Verified: `status_filter="pending_review"` returns **0** rows even when stale actives exist (impossible dual status).
- **Impact:** Parameter cannot select non-active statuses; misleading API.
- **Suggested fix:** if `status_filter` set, use it instead of hardcoded `'active'`.

### Reviewed and dropped (false positives / not bugs for Part 4)

| Initial suspicion | Why dropped |
|---|---|
| CLI default ignores `resolve_hybrid_settings_path` | Default is global `~/.openlmlib/...` by design (README/docs); override via `--settings`. Hybrid is for scripts. |
| `maybe_flush(force=True)` with no dirty still returns True | Resets counters only; no incorrect I/O. Harmless. |
| `shutdown_runtime` swallows flush errors | Intentional best-effort teardown. |
| Empty retrieval precision = 0.0 | Expected with `max(1, len(top_k))` / empty expected handling. |
| Runtime singleflight / prewarm | Intentional; no correctness defect found. |
| CLI `rebuild-index` TypeError | Already filed under Part 2 (`batch_size`). |

### Part 4 notes
- Archived findings from consolidation remain in the vector index (no `store.delete`); combined with Part 3 status filter gap, consolidated “duplicates” can still surface in semantic search.
- `usage_analytics` logging itself is fine; MCP wraps `log_tool_call` in try/except so analytics failures do not break tools.

---

## Part 5 — MCP layer

**Scope:** `openlmlib/mcp_server.py`, `mcp_setup.py`, `tui_setup.py`

### Confirmed

#### 1. Aider MCP install writes JSON into a `.yml` config file
- **Severity:** High  
- **Status:** Confirmed  
- **Refs:** `openlmlib/mcp_setup.py:237-240`, `openlmlib/mcp_setup.py:350-366`  
- **Evidence:**
  - Target path is `~/.aider.conf.yml`.
  - Writer uses `json.dumps` for all non-TOML clients (including aider).
  - Verified install content starts with `{ "mcp_servers": { ... } }` — JSON, not YAML.
- **Impact:** Aider cannot parse the installed config as YAML; MCP registration for Aider is broken after `openlmlib setup` / `mcp-config --ide aider`.
- **Not a false positive because:** file path, serializer branch, and on-disk content all checked.
- **Suggested fix:** YAML dump for `.yml`/`.yaml` (and document Aider’s actual MCP config schema if different from nested JSON).

#### 2. `save_finding` session warning never reaches the caller
- **Severity:** Medium  
- **Status:** Confirmed  
- **Refs:** `openlmlib/mcp_server.py:940-942`, `openlmlib/mcp_server.py:970-988`, `openlmlib/library.py:354`  
- **Evidence:**
  - Tool docstring: “If no active session is detected, a warning will be returned.”
  - Code computes `_session_warning = _check_active_sessions()` and passes `session_warning=_session_warning` into `add_finding`.
  - `add_finding` marks `session_warning` as **deprecated** and never reads it in the body (only the parameter declaration).
  - Return payloads from `add_finding` have no `session_warning` field.
- **Impact:** Session-awareness guidance is a no-op; models never see the promised warning.
- **Not a false positive because:** dead parameter + docstring mismatch verified via source inspection.
- **Suggested fix:** attach `session_warning` on the MCP response dict (even when status is ok/rejected), or stop claiming it is returned.

#### 3. Interactive setup ignores the provided `settings_path`
- **Severity:** Medium  
- **Status:** Confirmed  
- **Refs:** `openlmlib/tui_setup.py:14-39`, `installer/src/ui/setup-wizard.js` (`global_settings_path()` only)  
- **Evidence:**
  - `run_interactive_setup(settings_path)` accepts a path and returns it in the success payload.
  - Subprocess is only `[node, run-setup.mjs]` — **no args/env** for settings.
  - Wizard scripts hardcode `global_settings_path()` / `~/.openlmlib`.
- **Impact:** `openlmlib --settings /custom/path setup` in interactive mode still configures the global home library, not the requested path.
- **Not a false positive because:** CLI passes `settings_path` into TUI, but TUI never forwards it.
- **Suggested fix:** pass settings path via env/CLI arg to the Node wizard and use it for `write_default_settings` / MCP install.

#### 4. Memory/collab tools are absent until `main()` runs registration
- **Severity:** Low (footgun)  
- **Status:** Confirmed  
- **Refs:** `openlmlib/mcp_server.py:77-183`, `openlmlib/mcp_server.py:186-790`, `openlmlib/mcp_server.py:1870-1885`  
- **Evidence:**
  - Import-time tool set is core only (~17 tools: `save_finding`, `init_library`, …).
  - Verified: after import, `create_session` / `query_memory` are **not** registered.
  - `_register_memory_tools()` / `_register_collab_tools()` run only inside `main()`.
  - Production `python -m openlmlib.mcp_server` is fine; tests must call register helpers explicitly.
- **Impact:** Alternate hosts that import `mcp` without calling `main()` expose an incomplete tool surface.
- **Suggested fix:** register lazy tools on first list-tools if FastMCP supports a hook, or document that `main()` is required.

### Reviewed and dropped (false positives / not bugs for Part 5)

| Initial suspicion | Why dropped |
|---|---|
| `init_library` name shadowing (old audit) | Fixed: tool calls `lib_init_library`; no recursion. |
| `--settings` ignored by server | `main()` sets `OPENLMLIB_SETTINGS` from `--settings` / `--dir` before tools run. |
| Qwen/Gemini config clobber | Verified merge keeps existing keys (`model`, etc.) and adds `mcpServers`. |
| Codex TOML write | Writes valid simple TOML table for `mcp_servers.openlmlib`. |
| OpenCode missing `type` | `build_server_entry` sets `type: local` for opencode. |
| `search_knowledge` hybrid routing | Uses `lib_retrieve_findings`; tests cover path; fallback to FTS on exception is intentional. |

### Part 5 notes
- Duplicate `similarity_rank` crash on MCP `save_finding` remains filed under Part 2 (still live via `similar_findings`).
- `tui_setup` Node dependency is intentional for the wizard UX.

---

## Part 6 — Memory

**Scope:** `openlmlib/memory/*` (storage, session_manager, retriever, context_builder, compressor, privacy, hooks, knowledge_extractor, retrogit_ingest, observation_queue, caveman_compress) + memory MCP wiring in `mcp_server.py`

### Confirmed

#### 1. Session restart / reuse always fails with `IntegrityError`
- **Severity:** High  
- **Status:** Confirmed  
- **Refs:** `openlmlib/memory/storage.py:181-187`, `openlmlib/memory/session_manager.py:128-136`, `openlmlib/memory/storage.py:198-221`  
- **Evidence:**
  - `create_session` always `INSERT`s; no upsert/resume path.
  - `end_session` only sets `ended_at`; row stays (PK still taken).
  - Dynamic: second `create_session('s1')` → `IntegrityError: UNIQUE constraint failed`.
  - Dynamic: `SessionManager.on_session_start` after process-like re-init (same DB, empty `active_sessions`) → same crash.
  - Dynamic: after `end_session`, re-`create_session` same id still fails.
- **Impact:** Reusing a session_id (common agent pattern, or MCP process restart) hard-fails; `session_start` cannot resume.
- **Not a false positive because:** reproduced end-to-end on SQLite + SessionManager.
- **Suggested fix:** upsert/resume: if row exists, clear `ended_at` (or open new id); treat ended sessions as reopenable.

#### 2. `retroactive_ingest` writes to a different DB than the MCP memory tools
- **Severity:** High  
- **Status:** Confirmed  
- **Refs:** `openlmlib/memory/retrogit_ingest.py:256-267`, `openlmlib/memory/retrogit_ingest.py:316-321`, `openlmlib/mcp_server.py:753-778`, `openlmlib/mcp_server.py:61-63`  
- **Evidence:**
  - `retroactive_ingest` always does `get_runtime(Path("config/settings.json"))` and builds its **own** `MemoryStorage`.
  - Dynamic: MCP settings resolve to `~/.openlmlib/.../findings.db`; hardcode resolves to cwd-relative `data\findings.db` (and `config/settings.json` often **missing**).
  - Observations are inserted via that private storage; MCP wrapper only re-saves **knowledge** onto the shared storage.
- **Impact:** Git-ingest observations land in the wrong (or ephemeral) library; knowledge can appear without matching observations in the active DB.
- **Not a false positive because:** dual runtime paths verified; settings paths differ on a real machine.
- **Suggested fix:** accept `storage`/`settings_path` from caller; MCP must pass `_get_memory_state()["storage"]` and never open a second runtime.

#### 3. `MemoryInjectionSettings` is entirely dead config
- **Severity:** Medium  
- **Status:** Confirmed  
- **Refs:** `openlmlib/settings.py:84-96`, `openlmlib/settings.py:185-197`, `openlmlib/mcp_server.py:61-66`  
- **Evidence:**
  - Settings define: `enabled`, `observations_at_session_start`, `auto_log_tool_use`, `progressive_disclosure`, `max_context_tokens`, `privacy_filtering`, `compression_enabled`, `max_observations_per_session`, `session_cleanup_days`, `caveman_*`.
  - Repo-wide search: **zero** reads of `settings.memory.*` / `memory.max_*` / etc. in `openlmlib/`.
  - MCP constructs `ContextBuilder(retriever)` with defaults only; no cap on observations; no cleanup job; privacy always on via hard-coded `sanitize_for_storage`.
  - Dynamic: unlimited `add_observation` succeeds past any conceptual 500 cap.
- **Impact:** Documented memory knobs (docs + settings.json) do nothing; operators cannot tune limits/cleanup/caveman from config.
- **Suggested fix:** wire settings into `_get_memory_state`, session start limit, compressor, cleanup, and optional privacy toggle.

#### 4. `session_start` / `inject_context` report wrong observation counts
- **Severity:** Medium  
- **Status:** Confirmed  
- **Refs:** `openlmlib/mcp_server.py:227-239`, `openlmlib/mcp_server.py:489-497`, `openlmlib/memory/session_manager.py:164-170`  
- **Evidence:**
  - `session_start` returns `observation_count: context.get("observation_count", 0)` where `context` is the **lifecycle** response (`status`, `injected_context`, …) — no such key → always **0**.
  - Dynamic: `on_session_start` keys are `session_id, status, context_injected, injected_context, hook_results` only.
  - `inject_context` returns `"observation_count": limit` and `"estimated_tokens": limit * 75` regardless of how many memories were actually injected (builder returns a plain string, not a count).
- **Impact:** Agents get false telemetry; empty vs full injection looks identical on `session_start`.
- **Suggested fix:** return counts from `auto_inject_context` / `build_session_start_context` (dict with `observation_count`).

#### 5. Progressive layer-2 `window` is a no-op; query expansion threshold rarely fires
- **Severity:** Low  
- **Status:** Confirmed  
- **Refs:** `openlmlib/memory/memory_retriever.py:126-167`, `openlmlib/mcp_server.py:435-441`, `openlmlib/memory/memory_retriever.py:344-363`  
- **Evidence:**
  - `layer2_timeline(..., window=...)` docstring: “not yet implemented”; body ignores `window`.
  - `_calculate_confidence` base is **0.5**; needs compressed_summary (+0.2) and facts+concepts (+0.2) to exceed `query_memory`’s `> 0.6` core gate.
  - Dynamic: uncompressed obs → confidence `0.5` → `core_ids` empty → only top-1 expanded.
  - Compression only runs at `session_end`, so mid-session / raw logs stay at 0.5.
- **Impact:** Timeline window API misleads; adaptive “core” expansion often degrades to single full detail.
- **Suggested fix:** implement window or remove param; lower threshold or score by text match/recency without requiring compression.

### Reviewed and dropped (false positives / not bugs for Part 6)

| Initial suspicion | Why dropped |
|---|---|
| Privacy never runs | Always applied in `add_observation` / `on_tool_use` via `sanitize_for_storage`. |
| FK cascade broken | Dynamic: cleanup after end deletes observations/summaries/knowledge (CASCADE works). |
| `MemoryStorage.close` used by MCP | MCP never closes storage; shared-conn close is a footgun only if callers use context manager. |
| ObservationQueue broken | Unwired/incomplete feature; not on live MCP path. |
| `default_observation_processor` mutates nothing | Documented placeholder; not registered by production wiring. |
| Default hooks do real work | By design stubs; real work is in SessionManager methods. |

### Part 6 notes
- Knowledge synthesis at `session_end` works when observations exist; gap is mostly lifecycle resume + config + git ingest isolation.
- Caveman compression path is functional when enabled on compressor/context builder defaults.

---

## Part 7 — Collab core

**Scope:** `openlmlib/collab/db.py`, `session.py`, `message_bus.py`, `state_manager.py`, `security.py`, `artifact_store.py`, `rules_engine.py`, `context_compiler.py`, `notification.py`, `errors.py`, and core tools in `collab_mcp.py` (create/join/leave/terminate/send/read/poll/state/claim)

### Confirmed

#### 1. Generated agent IDs are rejected by security validation (model names with `.` / `:`)
- **Severity:** High  
- **Status:** Confirmed  
- **Refs:** `openlmlib/collab/session.py:41-44`, `openlmlib/collab/security.py:29-77`, `openlmlib/collab/collab_mcp.py:666-668`  
- **Evidence:**
  - `_generate_agent_id` only replaces spaces and `/` — keeps `.` and `:` (e.g. `gpt-4.1` → `agent_gpt-4.1_<hex>`).
  - `AGENT_ID_RE` allows only `[a-zA-Z0-9_\-]`.
  - Dynamic: `create_session(..., created_by="gpt-4.1")` succeeds and returns `agent_gpt-4.1_…`.
  - Dynamic: `send_message(..., from_agent=that_id)` fails: `Invalid agent_id format` / `security_error`.
  - Same for `claude-3.5-sonnet`, `google/gemini-2.0-flash`, `qwen2.5-coder:7b`.
- **Impact:** Sessions created with common model IDs cannot use MCP tools that validate `agent_id` (send, leave, terminate, state updates).
- **Not a false positive because:** create path + MCP send path both exercised live.
- **Suggested fix:** sanitize model segment to `[a-zA-Z0-9_-]` only (map `.`/`:` → `-`) **or** widen the regex to match generators.

#### 2. `to_agent="any"` is blocked by MCP validation
- **Severity:** High  
- **Status:** Confirmed  
- **Refs:** `openlmlib/collab/collab_mcp.py:669-670`, `openlmlib/collab/db.py:517-521`  
- **Evidence:**
  - Message readers treat `to_agent = 'any'` as a valid open/broadcast target.
  - `send_message` runs `validate_agent_id(to_agent)` for any non-empty `to_agent`.
  - Dynamic: `send_message(..., to_agent="any")` → `SecurityError: Invalid agent_id format: any`.
  - Context/task language and templates assume open assignment via `"any"`.
- **Impact:** Cannot address open tasks / unassigned workers via the documented `any` sentinel.
- **Suggested fix:** allow `to_agent in {None, "", "any"}` without agent-id regex; only validate real agent IDs.

#### 3. `RulesEngine` is never applied on live paths
- **Severity:** Medium  
- **Status:** Confirmed  
- **Refs:** `openlmlib/collab/rules_engine.py`, `openlmlib/collab/session.py`, `openlmlib/collab/collab_mcp.py`, `openlmlib/collab/templates.py`  
- **Evidence:**
  - Templates store `require_assignment`, `require_artifact_for_results`, `max_pending_tasks`, etc.
  - `RulesEngine` is exported from the package but **not** referenced by `session.py` or `collab_mcp.py` (source inspection).
  - Only partial rule use: `join_collab_session` reads `rules.max_agents` directly.
  - `MessageBus` enforces result template structure independently; does not consult session rules for `require_artifact_for_results`.
- **Impact:** Documented/template rules are mostly decorative; operators cannot enforce assignment or artifact requirements.
- **Suggested fix:** call `RulesEngine` from join / send_message / task insert paths.

#### 4. Terminate writes status `completed`, not `terminated`
- **Severity:** Medium  
- **Status:** Confirmed  
- **Refs:** `openlmlib/collab/session.py:343-346`, `openlmlib/collab/db.py:23`, `openlmlib/collab/collab_mcp.py:474`  
- **Evidence:**
  - `terminate_collab_session` calls `update_session_status(..., "completed")`.
  - Dynamic: after terminate, `sessions.status == "completed"`.
  - Schema and docs also list `"terminated"`; `list_sessions(status="terminated")` returns empty for ended sessions.
  - `poll_messages` correctly treats both `completed` and `terminated` as ended.
- **Impact:** Status filter / tooling that looks for `terminated` never sees ended sessions; status vocabulary is inconsistent.
- **Suggested fix:** write `terminated` (or map both in list filters and document one canonical end state).

#### 5. `poll_messages` advances read offset even when filters are applied
- **Severity:** Medium  
- **Status:** Confirmed  
- **Refs:** `openlmlib/collab/collab_mcp.py:805-807` vs `898-901` and `965-967`  
- **Evidence:**
  - `read_messages` only updates offset when `not msg_types and from_agent is None`.
  - `poll_messages` always `save_offset` to the last returned message when any messages are returned, including filtered polls.
- **Impact:** Filtering `poll_messages(msg_types=["result"])` can permanently skip intervening `task`/`question` messages (offset jumps past them).
- **Suggested fix:** match `read_messages` offset policy, or track separate filtered cursors.

### Reviewed and dropped (false positives / not bugs for Part 7)

| Initial suspicion | Why dropped |
|---|---|
| Seq assignment race | Concurrent multi-connection sends produced 80 unique seqs, 0 errors. |
| FTS triggers broken | Standard content= FTS5 pattern; no failure found in core path. |
| Orchestrator verify broken | Compatible with agent_id + legacy model-name orchestrator column. |
| Notification clear race | `clear_notification` is intentionally a no-op; seq-based wait is correct. |
| join role always worker | MCP omits role param (limitation); lower-level `join_collab_session` supports observer — note only, not a core crash. |

### Part 7 notes
- Result-message template enforcement in `MessageBus.send` is real and working (rejects unstructured `result` content).
- Artifact store path sanitization for agent dirs is reasonable; file content paths are absolute on insert.

---

## Part 8 — Collab advanced

**Scope:** `export_bridge.py`, `templates.py`, `compactor.py`, `multi_session.py`, `openrouter_client.py`, advanced MCP tools (export, templates, multi-session, artifacts, session_context)

### Confirmed

#### 1. Export to library maps write-gate rejections as `"Unknown error"` and often fails
- **Severity:** High  
- **Status:** Confirmed  
- **Refs:** `openlmlib/collab/export_bridge.py:91-114`, `openlmlib/library.py` (`status: rejected` + `issues`)  
- **Evidence:**
  - On non-`ok`, bridge uses `result.get("error", "Unknown error")`.
  - `add_finding` returns `issues` (list), not `error`.
  - Dynamic: export of a normal artifact → `exported: 0`, `failures: [{reason: "Unknown error"}]`.
  - Direct `add_finding` with same payload: `status=rejected` with claim/evidence similarity below 0.7 (write gate).
  - Export builds a fixed short `reasoning` string and uses artifact **title** as claim vs full body as evidence — often low similarity.
- **Impact:** Export appears broken; agents cannot diagnose rejections; many real sessions fail to land findings.
- **Suggested fix:** surface `issues`/`status`; use body-derived claim/evidence pairs or `confirm`/gate bypass path for trusted collab export; raise reasoning quality.

#### 2. Custom templates resolve `data_root` against CWD, not settings parent
- **Severity:** High  
- **Status:** Confirmed  
- **Refs:** `openlmlib/collab/templates.py:119-145` vs `openlmlib/collab/collab_mcp.py:129-143`  
- **Evidence:**
  - Collab MCP: relative `data_root` → `settings_path.parent / data_root`.
  - Templates: relative `data_root` → bare `Path("data")` (CWD).
  - Dynamic: with settings at `.../cfg/settings.json` and `data_root: "data"` → collab DB under `cfg/data/`, templates under cwd `data/collab_templates`.
- **Impact:** Custom templates saved by one client are invisible to another; diverges from collab session storage root.
- **Suggested fix:** same resolve logic as `_get_collab_paths` (`settings_path.parent / data_root`).

#### 3. `create_template` allows path-escaping `template_id`
- **Severity:** Medium  
- **Status:** Confirmed  
- **Refs:** `openlmlib/collab/templates.py:172-180`  
- **Evidence:**
  - Filename is `templates_dir / f"{template_id}.json"` with no sanitize.
  - Dynamic: `create_template("..\\evil", ...)` wrote `data/evil.json` **outside** `collab_templates/`.
- **Impact:** Arbitrary JSON write under parent of templates dir (path traversal).
- **Suggested fix:** reject non-`[a-zA-Z0-9_-]` ids; resolve and assert path stays under templates dir.

#### 4. Auto-compaction never runs on the MCP path
- **Severity:** Medium  
- **Status:** Confirmed  
- **Refs:** `openlmlib/collab/compactor.py:193-213`, `openlmlib/cli.py:691-703`, templates `auto_compact_after_messages`  
- **Evidence:**
  - `SessionCompactor.check_and_compact` exists; CLI can call `compact_session`.
  - No MCP tool and no send/read hook invokes compaction.
  - Template rules set `auto_compact_after_messages` but nothing reads them on live MCP traffic.
- **Impact:** Long sessions never auto-summarize; context grows without the advertised compaction.
- **Suggested fix:** call `check_and_compact` after send (or periodic) using session rules threshold.

#### 5. `session_context` refuses non-active sessions
- **Severity:** Medium  
- **Status:** Confirmed  
- **Refs:** `openlmlib/collab/collab_mcp.py:1155-1156`, `openlmlib/collab/security.py:169-186`  
- **Evidence:**
  - Tool calls `verify_session_exists_and_active` before compile.
  - Dynamic: after terminate → `SessionNotActiveError`.
  - Export/docs expect post-completion review; membership reads use `_require_reader_access` (allows non-active) elsewhere.
- **Impact:** Cannot review context of completed sessions via the primary context tool.
- **Suggested fix:** allow read-only context for members of completed sessions (same as export’s `require_active=False`).

#### 6. Multi-session “agent history” is per ephemeral agent_id, not per model/user
- **Severity:** Low  
- **Status:** Confirmed  
- **Refs:** `openlmlib/collab/session.py:41-44`, `openlmlib/collab/multi_session.py:15-44`, `openlmlib/collab/collab_mcp.py:1663-1696`  
- **Evidence:**
  - Every create/join mints a new `agent_*_<hex>` id.
  - `get_agent_sessions` filters exact `agent_id`.
  - Dynamic: two sessions by same model → different orchestrator ids; each query returns only one session.
- **Impact:** “What sessions have I been in?” only works if the agent retained the exact id; no model-level history.
- **Suggested fix:** index/query by model + role, or stable user-supplied agent identity.

### Reviewed and dropped (false positives / not bugs for Part 8)

| Initial suspicion | Why dropped |
|---|---|
| Export skips auth | MCP requires orchestrator + `verify_agent_in_session(..., require_active=False)`. |
| OpenRouter client broken | Offline-safe; needs API key; not a core logic defect. |
| Compactor total-message formula | Matches max_seq for exercised cases. |
| Relationships leak without filter | MCP always passes `agent_id` and filters to membership. |

### Part 8 notes
- Artifact save + task auto-complete by `artifact_type` in description is intentional and wired.
- OpenRouter model list is optional infrastructure; skipped deep network testing.

---

## Part 9 — Co-scientist

**Scope:** `openlmlib/co_scientist/*` (orchestrator, hypothesis, evidence, ranking, policy, reporting, templates, evaluation, worker_runner) + Co-Scientist MCP tools in `collab_mcp.py`

### Confirmed

#### 1. Stale clients can overwrite run state (lost updates) — RECLASSIFIED
- **Severity:** Medium (was High)  
- **Status:** Partially confirmed / original claim overstated  
- **Refs:** openlmlib/co_scientist/orchestrator.py:654-691, openlmlib/collab/db.py:934-959  
- **Reanalysis (2026-07-12):**
  - _write_run_state_to_sessions does pass expected_version=row["version"] into update_session_state.
  - On mismatch, update returns False and the writer raises CoScientistRunError (state_conflict) — **stale writers do not silently overwrite**.
  - Reproduced CAS logic: client A (v1→v2) succeeds; client B (still expected v1) fails; A's phase=verification is preserved.
  - Original “A's progress erased / silent clobber” is a **false positive**.
- **What remains real:**
  - Writers still replace the **entire** co_scientist_run blob from a previously loaded copy (no field-level merge). Concurrent successful writers must reload after state_conflict or they can drop each other's *unsynced* in-memory edits if they incorrectly retry without reload.
  - Dual-session write (generation + verification) can leave partial inconsistency if the first session updates and the second hits a version conflict mid-loop.
- **Impact:** Lost updates are prevented by CAS errors, not silent; concurrency UX is still brittle (retry/reload required).
- **Suggested fix:** re-load + merge under one transaction; surface state_conflict clearly to MCP clients; make dual-session write atomic.

#### 2. Co-Scientist mutations have no agent membership / role checks
- **Severity:** High  
- **Status:** Confirmed  
- **Refs:** `openlmlib/co_scientist/orchestrator.py:169-247`, `273-362`, `365-471`; `reporting.py:30-55`; MCP wrappers pass `created_by` through  
- **Evidence:**
  - `submit_hypothesis(..., created_by=...)` uses any string as artifact `created_by` / message sender.
  - Dynamic: `created_by='agent_not_a_member_zzzz'` succeeds; artifact stored under that id (not in `agents` table).
  - Same pattern for verification handoff, reports, and final report (`created_by or verification_orchestrator_agent_id` only as default).
- **Impact:** Unauthenticated spoofing of who submitted packets/reports; breaks audit and collab security model.
- **Suggested fix:** require `verify_agent_in_session` on the relevant gen/verify session; restrict orchestration actions to session orchestrators.

#### 3. Starting verification marks **all** generation tasks completed
- **Severity:** Medium  
- **Status:** Confirmed  
- **Refs:** `openlmlib/co_scientist/orchestrator.py:331-335`, `862-883`  
- **Evidence:**
  - `_complete_open_session_tasks` completes every non-completed task in the session.
  - Dynamic: generation plan still has pending scout/critic/rank steps; after `start_hypothesis_verification` → **all 6 tasks `completed`**.
- **Impact:** Template workflow progress lies; agents think reflection/ranking finished when only handoff ran.
- **Suggested fix:** complete only handoff-related tasks (or tasks matching artifact types), not the entire plan.

#### 4. Supported-finding export drops write-gate detail (often fails silently for agents)
- **Severity:** Medium  
- **Status:** Confirmed  
- **Refs:** `openlmlib/co_scientist/reporting.py:337-381`  
- **Evidence:**
  - On reject: `reason = result.get("message") or result.get("error") or "export rejected"`.
  - `add_finding` returns `issues`, not `message`/`error` (same class of bug as Part 8 export).
  - Dynamic: supported hypothesis export → `failed: 1`, `reason: "export rejected"` with no similarity/confidence detail.
- **Impact:** Operators cannot fix export failures; verified claims never reach the library.
- **Suggested fix:** pass through `issues`; align claim/evidence text for write-gate or use a trusted export path.

#### 5. External URL citations are “valid” with no reachability check
- **Severity:** Low  
- **Status:** Confirmed (by design, still a quality gap)  
- **Refs:** `openlmlib/co_scientist/evidence.py:155-163`  
- **Evidence:**
  - Any `http(s)://` with a netloc resolves as valid; comment admits network not checked.
  - Dynamic: full run succeeded with only `https://example.com/paper`.
- **Impact:** Verification can rubber-stamp fake URLs as citations.
- **Suggested fix:** optional HEAD check, or require artifact/local path for high confidence.

### Reviewed and dropped (false positives / not bugs for Part 9)

| Initial suspicion | Why dropped |
|---|---|
| Dual gen/verify orchestrator IDs | Intentional (two sessions, two agents). |
| Scope screen blocks defense research | Conservative policy; working as designed. |
| Empty `disconfirming_evidence` rejected | Intentional validation (forces explicit “none found”). |
| Worker runner vs Phase 0 “no spawn” docs | Optional external runner; not auto-invoked by MCP create path. |
| Ranking/clustering math | Deterministic unit-style logic; no failure found in review pass. |
| Silent concurrent overwrite of run state (original Part 9.1 claim) | expected_version CAS rejects stale writers; A is not erased. Residual: full-blob replace + dual-session partial write risk (reclassified Medium). |

### Part 9 notes
- Happy path (create → submit → start verification → submit report → final report) works end-to-end when citations are URLs and reports are complete.
- Run state stored in both session `state_json` blobs is powerful but makes concurrency harder.

---

## Part 10 — Installer / scripts / tests smoke

**Scope:** `installer/*`, root `package.json`, `install.ps1` / `install.sh`, `scripts/*`, `.github/workflows/ci.yml`, `pyproject.toml` test metadata, unit-test smoke

### Confirmed

#### 1. Interactive (TTY) npm install never finds bundled Python source
- **Severity:** High  
- **Status:** Confirmed  
- **Refs:** `installer/src/postinstall.mjs:415-420`, `installer/src/ui/app.js:99`, `installer/src/install.js:90-98`, `installer/src/install.js:144-176`  
- **Evidence:**
  - TTY postinstall runs Ink UI → `installFromLocal(path.resolve(installerDir, '..', '..'), ...)`.
  - `installerDir` is `.../openlmlib/src`, so seed is **`node_modules`**, not the package root that holds bundled `openlmlib/` + `pyproject.toml`.
  - `install.js` only discovers seed/cwd parents; **no** Priority-1 “bundled package root” check (unlike non-interactive `postinstall.mjs:193-204`).
  - Dynamic layout sim (cwd outside monorepo): package root **has** project; seed/cwd candidates **NONE** → throws “Bundled OpenLMlib Python source was not found…” unless `OPENLMLIB_ALLOW_NETWORK_INSTALL_FALLBACK=1`.
- **Impact:** Global/local `npm install` on a real terminal fails Python install even when the tarball correctly bundled source; non-TTY CI path works.
- **Suggested fix:** seed with package root (`path.resolve(installerDir, '..')`) and/or port postinstall’s bundled-source candidate into `installFromLocal`.

#### 2. CI `npm ci` cannot run on a clean clone (lockfile gitignored)
- **Severity:** High  
- **Status:** Confirmed  
- **Refs:** `.gitignore:55`, `.github/workflows/ci.yml:86-91`, `installer/package.json`  
- **Evidence:**
  - `installer/package-lock.json` is listed in `.gitignore` and **not** tracked (`git ls-files` empty).
  - Workflow runs `cache-dependency-path: installer/package-lock.json` then `npm ci` in `installer/`.
  - Dynamic: copy only `package.json` into temp dir → `npm ci` exits with `EUSAGE` (“can only install with an existing package-lock.json”).
- **Impact:** `npm-installer-smoke` job is broken for any fresh checkout; cache key also useless.
- **Suggested fix:** stop ignoring the lockfile, commit a regenerated lock, keep `npm ci`; or switch CI to `npm install` and drop lock cache.

#### 3. Python discovery never tries the `python` command
- **Severity:** Medium  
- **Status:** Confirmed  
- **Refs:** `installer/src/postinstall.mjs:18-34`, `installer/src/install.js:14-30`  
- **Evidence:**
  - Order is only `python3` then `py`; no fallback to `python`.
  - Common Windows python.org installs expose `python` without `python3` / without `py` on PATH.
- **Impact:** Prerequisite checks report “Python not found” and abort install despite a valid 3.10+ interpreter.
- **Suggested fix:** try `python` last (or `py -3` with version args) and validate `major.minor >= 3.10`.

#### 4. Test runner docs / dev extras disagree with CI and the suite
- **Severity:** Low  
- **Status:** Confirmed  
- **Refs:** `README.md:365`, `pyproject.toml:44`, `.github/workflows/ci.yml:38-39`, `CONTRIBUTING.md:17`  
- **Evidence:**
  - All `tests/test_*.py` use `unittest`; none import `pytest`.
  - CI + CONTRIBUTING: `python -m unittest discover ...`
  - README still says `python -m pytest tests/ -v`; `[project.optional-dependencies] dev` only lists `pytest` / `pytest-cov`.
  - Dynamic smoke: `unittest discover -s tests -p "test_*.py"` → **313 tests OK** in ~11s (local venv).
- **Impact:** Contributors follow README and hit missing pytest; `pip install -e ".[dev]"` does not match the runner CI uses.
- **Suggested fix:** align README + `dev` extras with unittest (or adopt pytest fully and update CI).

### Reviewed and dropped (false positives / not bugs for Part 10)

| Initial suspicion | Why dropped |
|---|---|
| Bundled tarball missing README/LICENSE breaks `pip install -e` | Dynamic: editable install of package root with only `openlmlib/` + `pyproject.toml` succeeded. |
| Root `package.json` `cd installer && …` broken on Windows | `npm run pack` succeeded; npm script shell handles `&&`. |
| `test-install.js` only inspects tarball | Script performs real temp `npm install`, bin `--help`, and MCP tool-count assert (≥76). |
| Unit suite generally red | Full discover: 313 OK. |
| `install.ps1` / `install.sh` pipx path | Straightforward repo-root pipx install; no defect found in smoke review. |
| Diagnostic scripts Windows-only examples | Docstrings only; scripts themselves are portable. |

### Part 10 notes
- Non-interactive postinstall (no TTY) correctly prefers bundled source and validates ≥76 MCP tools — good path for CI/automation.
- `npm pack` / prepack bundle + postpack cleanup works; tarball includes Python sources.
- Prefer fixing interactive seed + committing the lockfile before relying on the npm smoke job in CI.

---

## Review progress

| Part | Scope | Status |
|------|--------|--------|
| 1 | Foundation | Done |
| 2 | Storage & embeddings | Done |
| 3 | Retrieval pipeline | Done |
| 4 | Runtime & CLI | Done |
| 5 | MCP layer | Done |
| 6 | Memory | Done |
| 7 | Collab core | Done |
| 8 | Collab advanced | Done |
| 9 | Co-scientist | Done |
| 10 | Installer / scripts / tests smoke | Done |

---

## Reanalysis (2026-07-12)

Method: independent static re-read of every “Confirmed” finding against current openlmlib/ + installer/ sources, plus targeted dynamic checks (bool parse, encode signature, duplicate KeyError, FTS INSERT OR REPLACE, lock reclaim, agent_id generation vs regex, query expansion, write-gate empty evidence, packing max_context_tokens, memory settings refs, CAS version update).

### Verdict summary

| Outcome | Count (approx.) | Notes |
|---|---|---|
| Confirmed true positives | ~46 | Core crashes, security/validation mismatches, dead config, installer CI issues hold. |
| Overstated / reclassified | 1 | Part 9.1 “silent lost update” — CAS blocks overwrite; residual concurrency UX is Medium. |
| Intentional quality gaps (kept) | several | e.g. URL citation reachability, PermissionError-as-dead PID on multi-user Unix. |
| Already-marked latent / low | several | FTS INSERT OR REPLACE latent, multi-session agent history model, docs/pytest mismatch. |

### Confirmed true positives (spot-checked live)

- **P1.1** Empty evidence: alidate / _encode_claim_evidence raise on strict embedder (RuntimeError: empty text); library.add_finding pre-encodes before validate.
- **P1.2** _parse_bool(1) → ValueError.
- **P1.3** Empty / non-PID lock files → TimeoutError (no reclaim).
- **P1.5** Second INSERT OR REPLACE into FTS5 → 2 rows (latent; normal insert path still PK-protected).
- **P2.1** embedder.encode(all_texts, batch_size=32) but SentenceTransformerEmbedder.encode only accepts 	exts → TypeError on rebuild.
- **P2.2** _check_duplicate_warning returns ts_rank; caller reads similarity_rank → KeyError.
- **P2.3–P2.5** Packing trim-after-interleave, cache last-writer-wins under lock, exception delete_finding on same id — code matches.
- **P3.1–P3.4** Lexical SELECT omits text columns; no status filter on retrieval; decomp hard-caps max_findings=5; options.max_context_tokens unused in pack.
- **P3.5** Expansion case-fold bug **duplicates** original (not drops it) — still a real low-severity bug.
- **P4–P8** Consolidation no-merge, keep_id ignored, content_hash marker, tool_selection None→0, dead status_filter, Aider JSON-into-yml, session_warning dead param, TUI settings path, deferred tool registration, session IntegrityError, retrogit hardcoded settings, dead settings.memory, wrong observation counts, progressive window no-op, agent_id ./: rejected, 	o_agent=any blocked, RulesEngine unused, terminate→completed, poll offset with filters, export error vs issues, template data_root CWD, template path traversal, no MCP auto-compact, session_context active-only, multi-session per ephemeral agent_id.
- **P9.2–P9.5** No membership checks on mutations; _complete_open_session_tasks completes all open tasks; export drops issues; URL citations accepted without fetch.
- **P10** TTY seed 
esolve(installerDir,'..','..') with installerDir=.../src lands on package parent / 
ode_modules (not package root with bundled openlmlib/); lockfile gitignored vs 
pm ci; python discovery skips python; README pytest vs unittest CI.

### Installer seed path note

For the **published** npm layout (
ode_modules/openlmlib/src/postinstall.mjs), installerDir=__dirname is .../openlmlib/src, so path.resolve(installerDir,'..','..') is 
ode_modules — finding **P10.1 stands**. Non-interactive path uses package root correctly.

### What was *not* demoted

No other Confirmed finding was found to be a clean false positive against current code. Several are **edge / latent / platform-specific** (already labeled that way in the original doc) and should stay for maintainers.

### Recommended priority (unchanged except 9.1)

1. **High:** P2.1 rebuild TypeError, P2.2 similarity_rank KeyError, P5.1 Aider yml, P6.1 session IntegrityError, P6.2 retrogit DB split, P7.1 agent_id regex, P7.2 	o_agent=any, P10.1 interactive install seed, P10.2 lockfile/CI 
pm ci, P9.2 authz, P8.2–P8.3 templates.
2. **Medium:** write-gate empty evidence, retrieval text/status gaps, export issue mapping, terminate status vocabulary, poll offset filters, memory dead settings / wrong counts.
3. **Low / latent:** FTS upsert wording, PermissionError PID, URL citation policy, docs/pytest mismatch, expansion duplicate variants.

---

## Fix progress tracker

Update **Fix status** as work lands: `Open` → `In progress` → `Fixed` / `Won't fix` / `Deferred`.  
**Verified** = re-checked after the fix (Y/N).

| ID | Part | Finding | Severity | Fix status | Verified | Notes |
|----|------|---------|----------|------------|----------|-------|
| P1.1 | 1 Foundation | Empty evidence crashes add path before structured rejection | Medium | Fixed | Y | short-circuit hard errors before encode; no pre-encode empty evidence |
| P1.2 | 1 Foundation | Settings booleans reject JSON integers `0`/`1` | Medium | Fixed | Y | `_parse_bool` accepts int 0/1 |
| P1.3 | 1 Foundation | Interprocess lock never recovers empty / non-PID lock files | Medium | Fixed | Y | reclaim empty/invalid PID after 2s grace |
| P1.4 | 1 Foundation | `_pid_is_alive` treats `PermissionError` as dead | Low | Fixed | Y | PermissionError → alive; ProcessLookupError → dead |
| P1.5 | 1 Foundation | FTS `INSERT OR REPLACE` does not upsert by `id` | Low | Fixed | Y | DELETE then INSERT into findings_fts |
| P2.1 | 2 Storage | `rebuild_vector_index` `batch_size` → TypeError | High | Fixed | Y | encode() accepts batch_size, forwards to model |
| P2.2 | 2 Storage | Duplicate guard `KeyError: similarity_rank` | High | Fixed | Y | warning dict includes similarity_rank (+ fts_rank) |
| P2.3 | 2 Storage | Packing trims after interleave (drops higher scores) | Medium | Fixed | Y | trim by score first, then interleave |
| P2.4 | 2 Storage | Embedding cache multi-process save last-writer-wins | Medium | Fixed | Y | merge disk under lock before write |
| P2.5 | 2 Storage | `add_finding` except can delete pre-existing same id | Medium | Fixed | Y | reject existing id; only delete if this call inserted |
| P3.1 | 3 Retrieval | Lexical hits drop tags/evidence/reasoning/caveats | High | Fixed | Y | SELECT + parse text columns in FTS search |
| P3.2 | 3 Retrieval | Archived / non-active findings still in retrieval | High | Fixed | Y | default status=active in FTS + _passes_filters |
| P3.3 | 3 Retrieval | Decomposition hard-caps at 5, ignores `final_k` | Medium | Fixed | Y | pass max_findings from final_k / candidate count |
| P3.4 | 3 Retrieval | `max_context_tokens` API flag ignored | Medium | Fixed | Y | packer uses options.max_context_tokens |
| P3.5 | 3 Retrieval | Query expansion duplicates original (case-fold) | Low | Fixed | Y | case-fold include_original against seen |
| P4.1 | 4 Runtime/CLI | Consolidation only archives; no evidence/tags merge | High | Fixed | Y | union tags/evidence/caveats into survivor |
| P4.2 | 4 Runtime/CLI | `consolidate_group(keep_id=...)` ignored | Medium | Fixed | Y | honor keep_id when present in group |
| P4.3 | 4 Runtime/CLI | Consolidation overwrites `content_hash` with marker | Medium | Fixed | Y | leave content_hash; log pointer in failure_log |
| P4.4 | 4 Runtime/CLI | `log_tool_selection` stores unknown as incorrect (`0`) | Medium | Fixed | Y | store NULL; accuracy uses labeled rows only |
| P4.5 | 4 Runtime/CLI | `find_stale_findings(status_filter=...)` dead | Low | Fixed | Y | status_filter replaces default active filter |
| P5.1 | 5 MCP | Aider install writes JSON into `.yml` | High | Fixed | Y | YAML dump for aider / .yml paths |
| P5.2 | 5 MCP | `save_finding` session warning never returned | Medium | Fixed | Y | attach session_warning on MCP response |
| P5.3 | 5 MCP | Interactive setup ignores `settings_path` | Medium | Fixed | Y | pass OPENLMLIB_SETTINGS to Node wizard |
| P5.4 | 5 MCP | Memory/collab tools absent until `main()` | Low | Fixed | Y | ensure_tools_registered + list_tools hook |
| P6.1 | 6 Memory | Session restart/reuse → `IntegrityError` | High | Fixed | Y | create_session upserts/resumes; clears ended_at |
| P6.2 | 6 Memory | `retroactive_ingest` writes to different DB | High | Fixed | Y | accept storage/settings_path; MCP passes shared storage |
| P6.3 | 6 Memory | `MemoryInjectionSettings` entirely dead config | Medium | Fixed | Y | all knobs: auto_log, cleanup, progressive, max tokens, compression |
| P6.4 | 6 Memory | Wrong observation counts on session_start/inject | Medium | Fixed | Y | as_dict context returns real observation_count |
| P6.5 | 6 Memory | Progressive `window` no-op; expansion threshold rare | Low | Fixed | Y | implement window neighbors; lower core confidence gate |
| P7.1 | 7 Collab core | Generated agent IDs rejected (`.` / `:` in model) | High | Fixed | Y | sanitize model segment to [a-zA-Z0-9_-] |
| P7.2 | 7 Collab core | `to_agent="any"` blocked by MCP validation | High | Fixed | Y | skip agent-id regex for any/empty/None |
| P7.3 | 7 Collab core | `RulesEngine` never applied on live paths | Medium | Fixed | Y | MessageBus.send + join/plan; any=valid assignment |
| P7.4 | 7 Collab core | Terminate writes `completed`, not `terminated` | Medium | Fixed | Y | write status terminated |
| P7.5 | 7 Collab core | `poll_messages` advances offset under filters | Medium | Fixed | Y | match read_messages offset policy |
| P8.1 | 8 Collab adv | Export maps rejections as `"Unknown error"` | High | Open | N | |
| P8.2 | 8 Collab adv | Custom templates resolve `data_root` vs CWD | High | Open | N | |
| P8.3 | 8 Collab adv | `create_template` path-escaping `template_id` | Medium | Open | N | |
| P8.4 | 8 Collab adv | Auto-compaction never runs on MCP path | Medium | Open | N | |
| P8.5 | 8 Collab adv | `session_context` refuses non-active sessions | Medium | Open | N | |
| P8.6 | 8 Collab adv | Multi-session history per ephemeral agent_id | Low | Open | N | |
| P9.1 | 9 Co-scientist | Run state full-blob replace / dual-session CAS UX | Medium | Open | N | reclassified from High |
| P9.2 | 9 Co-scientist | Mutations lack agent membership / role checks | High | Open | N | |
| P9.3 | 9 Co-scientist | Start verification completes all gen tasks | Medium | Open | N | |
| P9.4 | 9 Co-scientist | Supported-finding export drops write-gate detail | Medium | Open | N | |
| P9.5 | 9 Co-scientist | URL citations valid with no reachability check | Low | Open | N | quality gap |
| P10.1 | 10 Installer | TTY npm install never finds bundled Python source | High | Open | N | |
| P10.2 | 10 Installer | CI `npm ci` fails (lockfile gitignored) | High | Open | N | |
| P10.3 | 10 Installer | Python discovery never tries `python` | Medium | Open | N | |
| P10.4 | 10 Installer | Test docs/dev extras disagree with CI (pytest vs unittest) | Low | Open | N | |

### Tracker summary

| Severity | Total | Open | In progress | Fixed | Won't fix / Deferred |
|----------|------:|-----:|------------:|------:|---------------------:|
| High | 15 | 5 | 0 | 10 | 0 |
| Medium | 24 | 6 | 0 | 18 | 0 |
| Low | 10 | 4 | 0 | 6 | 0 |
| **All** | **49** | **15** | **0** | **34** | **0** |
