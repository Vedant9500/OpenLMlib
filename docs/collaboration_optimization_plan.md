# Multi-Agent Collaboration Optimization Plan v2

**Date:** April 18, 2026 (v2 — revised from April 14 original)  
**Source:** Analysis of OpenLMlib sessions + 6 framework comparisons + context optimization research + cross-model handoff analysis  
**Status:** Research-validated, corrections applied from independent codebase audit

**Research Scope:** 
- Frameworks analyzed: AutoGen, CrewAI, LangGraph, ChatDev, MetaGPT, OpenHands
- Context optimization: MemGPT/Letta, H-MEM, Google ADK, LangChain, vLLM
- Cross-model handoff: Google ADK scoped handoffs, Universal-Adopter LoRA, HACPO, PantheonOS
- Academic papers: Multi-agent memory survey, distributed context management
- Validation: Independent codebase audit of `openlmlib/collab/` 

**Key Changes from v1:**
- Added Phase 0 (worker instruction rewrite — highest ROI, zero code changes)
- Added Problem 4: Cross-Model Handoff Quality (entirely new section)
- Corrected benchmark numbers to use verified ranges with "up to" qualifiers
- Noted existing infrastructure that already supports Solutions 1A and 2B
- Removed unverified DisCEdge citation (arXiv:2511.22599)
- Added connection lifecycle and notification latency as optimization targets

---

## Executive Summary

OpenLMlib's collaboration sessions suffer from four critical inefficiencies validated against industry benchmarks:

1. **Sequential bottlenecks** cause 1-2 min idle time per worker (industry parallel speedup: up to 3-5x)
2. **Context rot** consumes 30-50% of smaller model windows on chatter (industry achieves up to 60-80% reduction)
3. **Message inefficiency** wastes 75-80% of messages on overhead (industry achieves 1-2 msgs per task)
4. **Cross-model handoff degradation** causes context corruption, format mismatches, and reasoning style conflicts when heterogeneous models collaborate

Solutions validated by production frameworks can reduce overhead by 60-80% and improve agent utilization up to 3x.

---

## Problem 1: Sequential Bottleneck

### Current Pattern & Impact
```
Orchestrator creates session → Sends Task 1 → Waits → Reviews → Sends Task 2
Worker B idle during Task A execution (90+ sec observed)
```

**Observed Impact:**
- 1-2 min idle time per worker
- 225+ tokens wasted on poll cycles in 90 seconds
- Only one agent productive at any time (20-30% utilization)

**Root Cause (Codebase):**
- `context_compiler.py` L277-302: Worker instructions explicitly say "wait for the orchestrator to assign you work"
- `collab_mcp.py` L684-800: `poll_messages` blocks for up to 30s per call
- `notification.py` L130-181: File-based polling at 300ms intervals adds minimum 150ms latency

### Industry Solutions

| Framework | Pattern | Speedup | Approach |
|-----------|---------|---------|----------|
| **CrewAI** | Parallel mode | Up to 3x | Independent tasks execute simultaneously |
| **LangGraph** | Fork/join subgraphs | Up to 5x+ | Data-parallel with async worker pools |
| **AutoGen** | Dynamic speaker selection | Up to 2-3x | LLM-driven delegation, async processing |
| **OpenHands** | Sub-agent spawning | Up to 2x | Hierarchical coordination, blocking parallel |
| **MetaGPT** | DAG pipeline | 1x | Sequential only |
| **ChatDev** | Chat chains | 1x | Sequential only |

**Key Insight:** Parallel execution achieves up to 3-5x speedup in production frameworks. Actual gains depend on task independence and I/O-boundedness.

### Solution 1A: Parallel Task Assignment (Immediate — Already Supported)

> **Note:** The infrastructure already exists. `create_collab_session()` in `session.py` L116-156 
> accepts a `plan` parameter and batch-inserts all tasks. `compile_context()` in 
> `context_compiler.py` L62-65 already presents `my_tasks` to agents on join. The gap is 
> **behavioral** — worker instructions tell agents to wait instead of checking pre-assigned tasks.

