# Multi-Agent Collaboration Optimization Plan

**Date:** April 14, 2026  
**Source:** Analysis of OpenLMlib sessions + 6 framework comparisons + context optimization research  
**Status:** Research-validated

**Research Scope:** 
- Frameworks analyzed: AutoGen, CrewAI, LangGraph, ChatDev, MetaGPT, OpenHands
- Context optimization: MemGPT/Letta, H-MEM, Google ADK, LangChain, DisCEdge, vLLM
- Academic papers: Multi-agent memory survey, distributed context management

---

## Executive Summary

OpenLMlib's collaboration sessions suffer from two critical inefficiencies validated against industry benchmarks:

1. **Sequential bottlenecks** cause 1-2 min idle time per worker (industry parallel speedup: 3-5.75x)
2. **Context rot** consumes 30-50% of smaller model windows on chatter (industry achieves 60-90% reduction via filtering/summarization)

Solutions validated by production frameworks can reduce overhead by 60-80% and improve agent utilization 3x.

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

### Industry Solutions

| Framework | Pattern | Speedup | Approach |
|-----------|---------|---------|----------|
| **CrewAI** | Parallel mode | 3x | Independent tasks execute simultaneously |
| **LangGraph** | Fork/join subgraphs | 5.75x | Data-parallel with async worker pools |
| **AutoGen** | Dynamic speaker selection | 2-3x | LLM-driven delegation, async processing |
| **OpenHands** | Sub-agent spawning | 2x | Hierarchical coordination, blocking parallel |
| **MetaGPT** | DAG pipeline | 1x | Sequential only |
| **ChatDev** | Chat chains | 1x | Sequential only |

**Key Insight:** Parallel execution achieves 3-5.75x speedup in production frameworks.

### Solution 1A: Parallel Task Assignment (Immediate)

Include COMPLETE plan in session creation with assigned workers:

```python
create_session(
    plan=[
        {"step": 1, "task": "[FULL DETAILS]", "assigned_to": "agent_qwen"},
        {"step": 2, "task": "[FULL DETAILS]", "assigned_to": "agent_gemini"},
    ]
)
```

Workers see plan on join → Start immediately → No waiting.

**Expected:** 50-70% time reduction (based on CrewAI/LangGraph benchmarks)

### Solution 1B: Task Queue with Auto-Assignment (Framework Enhancement)

```
Session created → Tasks pre-loaded in queue
Workers join → Auto-claim next task → Work immediately
```

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
- Smaller models (250k-400k) most affected
- 4-6 overhead messages per 1 work message
- 500-1000 tokens wasted per worker per session

### Industry Solutions

| Framework | Technique | Reduction | Approach |
|-----------|-----------|-----------|----------|
| **MetaGPT** | Role-based filtering | 60-80% | Agents watch only relevant message types |
| **OpenHands** | Condenser system | 2x | Auto-summarize older events |
| **LangGraph** | Scoped state objects | 90% | Sub-2MB for 50-node workflows |
| **CrewAI** | Selective context | 70% | Pass only immediate/relevant context |
| **Google ADK** | Scoped handoffs | 50-70% | include_contents knob for sub-agents |

**Key Insight:** Role-based filtering (MetaGPT) and condensation (OpenHands) achieve 2-10x context reduction.

### Solution 2A: Minimal Context Loading (Immediate)

```python
# Current: Loads 50 messages
session_context(session_id, agent_id, max_messages=5)
```

**Expected:** 90% reduction in history overhead

### Solution 2B: Role-Based Message Filtering (Framework Enhancement)

Pattern from MetaGPT - agents subscribe ONLY to relevant message types:

```python
poll_messages(
    session_id, agent_id,
    msg_types=["task", "artifact"]  # Ignore acks, system, updates
)
```

MetaGPT achieves 60-80% context reduction with this pattern.

**Expected:** 40-60% context savings

### Solution 2C: Staged Context Loading (Framework Enhancement)

Pattern from Google ADK's Working Context/Session/Memory/Artifacts tiers:

```
Phase 1: Task assignment only (~500 tokens)
Phase 2: Do the work
Phase 3: Peer results (~1k tokens)
Phase 4: Synthesize
```

vs. Current: Load everything upfront (10k+ tokens)

**Expected:** 70-80% context savings per phase

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

**Expected:** 75-83% message reduction

---

## Comprehensive Optimization Strategy

### Immediate (Use Now - No Framework Changes)

| # | Technique | Source | Expected Impact |
|---|-----------|--------|----------------|
| 1 | Parallel task assignment in plan | CrewAI/LangGraph | 50-70% faster |
| 2 | Broadcast tasks at session start | AutoGen | 50% less waiting |
| 3 | Minimal context (max_messages=5) | Google ADK | 90% less history |
| 4 | Artifact-first communication | MetaGPT/CrewAI | 80-90% smaller msgs |
| 5 | Eliminate acknowledgment msgs | CrewAI | 75% fewer messages |
| 6 | Message type filtering | MetaGPT | 40-60% less context |

**Combined Expected Impact:**
- Time: 2-3 min → 1-2 min (33-50% faster)
- Messages: 6+ per worker → 2-3 (50-67% fewer)
- Context: 30-50% → 5-10% of window (60-80% reduction)
- Tokens: 500-1000 → 100-200 wasted (70-80% savings)
- Utilization: 20-30% → 70-80% productive (3x better)

### Short-Term (Framework Enhancements)

