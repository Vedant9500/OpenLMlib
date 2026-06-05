# OpenLMlib Multi-Pass Code Audit

Date: 2026-06-05

Scope: static and targeted dynamic review of the Python package, core retrieval/storage path, CollabSessions, memory subsystem, MCP/CLI/package surfaces, tests, and installer metadata.

Method:
- Pass 1 maps the codebase and records initial findings.
- Pass 2 validates each high-impact finding against source/tests, widens the scan, and marks findings as confirmed, revised, or dropped.
- Findings include trade-offs where a fix adds I/O, latency, schema complexity, or operational constraints.

## Pass 1 Summary

### Efficiency Audit

The core knowledge-base design, SQLite metadata plus JSON full-text payloads plus a local vector index, is a sensible low-latency architecture for a local developer tool. The highest-risk performance/correctness issue is not the storage model itself, but the runtime batching layer: writes can remain only in memory while SQLite/JSON are already committed.

CollabSessions and memory use straightforward SQLite schemas and avoid unnecessary external services. That is optimal for the current scale, but several authorization and boundary checks are missing, which creates cross-agent, cross-session, or cross-user data leakage.

Pass 2 added one critical release blocker in the MCP tool surface: the MCP `init_library` tool is currently broken by name shadowing.

### The Paradigm Shift

Do not add more agentic coordination, search services, or database tiers yet. The useful shift is to make persistence and authorization explicit: writes must have a durable boundary, and every read/write operation must carry the actor scope needed to enforce visibility.

### The Elegant Solution & Trade-offs

Prefer small, deterministic fixes:
- Force-flush or transactionally persist vector/cache changes for successful writes. Trade-off: more I/O per write, but avoids silent retrieval loss.
- Add actor/user/session predicates to collaboration and memory read paths. Trade-off: slightly more query plumbing and tests, but prevents data leakage without a new access-control layer.
- Keep SQLite/FTS for local scale; add FTS5 to memory only if observation volume proves `%LIKE%` scans are a real bottleneck.

## Pass 1 Findings

### High Severity

1. **Successful `add_finding` can lose the vector/cache update before process exit.**
   - Refs: `openlmlib/library.py:505`, `openlmlib/library.py:508`, `openlmlib/library.py:509`, `openlmlib/runtime.py:162`, `openlmlib/runtime.py:169`, `openlmlib/runtime.py:127`.
   - Evidence: `add_finding` commits SQLite and writes JSON, then marks vector/cache dirty and calls `maybe_flush(runtime)` without `force=True`. Default flush policy returns false until 5 writes or 30 seconds. `shutdown_runtime` closes the DB connection without forcing a dirty flush.
   - Impact: a short-lived CLI invocation can return `status=ok` but leave the persisted vector index stale, so semantic retrieval misses the new finding after restart.
   - Suggested fix: force a flush after successful writes in process-per-command paths, or make `shutdown_runtime`/`atexit` call `maybe_flush(force=True)` before closing. The safest default is durable-on-success for user-facing write tools.
   - Trade-off: extra index/cache write I/O per add; correctness is worth it for a local knowledge base.

2. **FAISS vector saves can lose concurrent process updates.**
   - Refs: `openlmlib/vector_store.py:250`, `openlmlib/vector_store.py:254`, `openlmlib/vector_store.py:268`.
   - Evidence: `save_vector_store(..., merge_existing=True)` only merges existing data for `numpy` stores. With FAISS, two processes can load the same old index, each add a vector, then the later save overwrites the earlier one even though the save itself is locked.
   - Impact: default FAISS-backed installs can silently drop vectors under concurrent writers.
   - Suggested fix: either serialize load-add-save under an interprocess write lock, or represent pending FAISS additions/deletions as deltas and merge them after reloading the current index under the lock.
   - Trade-off: broader lock scope increases write latency but prevents lost updates.

3. **Collab targeted messages are not private on read paths.**
   - Refs: `openlmlib/collab/collab_mcp.py:567`, `openlmlib/collab/db.py:539`, `openlmlib/collab/collab_mcp.py:742`.
   - Evidence: `send_message` can persist `to_agent`, but polling and session message reads return messages by session/seq without a reader visibility predicate.
   - Impact: a session member can read messages targeted to another agent.
   - Suggested fix: all message read/tail/range/grep/context queries should apply `(to_agent IS NULL OR to_agent = reader OR from_agent = reader)` when private targeting is intended.
   - Trade-off: read APIs need an explicit reader identity; unauthenticated historical browsing should be a separate policy.