```python
create_session(
    plan=[
        {"step": 1, "task": "[FULL DETAILS]", "assigned_to": "agent_qwen"},
        {"step": 2, "task": "[FULL DETAILS]", "assigned_to": "agent_gemini"},
    ]
)
```

Workers see plan on join → Start immediately → No waiting.

**Fix Required:** Rewrite worker instructions (see Phase 0 below).

**Expected:** 50-70% time reduction (based on CrewAI/LangGraph patterns)

### Solution 1B: Task Queue with Auto-Assignment (Framework Enhancement)

```
Session created → Tasks pre-loaded in queue
Workers join → Auto-claim next task → Work immediately
```

**Implementation:** New atomic claim query:
```sql
UPDATE tasks SET assigned_to=?, status='in_progress' 
WHERE task_id=? AND assigned_to IN (NULL, 'any')
```
Plus new `collab_claim_task()` MCP tool.

Pattern used by AutoGen's Team abstraction and CrewAI's hierarchical mode.

---

## Problem 2: Context Rot

### Current Pattern & Impact
```
Worker joins → Loads 20+ messages (greetings, acks, system)
→ 30-50% context consumed before work starts
→ Less room for complex reasoning/outputs
```

**Observed Impact:**
- Smaller models (32k-128k context) most affected
- 4-6 overhead messages per 1 work message
- ~1200-1500 tokens wasted per worker per session (role instructions ~500-800, autonomous instructions ~350, system messages ~200-400)

**Root Cause (Codebase):**
- `context_compiler.py` L34-112: `compile_context()` loads ALL session info, state, summary, messages, tasks, artifacts, agents, role instructions, and autonomous instructions on every call
- Default `max_messages=20` (L38) includes every greeting, ack, and system event
- `context_compiler.py` L322-352: `autonomous_instructions()` injects ~350 tokens of static boilerplate into every context compilation — never changes, always injected

### Industry Solutions

| Framework | Technique | Reduction | Approach |
|-----------|-----------|-----------|----------|
| **MetaGPT** | Role-based filtering | Up to 60-80% | Agents watch only relevant message types |
| **OpenHands** | Condenser system | Up to 2x | Auto-summarize older events |
| **LangGraph** | Scoped state objects | High | Lightweight state per node |
| **CrewAI** | Selective context | Up to 70% | Pass only immediate/relevant context |
| **Google ADK** | Scoped handoffs | 50-70% | include_contents knob for sub-agents |

**Key Insight:** Role-based filtering (MetaGPT) and condensation (OpenHands) achieve significant context reduction.

### Solution 2A: Minimal Context Loading (Immediate)

```python
# Current: Loads 20 messages by default
session_context(session_id, agent_id, max_messages=5)
```

**Files to change:**
- `context_compiler.py` L38: Change default `max_messages=20` → `max_messages=5` for workers
- `collab_mcp.py` L990: Change default `max_messages=20` → `max_messages=5`

**Expected:** 30-50% reduction in total context size. Note: messages are only one component — fixed-cost items (role instructions, autonomous instructions, session info, tasks, artifacts, agents) are not affected by this change.

### Solution 2B: Role-Based Message Filtering (Already Supported)

> **Note:** `poll_messages` already accepts `msg_types` parameter (`collab_mcp.py` L689). 
> `message_bus.py` L147 passes it through to the DB layer. This is a prompt engineering 
> change, not a code change.

Pattern from MetaGPT — agents subscribe ONLY to relevant message types:

```python
poll_messages(
    session_id, agent_id,
    msg_types=["task", "artifact"]  # Ignore acks, system, updates
)
```

**Fix Required:** Update worker instructions to use `msg_types` filter by default.

**Expected:** 40-60% context savings

### Solution 2C: Staged Context Loading (Framework Enhancement)

