# Why harness engineering, not a council of agents

A whole class of "AI employee" demos right now use multi-agent frameworks:
LangGraph orchestrating a planner agent, a researcher agent, and a
critic agent; AutoGen's group-chat patterns; CrewAI's roles + tasks +
delegation; council-of-agents debates that vote on outcomes.

We didn't.

## What we built instead

```
                   ┌──────────────────────────────────┐
                   │     Claude (the only LLM)        │
                   │     + a bounded prompt           │
                   │     + access to MCP tools        │
                   └──────────────┬───────────────────┘
                                  │
                  ┌───────────────┴────────────────┐
                  │                                │
                  ▼                                ▼
       ┌────────────────────┐        ┌────────────────────────┐
       │   MCP server       │        │   Citation validator   │
       │   (9 opinionated   │        │   (output contract     │
       │    tools)          │        │    enforcement)        │
       └────────────────────┘        └────────────────────────┘
                  │
                  ▼
       Canonical data + provenance
       (the lake plus projections)
```

Three components, no orchestration. The LLM provides judgment. The MCP
provides primitives. The validator is the structural defense. Composition
happens *inside the model's reasoning*, not in our code.

We call this **harness engineering**: build the substrate, build the tools,
build the contract, let the model do the thinking. The same pattern Claude
Code itself uses to ship.

## Why not a council of agents

A council pattern would have an "orchestrator" model, plus specialist
sub-models (data analyst, ops planner, finance reviewer), plus maybe a
critic. Output goes through several rounds.

The pitch: separation of concerns, each agent does its narrow job well,
emergent reasoning from debate.

The reality, in our context:

1. **N× the inference cost.** Each agent in a council burns its own
   inference budget. A 4-agent debate runs ~4x cost of a single model
   with the same prompt context. For a watcher running daily across
   10k merchants, this is the difference between viable and "we need
   to raise another round."

2. **More surface area to debug.** When the output is wrong, was it
   the planner's task decomposition? The analyst's tool choice? The
   critic's veto? Three places to look for one bug. With a single model,
   it's in the prompt, the tool, or the data — three concrete things,
   each individually inspectable.

3. **The "specialist" agents are usually the same model anyway.** Most
   council frameworks use the same underlying LLM with different system
   prompts. The "diversity of opinion" is theatrical — they're all
   sampling from the same distribution.

4. **Frontier-model improvements compound for free in a harness, and
   not in a council.** When a new model ships, our watcher gets better
   automatically. A council's improvements get partially absorbed
   into role-specific prompts that may now be over-engineered for the
   smarter model.

5. **The hard part isn't reasoning, it's grounding.** Most demos that
   look impressive in a council pattern are doing something a single
   well-tooled agent could do equally well — the council is hiding the
   missing grounding behind a layer of agentic theater. We chose to put
   the engineering into grounding (citation validator, structural
   provenance, content-addressed envelopes) instead.

## Why not a single autonomous agent (no harness)

The opposite end: just point a single LLM at the raw data with a big
system prompt and lots of tool access. No structured prompt format, no
validator, no opinionated tools.

The reality:

1. **The LLM does arithmetic in its head and gets it wrong.** Without
   opinionated cognitive tools, the model is left to compute *"4× the
   merchant average"* in prose. Sometimes right, sometimes off, usually
   uncited.

2. **Hallucination is unbounded.** No validator means no structural
   check. The agent emits numbers; you have no way to know which are
   real.

3. **Failure modes are vague.** When something goes wrong, you don't
   know if it was a tool-use error, a hallucination, a math error, or
   a prompt-interpretation error. With a harness, each of those has a
   distinct signature.

4. **No reusable knowledge.** The "expertise" lives entirely in the
   system prompt. Adding a new analysis requires re-prompting. With
   opinionated cognitive tools, expertise accumulates in code that's
   versioned, tested, and inspectable.

## Why harness specifically

What harness engineering buys us that the other two patterns don't:

### The cognitive layer is where the moat lives