4. **Collab agents marked `left` remain authorized for active operations.**
   - Refs: `openlmlib/collab/session.py:279`, `openlmlib/collab/security.py:141`, `openlmlib/collab/security.py:151`, `openlmlib/collab/collab_mcp.py:621`, `openlmlib/collab/collab_mcp.py:1162`.
   - Evidence: `leave_collab_session` updates agent status to `left`; `verify_agent_in_session` only verifies the row exists and session matches, then returns status without enforcing `active`.
   - Impact: departed agents can continue reading, writing, or saving artifacts.
   - Suggested fix: require `status == "active"` for mutating and live-read tools; add a separate historical-read function if completed/left access is desired.
   - Trade-off: more explicit lifecycle states, but less surprising authorization.

5. **`export_to_library` can export any collab session by ID without membership authorization.**
   - Refs: `openlmlib/collab/collab_mcp.py:1413`, `openlmlib/collab/collab_mcp.py:1445`, `openlmlib/collab/export_bridge.py:47`, `openlmlib/collab/export_bridge.py:63`.
   - Evidence: the tool accepts no acting agent and directly reads session artifacts/content before saving findings.
   - Impact: any caller with a session ID can exfiltrate/export another session's artifacts into the main library.
   - Suggested fix: require an `agent_id` or `orchestrator_id`, verify active/completed membership and role, and optionally require the session to be completed before export.
   - Trade-off: one more required parameter, but the tool becomes auditable.

6. **Memory retrieval can leak observations across users and sessions.**
   - Refs: `openlmlib/memory/storage.py:45`, `openlmlib/memory/storage.py:662`, `openlmlib/memory/memory_retriever.py:212`, `openlmlib/memory/memory_retriever.py:232`, `openlmlib/memory/context_builder.py:128`.
   - Evidence: sessions store `user_id`, but retrieval filters only by tool/type/session. `auto_inject_context(session_id=...)` ignores both the current session and user scope when retrieving context.
   - Impact: a new session can receive another user's memories or its own current-session observations.
   - Suggested fix: pass `user_id` and current `session_id` through retriever APIs, join `memory_sessions`, and default to same-user plus previous-session predicates.
   - Trade-off: slightly more query plumbing; no new storage system required.

7. **Memory privacy filtering is not enforced at the storage boundary.**
   - Refs: `openlmlib/memory/session_manager.py:205`, `openlmlib/memory/storage.py:223`, `openlmlib/memory/storage.py:228`, `openlmlib/memory/retrogit_ingest.py:317`, `openlmlib/memory/retrogit_ingest.py:338`.
   - Evidence: `SessionManager` sanitizes before storage, but `MemoryStorage.add_observation()` persists raw `tool_input`/`tool_output`. Retroactive ingest bypasses `SessionManager` and writes commit messages/file metadata directly.
   - Impact: secrets can be persisted if any caller uses storage directly or via ingest.
   - Suggested fix: sanitize at `MemoryStorage` for observations, summaries, and knowledge; keep caller-side sanitization as defense in depth.
   - Trade-off: storage becomes opinionated about privacy policy, which is appropriate for the data boundary.

8. **Observation queue shutdown can drop queued observations and leave queue accounting unfinished.**
   - Refs: `openlmlib/memory/observation_queue.py:69`, `openlmlib/memory/observation_queue.py:73`, `openlmlib/memory/observation_queue.py:124`, `openlmlib/memory/observation_queue.py:133`, `openlmlib/memory/observation_queue.py:156`.
   - Evidence: `stop()` sets `running=False` before enqueuing the sentinel; the worker loop condition is `while self.running`, so pending observations can be abandoned. The sentinel branch breaks before `queue.task_done()`.
   - Impact: best-effort memory logging can silently lose observations, and any future `join()` use can hang.
   - Suggested fix: loop until a sentinel is consumed, call `task_done()` in `finally`, and either drain queued observations or document intentional drop semantics.
   - Trade-off: shutdown may wait longer when the queue is large.

### Medium Severity