Pattern from Google ADK's Working Context/Session/Memory/Artifacts tiers:

```
Phase 1: Task assignment only (~500 tokens)
Phase 2: Do the work
Phase 3: Peer results (~1k tokens)
Phase 4: Synthesize
```

vs. Current: Load everything upfront (2-4k+ tokens)

**Implementation Effort:** Significantly higher than portrayed in v1. Requires changes to context compiler, new MCP tool parameters, and a state machine in session state to track per-agent phase.

**Expected:** 70-80% context savings per phase

### Solution 2D: Autonomous Instructions Compression (Immediate — NEW)

The `autonomous_instructions()` static method (`context_compiler.py` L322-352) injects ~350 tokens of boilerplate into every compilation. This can be:
1. **Condensed** to ~100 tokens (remove redundant explanations)
2. **Made conditional** — only inject on first compilation, not every poll cycle
3. **Moved to role instructions** — merge with role-specific instructions to avoid duplication

**Expected:** 250+ token savings per context compilation

---

## Problem 3: Message Inefficiency

### Current Pattern
```
Worker: "Hello! I've joined!"           # Overhead
Worker: "Acknowledged! Starting..."     # Overhead
Worker: "Progress: 50% done..."         # Overhead  
Worker: [poll timeout]                  # Overhead
Worker: "Result: [actual work]"         # Signal
Total: 5+ messages, 80% overhead
```

**Root Cause (Codebase):**
- `context_compiler.py` L290-292: Worker instructions explicitly encourage "PROGRESS UPDATES: For long tasks, send interim updates"
- `context_compiler.py` L337-340: Autonomous instructions tell agents to acknowledge every message type
- `context_compiler.py` L295-297: Step 6 encourages separate "complete" message + `leave_session`

### Industry Solutions

| Framework | Pattern | Efficiency | Messages per Task |
|-----------|---------|------------|-------------------|
| **CrewAI** | Task handoffs | Very High | 1 (structured output only) |
| **LangGraph** | State passing | High | 1-2 (explicit state transfer) |
| **MetaGPT** | Artifact pool | High | 1 (publish to pool) |
| **AutoGen** | Pub/Sub | Medium | 2-3 (broadcast + response) |
| **ChatDev** | Chat chains | Low | 5+ (full dialogue) |

**Key Insight:** CrewAI and MetaGPT achieve highest efficiency with single-message task completion.

### Solution 3A: Artifact-First Communication (Immediate)

```python
# Save work as artifact
save_artifact(...)

# Send tiny reference
send_message("Task done, see artifact art_123")
```

Pattern used by MetaGPT (structured artifact pool) and CrewAI (task outputs).

**Expected:** 80-90% message size reduction

### Solution 3B: Eliminate Acknowledgment Overhead (Immediate)

Workers start immediately without acknowledgment messages.

**Current:** 4-6 overhead msgs per task  
**Optimized:** 1 result msg per task

**Fix Required:** Remove ack encouragement from autonomous instructions (L337-340).

**Expected:** 75-83% message reduction

---

## Problem 4: Cross-Model Handoff Quality (NEW)

### The Core Challenge

When different models (Claude, GPT, Gemini, Qwen, Llama, etc.) collaborate in the same session, handoff quality degrades due to fundamental incompatibilities in how each model processes, structures, and recalls information.

### 4.1: Memory Format Incompatibility

**Problem:** Each model provider has its own memory system (ChatGPT Memories, Claude Projects, Gemini Gems) that stores context in proprietary formats optimized for their specific architecture. When Model A's output becomes Model B's input through OpenLMlib's message bus, the receiving model has no access to the sender's internal reasoning chain, working memory, or contextual assumptions.

**Observed Impact:**
- Model B may re-derive conclusions Model A already reached
- Implicit assumptions in Model A's output are lost (e.g., "as discussed earlier" references nothing in Model B's context)
- Confidence signals and uncertainty markers are model-specific and don't transfer