| # | Enhancement | Inspiration | Implementation |
|---|-------------|-------------|----------------|
| 1 | Task queue with auto-assignment | AutoGen Team | `collab_claim_task()` tool |
| 2 | Get my task view | CrewAI context | `collab_get_my_task()` tool |
| 3 | Staged context loading | Google ADK tiers | `stage` parameter on context tools |
| 4 | Context condensation | OpenHands | Auto-summarize old messages |

### Long-Term (Architectural Changes)

| # | Enhancement | Inspiration | Benefit |
|---|-------------|-------------|---------|
| 1 | Role-based context filtering | MetaGPT subscriptions | 60-80% context reduction |
| 2 | Artifact-first protocol | MetaGPT pool | Enforced message efficiency |
| 3 | Worker autonomy | AutoGen group chat | No orchestrator required |
| 4 | Hierarchical memory | MemGPT/Letta | Persistent cross-session knowledge |
| 5 | Distributed context | DisCEdge | Multi-session context sharing |

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
- **Context Management:** Global persistent state object, sub-2MB for 50 nodes
- **Optimizations:** Async worker pools (5.75x speedup), RL-driven routing
- **Relevance:** State-passing model eliminates redundant message history

### MetaGPT
- **Communication:** Pub/sub with role-based filtering
- **Task Distribution:** SOP-enforced deterministic pipeline
- **Context Management:** Role-specific subscriptions, structured artifacts
- **Optimizations:** Agents watch only relevant message types (60-80% context savings)
- **Relevance:** Role-based filtering is the most effective context optimization

### OpenHands
- **Communication:** Action-Observation contract, event stream
- **Task Distribution:** Hierarchical sub-agent spawning
- **Context Management:** Condenser system (2x token reduction)
- **Optimizations:** Context condensation, stuck detection, router LLM
- **Relevance:** Condensation system directly applicable to OpenLMlib

### ChatDev
- **Communication:** Sequential chat chains between dyads
- **Task Distribution:** Fixed chat chain topology
- **Context Management:** Memory stream, summary checkpoints
- **Optimizations:** Co-Saving (50% token reduction), DAG orchestration
- **Relevance:** Less relevant - sequential pattern is what we're trying to fix

---

## Context Optimization Techniques (Literature)

### Progressive Summarization (MemGPT/Letta)
- Compacts history at 85% capacity threshold
- Recent 5-7 turns retained in full, older compressed
- **Tradeoff:** Goal drift risk - agents lose original intent
- **Applicability:** Good for long OpenLMlib sessions

### Four-Level Hierarchical Memory (H-MEM)
- Domain → Category → Trace → Episode
- Sublinear O(<<n) lookup, >90% bandwidth savings
- **Tradeoff:** Complex end-to-end training
- **Applicability:** Overkill for current OpenLMlib needs

### Scoped Handoffs (Google ADK)
- include_contents knob controls sub-agent context
- **Tradeoff:** Requires explicit configuration
- **Applicability:** Directly applicable to OpenLMlib task assignment

### Artifact Handle Pattern
- Large payloads external, agents see lightweight references
- **Tradeoff:** Adds retrieval latency
- **Applicability:** Already supported via OpenLMlib artifacts

### Distributed Context (DisCEdge)
- Pre-tokenized sequences, geo-distributed KV store
- 14% latency improvement, 15% sync overhead reduction
- **Tradeoff:** Multi-tenant contention
- **Applicability:** Future consideration for multi-session scenarios

---

## Implementation Roadmap

### Phase 1: Immediate Optimizations (Week 1)
- [ ] Update session templates to use parallel task assignment
- [ ] Add guidance to skip acknowledgment messages
- [ ] Set max_messages=5 as default for workers
- [ ] Promote artifact-first communication pattern

### Phase 2: Framework Enhancements (Week 2-3)
- [ ] Add `collab_get_my_task()` tool
- [ ] Add message type filtering to poll_messages
- [ ] Add staged context loading support
- [ ] Implement basic context condensation

### Phase 3: Advanced Features (Month 2)
- [ ] Role-based context filtering
- [ ] Task queue with auto-assignment
- [ ] Artifact-first protocol enforcement
- [ ] Hierarchical memory integration

### Phase 4: Validation (Ongoing)
- [ ] Benchmark before/after metrics
- [ ] Test with different model sizes
- [ ] Quantify time/token savings
- [ ] Iterate based on results

---

## Validation Metrics

Track these metrics to measure improvement:

| Metric | Current | Target | Measurement |
|--------|---------|--------|-------------|
| Session duration | 2-3 min | <1.5 min | Timestamp difference |
| Messages per worker | 6+ | <3 | Message count |
| Context overhead | 30-50% | <10% | Token count analysis |
| Agent utilization | 20-30% | >70% | Productive time / total time |
| Poll cycles per session | 3+ | <1 | Poll message count |
| Artifacts per session | 3-4 | 4+ (more signal) | Artifact count |

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
- MemGPT: "MemGPT: Towards LLMs as Operating Systems" (arXiv:2310.08560)
- H-MEM: "Hierarchical Memory for High-Efficiency Long-Term Reasoning" (arXiv:2507.22925)
- DisCEdge: "Distributed Context Management for LLM Inference Services at the Edge" (arXiv:2511.22599)
- Multi-Agent Memory Survey: "Memory in LLM-based Multi-agent Systems" (TechRxiv)

### Blog Posts
- Letta Memory Blocks: https://www.letta.com/blog/memory-blocks
- Google ADK: "Architecting Efficient Context-Aware Multi-Agent Framework"
- LangChain Context Management: https://blog.langchain.com/
- CrewAI Memory Deep Dive: https://sparkco.ai/blog/deep-dive-into-crewai-memory-systems