9. **`terminate_collab_session` leaves final agent status update uncommitted.**
   - Refs: `openlmlib/collab/session.py:320`, `openlmlib/collab/session.py:342`, `openlmlib/collab/collab_mcp.py:145`.
   - Evidence: session status and message send use helpers that commit, but the final `UPDATE agents` executes outside `with conn:` on a thread-local connection.
   - Impact: active agents may remain active after session completion depending on connection lifetime.
   - Suggested fix: wrap the update in `with conn:` or move it into a committing DB helper.

10. **Collab `max_agents` enforcement is race-prone and counts departed agents.**
    - Refs: `openlmlib/collab/session.py:196`, `openlmlib/collab/session.py:198`, `openlmlib/collab/db.py:398`.
    - Evidence: join checks `len(get_session_agents(...))` before insert; `get_session_agents` returns all statuses while leave only marks rows `left`.
    - Impact: left agents can consume capacity forever, and concurrent joins can exceed `max_agents`.
    - Suggested fix: count active agents only and perform count-plus-insert under `BEGIN IMMEDIATE` or a conditional insert transaction.

11. **Retroactive memory ingest crashes with `include_uncommitted=False`.**
    - Refs: `openlmlib/memory/retrogit_ingest.py:270`, `openlmlib/memory/retrogit_ingest.py:329`.
    - Evidence: `modified_files` is assigned only inside the `include_uncommitted` branch, then referenced while processing commits.
    - Impact: committed-history-only ingestion fails before saving observations.
    - Suggested fix: initialize `modified_files = []` before the branch.

12. **Retroactive ingest builds compressed summaries that are never persisted.**
    - Refs: `openlmlib/memory/retrogit_ingest.py:311`, `openlmlib/memory/retrogit_ingest.py:343`, `openlmlib/memory/storage.py:230`.
    - Evidence: observations include `compressed_summary`, but `add_observation()` inserts only id/session/timestamp/tool fields/tags.
    - Impact: layer-2 memory timelines are empty until another compression path runs.
    - Suggested fix: persist optional `compressed_summary`, `facts`, `concepts`, and `obs_type`, or call `update_observation_compression()` after insert.

13. **Session summaries ignore observations beyond the newest 100.**
    - Refs: `openlmlib/memory/session_manager.py:341`, `openlmlib/memory/session_manager.py:349`.
    - Evidence: `on_session_end()` fetches `limit=100` for compression and summary generation.
    - Impact: older work in long sessions is excluded from summaries and extracted knowledge.
    - Suggested fix: paginate all observations or use the configured session cap.

14. **Core retrieval serializes all semantic and lexical reads under the write lock.**
    - Refs: `openlmlib/library.py:594`, `openlmlib/library.py:611`, `openlmlib/library.py:621`.
    - Evidence: embedding, vector search, and FTS search all run inside `runtime.write_lock`; only usage logging and dirty flush mutate after search.
    - Impact: concurrent read traffic becomes single-file, and long embedding/rerank calls block writes.
    - Suggested fix: introduce a read/write lock or snapshot read path, keeping mutations and vector save operations exclusively locked.
    - Trade-off: more synchronization complexity; current lock is safe but pessimistic.

15. **Enhanced retrieval reports misleading `combined_candidates`.**
    - Refs: `openlmlib/retrieval.py:135`, `openlmlib/retrieval.py:149`, `openlmlib/retrieval.py:163`, `openlmlib/retrieval.py:193`.
    - Evidence: `combined_candidates` is emitted after reranking/decomposition/deduplication may have reduced `candidates`.
    - Impact: benchmark/tuning output can undercount the original merged candidate pool.
    - Suggested fix: store `combined_candidate_count = len(candidates)` immediately after merge/expansion, then report post-phase counts separately.

16. **Pickle-backed local cache/index files are unsafe if a configured data path is attacker-controlled.**
    - Refs: `openlmlib/embeddings.py:29`, `openlmlib/vector_store.py:183`, `openlmlib/settings.py:96`.
    - Evidence: embedding cache and numpy vector store use `pickle.load()` from configurable filesystem paths.
    - Impact: loading a malicious cache/index can execute code.
    - Suggested fix: use `.npz`/SQLite/blob storage for vectors and a JSON/SQLite cache, or explicitly refuse to load files not owned by the current user where supported.
    - Trade-off: migration work and slower simple serialization; safer data interchange.