**Current State in OpenLMlib:**
- `messages` table (`db.py` L28-43) stores `from_model` but this metadata is never used by the context compiler
- `context_compiler.py` L209-212 shows other agents as `agent_id (model, role)` but provides no model-specific adaptation
- Artifacts are stored as plain markdown — format-neutral, which is good, but have no structured metadata about reasoning provenance

### 4.2: Reasoning Style Mismatch

**Problem:** Models have fundamentally different reasoning styles:
- **Claude:** Tends toward thorough, structured analysis with explicit caveats
- **GPT-4/o:** Concise, action-oriented, may skip intermediate reasoning steps
- **Gemini:** Broad synthesis, may introduce tangential connections
- **Qwen/Llama:** Variable — may not follow complex multi-step instructions as reliably
- **Reasoning models (o1, o3, DeepSeek-R1):** Produce long chain-of-thought that overwhelms non-reasoning models

When an orchestrator (e.g., Claude) delegates to a worker (e.g., Gemini), the instructions may be over-specified or under-specified for the receiving model's strengths.

**Current State in OpenLMlib:**
- Worker instructions in `context_compiler.py` L276-302 are identical regardless of `model` field
- The TUI (`collab_tui.py` L339-346) builds the same system prompt for all workers
- No adaptation based on model capabilities, context window size, or reasoning patterns

### 4.3: Output Format Drift

**Problem:** Without enforced output schemas, different models produce results in incompatible formats:
- One worker returns a bullet list, another returns prose, a third returns JSON
- The orchestrator must normalize/interpret all formats before synthesis
- In the TUI, `_extract_json_object()` (`collab_tui.py` L189-199) is a fragile JSON parser that fails on many model outputs, falling back to heuristic parsing (L228-235)

**Current State in OpenLMlib:**
- No output schema enforcement on `send_message()` or `save_artifact()`
- The `msg_type` enum (`db.py` L34-37) is a coarse signal but doesn't validate content structure
- Artifacts are opaque markdown blobs with no structured metadata

### 4.4: Context Contamination During Handoff

**Problem:** When one model's reasoning becomes input to another model, several failure modes emerge:
- **Ghost references:** Model A says "as we discussed" — Model B has no such memory
- **Style infection:** Model B starts mimicking Model A's formatting/reasoning style instead of using its strengths
- **Hallucinated continuity:** Model B pretends to remember a conversation it never had
- **Instruction leakage:** System prompts or tool documentation from Model A's context bleed into messages

**Current State in OpenLMlib:**
- `compile_context()` injects ALL recent messages regardless of source model
- No "conversational translation" (as Google ADK does) to rewrite prior messages
- No attribution markers to distinguish "your work" from "another agent's work"

### Industry Solutions for Handoff Quality

| Framework | Pattern | Approach |
|-----------|---------|----------|
| **Google ADK** | Scoped handoffs + conversational translation | Rewrites messages during handoff with attribution markers |
| **CrewAI** | Typed task handoffs | Structured output schemas, no raw conversation passing |
| **PantheonOS** | Context isolation | Child agents receive only task description + summary, no parent history |
| **AutoGen** | GroupChat speaker selection | LLM-driven routing based on model capabilities |
| **Universal-Adopter LoRA** | Architecture-agnostic adapters | SVD projection for cross-model skill transfer |
| **HACPO** | Heterogeneous agent training | Shared verified solution paths across model families |

### Solution 4A: Model-Aware Context Compilation (Framework Enhancement)

Adapt context compilation based on the receiving model's known characteristics:

```python
# In context_compiler.py
def compile_context(self, session_id, agent_id, max_messages=5):
    agent = self._get_agent(session_id, agent_id)
    model = agent["model"]
    
    # Adapt based on model family
    model_config = MODEL_PROFILES.get(model_family(model), DEFAULT_PROFILE)
    
    # Adjust context window usage
    max_messages = min(max_messages, model_config["optimal_context_messages"])
    
    # Add model-specific instructions
    instructions = model_config["handoff_instructions"]
```