```
                    ┌──────────────────────────┐
                    │   LLM (paraphrases)      │
                    └─────────┬────────────────┘
                              │
              ┌───────────────┴───────────────┐
              │                               │
              ▼                               ▼
     ┌────────────────────┐       ┌────────────────────────┐
     │  SENSORY tools     │       │   COGNITIVE tools      │
     │  (any LLM could    │       │   (D2C-specific        │
     │   write a SELECT)  │       │    operating knowledge │
     │                    │       │    encoded as code)    │
     └────────────────────┘       └────────────────────────┘
                                              │
                                              │  ← THE MOAT
                                              │
```

A generic LLM with raw DB access can answer *"how many orders did I have
last week?"*. It cannot answer *"which orders are reconciliation gaps
worth investigating?"* without you teaching it what "reconciliation gap"
means in your business. That teaching can live in:

- a prompt (fragile, model-specific, expensive to evolve)
- a council of agents (over-engineered, expensive)
- **a typed tool that computes the answer and returns it as a fact**
  ← what we picked

The tool is versioned code with tests (eventually). It outlives prompt
fashions and model upgrades. It's the architectural payload of "MCP is
the moat."

### The citation contract is enforceable

A council can vote on whether numbers look right. A harness can
*structurally enforce* that every numeric claim binds to a real
envelope_id in the lake. See [agent layer](./04-agent-layer.md#citation-contract)
for how.

### Failure modes are explicit and named

| Step      | Failure                                      | Detected by             |
| --------- | -------------------------------------------- | ----------------------- |
| Tool call | Tool returns 0 results                       | Tool's `reasoning` text |
| Tool call | Tool errors                                  | Try/except in tool body |
| LLM       | Hallucinated number                          | Citation validator      |
| LLM       | Hallucinated envelope_id                     | DB-backed cite resolution |
| LLM       | Wrong tool picked                            | Founder rejects in inbox |
| Output    | Preamble before proposal                     | `_strip_preamble()` post-process |
| Output    | Network error mid-stream                     | Subprocess returns non-zero |

A council might catch some of these by debate. A harness catches them by
construction. The latter is testable; the former is hopeful.

### Cost is predictable

Each watcher run is bounded:

- One LLM session
- 3-5 tool calls
- One validator pass
- One disk write

Cost: ~$0.50–$1 per run for the watcher loop with the strongest model.
Across 10k merchants × daily runs × cheaper model tiers for routine
work, this is in the order of dollars per merchant per month. A council
pattern would be a multiple of that.

## What we give up

For honesty:

- **No "debate" or "second opinion" emerges automatically.** The plan
  v2 talks about a skeptic loop that runs as a background process —
  a separate single-model invocation that tries to falsify recent
  beliefs. That's the harness equivalent of a critic in a council,
  but it runs on its own clock, not as part of every proposal.
- **No automatic "delegation" to specialist sub-agents.** Tools are
  the specialists. The architecture is flatter.
- **Multi-step planning is implicit in the prompt + model reasoning,
  not explicit in code.** The watcher prompt says "pick 3-5 tools";
  the model decides which. If the model is bad at planning, we don't
  have a separate planner layer to swap in.

We think these are acceptable trade-offs at v0 scale. They become
interesting again when:
- The action space gets large (council-style routing might help triage)
- Multiple specialist domains coexist (legal review + finance review +
  ops review might benefit from explicit sub-agents)
- Tools become unwieldy (a sub-agent that "knows" a tool family could
  reduce the parent prompt size)

None of those are v0 problems. They're v1.5+ problems.

## TL;DR

We picked harness engineering because:

- It puts the moat in **versioned code (the cognitive tools)**, not in a
  fragile prompt or an expensive council.
- It makes the **citation contract structural** instead of social.
- It makes **frontier-model improvements compound for free**.
- It keeps the cost line **predictable and low**.
- It makes **failure modes explicit and testable**.

The council pattern is appropriate for problems that genuinely need
multiple specialist perspectives. A D2C analytics agent is not one of
those problems — yet.