17. **Memory substring search full-scans at scale.**
    - Refs: `openlmlib/memory/storage.py:673`, `openlmlib/memory/storage.py:687`.
    - Evidence: `%query%` over large text fields cannot use the existing B-tree indexes.
    - Impact: memory retrieval degrades as observations grow.
    - Suggested fix: keep current LIKE path for small local stores; add an FTS5 table/triggers only when observation volume justifies the extra write complexity.

### Low Severity / Code Smell

18. **Read-before-write duplicate detection uses raw FTS rank as a similarity threshold.**
    - Refs: `openlmlib/library.py:309`, `openlmlib/library.py:320`, `openlmlib/library.py:322`, `openlmlib/mcp_server.py:887`, `openlmlib/mcp_server.py:1429`.
    - Evidence: any FTS match with `rank <= 2.0` is treated as very similar; FTS5 ranks are commonly negative/small and not a normalized similarity score.
    - Impact: duplicate suggestions can be poorly calibrated.
    - Suggested fix: use token overlap/embedding similarity for the gate, or calibrate rank against a fixture dataset and document the threshold.

19. **Boolean settings parsing treats string values like `"false"` as true.**
    - Refs: `openlmlib/settings.py:126`, `openlmlib/settings.py:130`, `openlmlib/settings.py:141`.
    - Evidence: `bool("false")` evaluates to `True`.
    - Impact: hand-edited JSON settings can silently enable features users intended to disable.
    - Suggested fix: add a strict bool parser accepting only booleans and known string literals.

## Pass 1 Test/Verification Notes

- Verified finding 1 with a mocked runtime under `.bench_tmp`: `add_finding` returned `ok`, left `dirty_vector=True`, `dirty_cache=True`, `writes_since_flush=1`, and did not create vector meta/index files.
- Confirmed `__pycache__` files are visible in the working tree but not tracked by `git ls-files`, so they are not included as a repo hygiene finding.
- Remaining high-severity collab and memory findings came from focused sidecar audits and have line-level source references; Pass 2 will re-check the highest-risk ones and run targeted tests where feasible.

## Pass 2 Validation Log

### Added Findings From Wider Pass

20. **Critical: MCP `init_library` tool is broken by name shadowing.**
    - Refs: `openlmlib/mcp_server.py:10`, `openlmlib/mcp_server.py:16`, `openlmlib/mcp_server.py:805`, `openlmlib/mcp_server.py:821`.
    - Evidence: the imported library function is named `init_library`, then the MCP tool defines `def init_library()`. The tool body calls `init_library(_settings_path())`, which resolves to the zero-argument tool function, not the library function.
    - Dynamic confirmation: `.\.venv\Scripts\python.exe -c "import openlmlib.mcp_server as m; m.init_library()"` raises `TypeError: init_library() takes 0 positional arguments but 1 was given`.
    - Impact: first-run MCP initialization fails.
    - Suggested fix: alias the import as `init_library as lib_init_library` and call `lib_init_library(_settings_path())`; add a direct MCP tool regression test.

21. **High: installer lockfile is stale and self-referential.**
    - Refs: `installer/package.json:3`, `installer/package-lock.json:3`, `installer/package-lock.json:20`.
    - Evidence: package manifest version is `0.2.7`, but the lockfile is `0.2.5` and includes `openlmlib: file:openlmlib-0.2.5.tgz`; only `openlmlib-0.2.6.tgz` and `openlmlib-0.2.7.tgz` exist locally.
    - Impact: `npm ci` from `installer/` is not reproducible and can resolve the package against a stale self-dependency.
    - Suggested fix: regenerate `installer/package-lock.json` from current `installer/package.json`, remove stale tarball/self-dependency state, and run `npm ci` in CI.

22. **High: npm postinstall can install Python code that does not match the npm tarball.**
    - Refs: `installer/src/postinstall.mjs:211`, `installer/src/postinstall.mjs:219`, `installer/src/postinstall.mjs:221`, `installer/src/postinstall.mjs:224`.
    - Evidence: after bundled/local source candidates, postinstall falls back to GitHub tag, GitHub main, PyPI exact version, then PyPI latest.
    - Impact: a published npm package can install a different Python implementation than the tarball being installed, which makes releases non-reproducible and weakens supply-chain review.
    - Suggested fix: for published npm packages, fail if bundled source is missing or invalid; allow network fallback only behind an explicit development escape hatch.