Model profiles would include:
```python
MODEL_PROFILES = {
    "claude": {
        "optimal_context_messages": 5,
        "prefers_structured_output": True,
        "handoff_instructions": "Be thorough. Include caveats and confidence levels.",
        "reasoning_style": "analytical",
    },
    "gpt": {
        "optimal_context_messages": 5,
        "prefers_structured_output": True,
        "handoff_instructions": "Be concise. Use numbered steps for actionable items.",
        "reasoning_style": "action-oriented",
    },
    "gemini": {
        "optimal_context_messages": 8,
        "prefers_structured_output": False,
        "handoff_instructions": "Synthesize broadly. Connect findings to related areas.",
        "reasoning_style": "synthetic",
    },
    "reasoning": {  # o1, o3, DeepSeek-R1
        "optimal_context_messages": 3,
        "prefers_structured_output": True,
        "handoff_instructions": "Think step by step. Show your reasoning chain.",
        "reasoning_style": "chain-of-thought",
    },
}
```

### Solution 4B: Structured Handoff Contracts (Framework Enhancement)

Replace free-form messages with typed work orders for task handoffs:

```python
# New: Structured task handoff schema
TASK_HANDOFF_SCHEMA = {
    "task_id": str,          # Correlation ID for tracking
    "goal": str,             # Clear, bounded objective
    "constraints": list,     # Hard limits (scope, format, length)
    "output_schema": dict,   # Required output structure
    "context_summary": str,  # Distilled context (not raw history)
    "prior_findings": list,  # Relevant artifacts by reference (ID only)
    "sender_model": str,     # Attribution
    "confidence": float,     # Sender's confidence in the task framing
}
```

**Implementation in `send_message()`:**
- When `msg_type="task"`, validate content against `TASK_HANDOFF_SCHEMA`
- Store structured fields in `metadata_json`
- Receiving agent gets a clean, model-neutral task description

### Solution 4C: Conversational Translation (Framework Enhancement)

Inspired by Google ADK's handoff translation:

```python
# In context_compiler.py — when presenting messages from other models
def _translate_for_receiver(self, messages, agent_model):
    """Rewrite messages for cross-model clarity."""
    translated = []
    for msg in messages:
        if msg["from_model"] != agent_model:
            # Add attribution and strip model-specific artifacts
            translated.append({
                **msg,
                "content": f"[From {msg['from_agent']} ({msg['from_model']})]: {msg['content']}",
                "is_external": True,
            })
        else:
            translated.append(msg)
    return translated
```

This ensures:
- Every message has clear attribution (no "ghost references")
- The receiving model knows which messages are its own vs. others
- Style infection is reduced by making the boundary explicit

### Solution 4D: Output Validation Gate (Framework Enhancement)

Add a programmatic validation layer between agent outputs and the message bus:

```python
# New: Output validation before message insertion
def validate_result(content: str, task_schema: dict) -> tuple[bool, str]:
    """Validate agent output against expected schema."""
    # 1. Check for required sections
    # 2. Verify output format matches task's output_schema
    # 3. Detect hallucinated references (mentions of artifacts that don't exist)
    # 4. Flag suspiciously short responses (<50 tokens for complex tasks)
    
    if not valid:
        return False, "Output failed validation: {reason}. Please retry."
    return True, content
```

**Implementation:**
- Add as middleware in `send_message()` when `msg_type="result"`
- On validation failure, send automatic retry request back to the agent
- Log validation failures for debugging and model performance tracking

### Solution 4E: Handoff Summary Distillation (Immediate — Prompt Change)

The cheapest intervention: require agents to include a "handoff summary" when sending results, structured for cross-model consumption:

Add to worker instructions:
```
When sending results, structure your response as:
## Summary (1-2 sentences)
[What was done and the main finding]

## Key Facts (bullet list)
- [Concrete, verifiable fact 1]
- [Concrete, verifiable fact 2]

## Confidence & Caveats
- Confidence: [high/medium/low]
- Caveats: [what might be wrong or incomplete]

## Artifacts
- [artifact_id]: [brief description]
```

This gives ANY receiving model a consistent, parseable structure regardless of the sender's natural style.

---

## Comprehensive Optimization Strategy

### Phase 0: Worker Instruction Rewrite (Immediate — Zero Code Changes)

**This is the single highest-ROI change.** Rewriting worker and autonomous instructions in `context_compiler.py` unlocks Solutions 1A, 3A, 3B, and 4E simultaneously.

**Changes to `context_compiler.py`:**

1. **Worker Role Instructions (L276-302):** 
   - Remove: "If you have no tasks, wait for the orchestrator to assign you work"
   - Add: "CHECK YOUR PRE-ASSIGNED TASKS FIRST. If tasks are listed above, start immediately."
   - Remove: "PROGRESS UPDATES: For long tasks, send interim updates"
   - Add: "Save significant work as artifacts. Send ONE result message when done."
   - Add: Handoff summary template (Solution 4E)

2. **Autonomous Instructions (L322-352):**
   - Remove: "If msg_type is 'result' or 'answer': acknowledge and update your state"
   - Remove: Ack encouragement — no more "acknowledge" messages
   - Condense from ~350 tokens to ~100 tokens
   - Add: "Use msg_types filter: poll_messages(..., msg_types=['task', 'question'])"

3. **Orchestrator Role Instructions (L214-238):**
   - Add: "Send ALL tasks at session start via the plan. Do not send tasks one at a time."
   - Add: "When synthesizing results from different models, note that each model may structure output differently."

### Phase 1: Immediate Optimizations (Week 1)

| # | Technique | Source | Expected Impact | Implementation |
|---|-----------|--------|-----------------|----------------|
| 1 | Phase 0 instruction rewrite | Validation audit | Unlocks 1A, 3A, 3B, 4E | `context_compiler.py` |
| 2 | Set max_messages=5 for workers | Google ADK | 30-50% total context reduction | `context_compiler.py` L38, `collab_mcp.py` L990 |
| 3 | Compress autonomous instructions | Validation audit | 250+ token savings | `context_compiler.py` L322-352 |
| 4 | Update session templates | CrewAI/LangGraph | Parallel task assignment | `templates.py` |

### Phase 2: Framework Enhancements (Week 2-3)

| # | Enhancement | Inspiration | Implementation |
|---|-------------|-------------|----------------|
| 1 | Model-aware context profiles | Google ADK | `MODEL_PROFILES` dict + context compiler adaptation |
| 2 | `collab_claim_task()` tool | AutoGen Team | New MCP tool + atomic SQL claim |
| 3 | Conversational translation | Google ADK | `_translate_for_receiver()` in context compiler |
| 4 | Add `msg_types` default to instructions | MetaGPT | Prompt change in worker instructions |
| 5 | Basic context condensation | OpenHands | Integrate with existing `compactor.py` |
| 6 | Structured handoff template | CrewAI/ADK | Task schema validation in `send_message()` |

### Phase 3: Advanced Features (Month 2)

| # | Enhancement | Inspiration | Benefit |
|---|-------------|-------------|---------|
| 1 | Output validation gate | Contract-based MAS | Prevent cascading errors |
| 2 | Role-based context filtering | MetaGPT subscriptions | 60-80% context reduction |
| 3 | Staged context loading | Google ADK tiers | Phase-appropriate context |
| 4 | Task queue with auto-assignment | AutoGen | Worker autonomy |
| 5 | Cross-model performance tracking | HACPO | Identify which model combos work best |
| 6 | Artifact-first protocol enforcement | MetaGPT pool | Enforced message efficiency |

### Phase 4: Long-Term (Month 3+)