23. **High: npm wrapper drops all `openlmlib setup` arguments.**
    - Refs: `installer/bin/openlmlib.js:42`, `installer/bin/openlmlib.js:47`, `openlmlib/cli.py:898`, `openlmlib/cli.py:899`.
    - Evidence: the wrapper intercepts `setup`/`wizard` and runs `src/run-setup.mjs` without forwarding `process.argv.slice(3)`. Python setup supports `--skip-model-warmup`, `--skip-mcp-config`, and `--ide`.
    - Impact: npm users cannot pass documented setup flags.
    - Suggested fix: forward args to `run-setup.mjs` and into Python/TUI, or stop intercepting `setup`.

24. **Medium: Python `cmd_setup` ignores explicit flags in interactive terminals.**
    - Refs: `openlmlib/cli.py:169`, `openlmlib/cli.py:177`, `openlmlib/cli.py:183`, `openlmlib/cli.py:203`.
    - Evidence: interactive terminals immediately launch TUI before the noninteractive path that honors `--skip-model-warmup`, `--skip-mcp-config`, and `--ide`.
    - Impact: even direct Python CLI users can lose setup options when running in an interactive shell.
    - Suggested fix: bypass TUI when explicit flags are supplied, or pass parsed options into the TUI setup path.

25. **Medium: Python 3.10 support is missing the TOML reader dependency.**
    - Refs: `pyproject.toml:10`, `pyproject.toml:26`, `openlmlib/mcp_setup.py:269`, `openlmlib/mcp_setup.py:274`.
    - Evidence: package metadata supports Python 3.10; TOML MCP config loading imports stdlib `tomllib`, then falls back to `tomli`, but `tomli` is not declared in dependencies.
    - Impact: existing TOML MCP configs fail on Python 3.10.
    - Suggested fix: add `tomli>=...; python_version<'3.11'` or drop Python 3.10 support.

26. **Medium: installer postinstall builds shell command strings from paths/specs.**
    - Refs: `installer/src/postinstall.mjs:160`, `installer/src/postinstall.mjs:178`, `installer/src/postinstall.mjs:231`, `installer/src/postinstall.mjs:233`, `installer/src/postinstall.mjs:319`, `installer/src/postinstall.mjs:353`.
    - Evidence: `execSync()` receives interpolated command strings containing Python paths, venv paths, and package specs.
    - Impact: paths containing quotes can break installation; user-controlled paths such as `OPENLMLIB_HOME` increase injection risk.
    - Suggested fix: use `execFileSync`/`spawn` with argument arrays and JSON-encode values written into temporary Python scripts.

27. **Medium: CI does not cover the declared Python/version and installer surface.**
    - Refs: `.github/workflows/ci.yml:21`, `.github/workflows/ci.yml:22`, `.github/workflows/ci.yml:36`, `.github/workflows/ci.yml:60`.
    - Evidence: CI tests only Python 3.12 across OSes, manually installs unbounded runtime deps, and the package-smoke job installs the wheel with `--no-deps` before manually installing unbounded deps.
    - Impact: declared 3.10, 3.11, 3.13 support and bounded dependency metadata are not validated.
    - Suggested fix: matrix 3.10-3.13 and install `.[dev]` or bounded requirements; add an npm installer smoke job.

28. **Medium: installer smoke test does not install or run the package.**
    - Refs: `package.json:7`, `installer/test-install.js:23`, `installer/test-install.js:42`.
    - Evidence: `npm run test:installer` only inspects an existing tarball and prints instructions for manual install.
    - Impact: postinstall, npm bin wiring, and setup argument behavior can regress without CI failure.
    - Suggested fix: create a temp install smoke test with isolated `OPENLMLIB_HOME`, run `npm pack`, install the tarball, execute the bin, and verify Python package import/tool list.

29. **Low: setup help text references stale MCP commands.**
    - Refs: `scripts/check_mcp_config.py:56`, `scripts/check_mcp_config.py:57`, `installer/src/ui/setup-wizard.js:440`, `installer/src/ui/setup-wizard.js:442`, `openlmlib/cli.py:880`.
    - Evidence: helper text suggests `openlmlib mcp-config --client` and `openlmlib mcp`, while the CLI exposes `mcp-config --ide`.
    - Impact: users follow commands that do not exist.
    - Suggested fix: update text to `openlmlib mcp-config --ide <client>` or remove stale shortcuts.

### Confirmation Results

- Confirmed finding 1 dynamically with a mocked runtime: a successful add left `dirty_vector=True`, `dirty_cache=True`, `writes_since_flush=1`, and no vector meta/index files.
- Confirmed finding 3 dynamically at the collab DB layer: a `to_agent='agent-b'` message is returned by `get_messages_since(session_id, last_seq)` with no recipient predicate.
- Confirmed finding 4 dynamically: `verify_agent_in_session()` returns `status='left'` without rejecting the agent.
- Confirmed findings 6 and 7 dynamically: `auto_inject_context(session_id='bob')` returned an observation from Alice's session, and direct `MemoryStorage.add_observation()` persisted raw `password=` and `API_KEY=` strings.
- Confirmed finding 8 dynamically: after enqueuing five observations and calling `stop()` quickly, only one processed and five queue items remained, including the sentinel.
- Confirmed finding 20 dynamically with the project venv; MCP `init_library` raises the expected `TypeError`.
- Static re-check confirmed findings 2, 5, 9-19, and 21-29 against source. No first-pass finding was dropped.

### Verification Commands

- `.\.venv\Scripts\python.exe -m compileall openlmlib -q` passed.
- Focused `unittest` run passed after monkeypatching `tempfile.TemporaryDirectory` to use workspace-local directories: 95 tests, 0 failures, 0 errors.
- A direct `pytest` run was not possible because the project venv does not have `pytest` installed.
- An unpatched `unittest` run fails in this managed sandbox because Python's standard Windows temp cleanup cannot access its own temporary directories under the sandbox. This is an environment artifact, not a project test failure.

### Coverage Gaps Exposed By Pass 2

- No direct test covers MCP `init_library`.
- No test covers durable vector/cache flush after a successful write in a short-lived process.
- Current vector-store concurrency tests cover numpy merge behavior only, not FAISS lost-update behavior.
- Existing collab tests check membership, but not targeted-message visibility, left-agent authorization, export authorization, or terminate-session commit semantics.
- Existing memory tests check privacy helpers and `SessionManager`, but not storage-level sanitization bypass, user/session isolation, observation queue shutdown, `include_uncommitted=False`, or >100-observation summaries.
- Installer tests do not exercise `npm install`, postinstall fallback behavior, or npm bin argument forwarding.

## Fix Pass Resolution

Date: 2026-06-05

Fixed or materially addressed:
- Critical/high runtime correctness: MCP `init_library` name shadowing, durable vector/cache flush on successful writes and shutdown, and FAISS delta merge on save.
- Collab authorization: targeted message visibility, inactive/left agent rejection for live access, orchestrator-only `export_to_library`, committed terminate-session agent updates, and active-agent capacity counting with an immediate join transaction.
- Memory safety: same-user/previous-session context filtering, storage-boundary privacy sanitization, optional compressed-summary/facts/concepts persistence, full-session summary input, queue drain/shutdown accounting, and retro-git `include_uncommitted=False`.
- Setup/MCP visibility: Codex TOML key quoting/preservation, setup flag handling, npm wrapper argument handling, stale setup text, and docs explaining per-client MCP registration.
- Installer/release: postinstall package fallback is now opt-in, shell-built Python install/config calls were moved to argument arrays, installer smoke test now performs a real temp install, and CI covers Python 3.10-3.13 plus npm installer smoke.
- Lower-risk correctness: strict boolean parsing, enhanced retrieval candidate metrics, duplicate warnings use claim overlap instead of raw FTS rank, embedding cache uses JSON, and numpy vector store uses non-pickle `.npz` payloads.

Remaining follow-ups:
- Finding 14, retrieval read concurrency, is still intentionally conservative; replacing the single lock with a read/write or snapshot strategy needs a focused concurrency design/test pass.
- Finding 17, memory FTS5, remains a scale optimization; current LIKE search is acceptable for small local stores, but FTS5 should be added once observation volume justifies trigger/schema migration complexity.