| # | Enhancement | Inspiration | Benefit |
|---|-------------|-------------|---------|
| 1 | Hierarchical memory integration | MemGPT/Letta, H-MEM | Persistent cross-session knowledge |
| 2 | Worker autonomy (no orchestrator) | AutoGen group chat | Reduced coordination overhead |
| 3 | Connection pooling | Standard practice | Reduce SQLite connection lifecycle overhead |
| 4 | Notification latency optimization | — | Replace 300ms file polling with faster IPC |

### Phase 5: Validation (Ongoing)

- [ ] Benchmark before/after metrics
- [ ] Test with different model combinations (Claude↔GPT, Gemini↔Qwen, etc.)
- [ ] Quantify time/token savings per phase
- [ ] Measure handoff quality via artifact consistency scoring
- [ ] Iterate based on results

---

## Validation Metrics

Track these metrics to measure improvement:

| Metric | Current | Target | Measurement |
|--------|---------|--------|-------------|
| Session duration | 2-3 min | <1.5 min | Timestamp difference |
| Messages per worker | 6+ | <3 | Message count |
| Context overhead (total) | 30-50% | <15% | Token count analysis |
| Agent utilization | 20-30% | >70% | Productive time / total time |
| Poll cycles per session | 3+ | <1 | Poll message count |
| Artifacts per session | 3-4 | 4+ (more signal) | Artifact count |
| **Handoff quality** (NEW) | Untracked | >80% consistency | Cross-model output formatting score |
| **Validation failures** (NEW) | Untracked | <10% | Failed handoff validations |
| **Token waste** | ~1200-1500/worker | <400/worker | Fixed-cost token audit |

---

## Detailed Framework Analysis

### AutoGen (Microsoft)
- **Communication:** Event-driven pub/sub with topic routing
- **Task Distribution:** Dynamic decomposition, LLM-driven delegation
- **Context Management:** Token-aware truncation, vector-backed retrieval
- **Optimizations:** Rule-based speaker selection (lower cost), async processing, message batching
- **Relevance:** Pub/sub pattern could replace sequential message sending in OpenLMlib

### CrewAI
- **Communication:** Structured task handoffs (no real-time messaging)
- **Task Distribution:** Sequential/Parallel/Hierarchical modes
- **Context Management:** Selective context parameter in Task definition
- **Optimizations:** Parallel execution, resource-aware scheduling, failure recovery
- **Relevance:** Task handoff pattern is most token-efficient for OpenLMlib

### LangGraph
- **Communication:** Graph-based state passing via directed edges
- **Task Distribution:** DAG with fork/join, data-parallel execution
- **Context Management:** Global persistent state object
- **Optimizations:** Async worker pools (up to 5x+ speedup), RL-driven routing
- **Relevance:** State-passing model eliminates redundant message history

### MetaGPT
- **Communication:** Pub/sub with role-based filtering
- **Task Distribution:** SOP-enforced deterministic pipeline
- **Context Management:** Role-specific subscriptions, structured artifacts
- **Optimizations:** Agents watch only relevant message types (up to 60-80% context savings)
- **Relevance:** Role-based filtering is the most effective context optimization

### OpenHands
- **Communication:** Action-Observation contract, event stream
- **Task Distribution:** Hierarchical sub-agent spawning
- **Context Management:** Condenser system (up to 2x token reduction)
- **Optimizations:** Context condensation, stuck detection, router LLM
- **Relevance:** Condensation system directly applicable to OpenLMlib

### ChatDev
- **Communication:** Sequential chat chains between dyads
- **Task Distribution:** Fixed chat chain topology
- **Context Management:** Memory stream, summary checkpoints
- **Optimizations:** DAG orchestration extensions
- **Relevance:** Less relevant — sequential pattern is what we're trying to fix

---

## Context Optimization Techniques (Literature)

### Progressive Summarization (MemGPT/Letta)
- Compacts history at 85% capacity threshold
- Recent 5-7 turns retained in full, older compressed
- **Tradeoff:** Goal drift risk — agents lose original intent
- **Applicability:** Good for long OpenLMlib sessions

### Four-Level Hierarchical Memory (H-MEM)
- Domain → Category → Trace → Episode
- Sublinear O(<<n) lookup, >90% bandwidth savings
- **Tradeoff:** Complex end-to-end training
- **Applicability:** Overkill for current OpenLMlib needs

### Scoped Handoffs (Google ADK)
- include_contents knob controls sub-agent context
- Conversational translation rewrites messages during handoff
- **Tradeoff:** Requires explicit configuration
- **Applicability:** Directly applicable to OpenLMlib task assignment

### Artifact Handle Pattern
- Large payloads external, agents see lightweight references
- **Tradeoff:** Adds retrieval latency
- **Applicability:** Already supported via OpenLMlib artifacts

---

## Cross-Model Handoff Techniques (Literature — NEW)

### Universal-Adopter LoRA (UAL)
- Architecture-agnostic intermediate representation for LoRA adapters
- SVD projection enables cross-model skill transfer without fine-tuning
- **Tradeoff:** Requires model weight access
- **Applicability:** Future consideration for specialized worker training

### HACPO (Heterogeneous Agent Cross-Policy Optimization)
- Shares verified solution paths and informative failure cases across model families
- Mitigates model-specific policy distribution shifts
- **Tradeoff:** Requires parallel evaluation infrastructure
- **Applicability:** Can inform which model pairs work best together

### PantheonOS Context Isolation
- Child agents receive only task description + summary, no parent history
- Prevents state modification and ensures modularity
- **Tradeoff:** Loses some contextual nuance
- **Applicability:** Directly applicable to OpenLMlib's worker context compilation

### Structured Inter-Agent Protocols
- Typed work orders replacing conversational handoffs
- Schema validation at every handoff boundary
- **Tradeoff:** Reduces agent flexibility
- **Applicability:** Foundation for Solution 4B

---

## Infrastructure Optimizations (NEW)

### Connection Lifecycle
- Each MCP tool call creates a new SQLite connection via `_collab_connection()` (`collab_mcp.py` L134-157)
- `poll_messages` creates two connections per call (L726 and L797)
- **Fix:** Implement connection pooling or reuse within the MCP server process

### Notification Latency
- File-based notification polls at 300ms intervals (`poll_interval=0.3`, `collab_mcp.py` L792)
- Minimum message delivery latency: 150ms (average)
- **Fix:** Consider named pipes (Windows) or Unix domain sockets for faster IPC

---

## References

### Frameworks
- AutoGen v0.4: https://microsoft.github.io/autogen/
- CrewAI: https://docs.crewai.com/
- LangGraph: https://langchain-ai.github.io/langgraph/
- MetaGPT: https://github.com/geekan/MetaGPT
- OpenHands: https://github.com/All-Hands-AI/OpenHands
- ChatDev: https://github.com/OpenBMB/ChatDev

### Papers & Literature
- MemGPT: "MemGPT: Towards LLMs as Operating Systems" (arXiv:2310.08560) ✅ Verified
- H-MEM: "Hierarchical Memory for High-Efficiency Long-Term Reasoning" (arXiv:2507.22925) ✅ Verified
- HACPO: "Heterogeneous Agent Cross-Policy Optimization" (arXiv, 2025)
- Multi-Agent Memory Survey: "Memory in LLM-based Multi-agent Systems" (TechRxiv)

### Blog Posts & Documentation
- Letta Memory Blocks: https://www.letta.com/blog/memory-blocks
- Google ADK Context Engineering: https://developers.googleblog.com/ (context engineering blog post)
- LangChain Context Management: https://blog.langchain.com/
- CrewAI Memory Deep Dive: https://sparkco.ai/blog/deep-dive-into-crewai-memory-systems
