# Why harness engineering, not a council of agents

## What we picked

```
                   ┌──────────────────────────────────┐
                   │     Claude (the only LLM)        │
                   │     + a bounded prompt           │
                   │     + access to MCP tools        │
                   └──────────────┬───────────────────┘
                                  │
                  ┌───────────────┴────────────────┐
                  ▼                                ▼
       ┌────────────────────┐        ┌────────────────────────┐
       │   MCP server       │        │   Citation validator   │
       │   (9 opinionated   │        │   (output contract     │
       │    tools)          │        │    enforcement)        │
       └────────────────────┘        └────────────────────────┘
                  │
                  ▼
       Canonical data + provenance
```

Three components, no orchestration. The LLM thinks. The MCP provides
primitives. The validator enforces the contract. Composition happens
inside the model's reasoning, not in our code.

## What this gives the founder

- **One LLM session per query, predictable cost.** ~$0.50-1 per watcher
  run; cheaper-tier routing keeps it linear at scale.
- **Hallucination defense by construction.** The citation validator
  checks every numeric claim against the DB. No "did the agents agree?"
  hand-wringing — they either resolved or didn't.
- **Frontier-model improvements compound for free.** Each new Claude
  release lifts the watcher's quality with no orchestration code to
  update.
- **Failure modes are testable, not vague.** When something goes wrong,
  it's in the prompt, a tool, or the data. Three concrete places.

## Why not a council of agents

A council pattern would use an orchestrator + specialist sub-agents
(data analyst, ops planner, critic) debating before output.

- **N× the inference cost.** Each agent in the council burns its own
  tokens. A 4-agent debate ≈ 4× single-model cost. At 10k merchants ×
  daily, this is the difference between viable and not.
- **More surface area to debug.** Was the bug in the planner's task
  decomposition? The analyst's tool choice? The critic's veto? Three
  places per bug. With a harness, it's the prompt, the tool, or the
  data.
- **"Specialist" agents are usually the same model.** Most frameworks
  use one LLM with different system prompts. Diversity of opinion is
  mostly theatrical.
- **Frontier-model improvements don't compound.** Role-specific prompts
  often need re-engineering for smarter models. We get the upgrade for
  free.

## Why not a single autonomous agent

The opposite: just point a model at the raw data with a big system
prompt and lots of tools, no harness.

- **The LLM does arithmetic in prose.** Without opinionated cognitive
  tools, it's left to compute *"4× the merchant average"* in text.
  Sometimes right, often off, usually uncited.
- **Hallucination is unbounded.** No structural validator means no way
  to know which numbers are real.
- **No reusable knowledge.** All expertise lives in the system prompt.
  Adding a new analysis requires re-prompting. With opinionated tools,
  expertise accumulates as versioned code.

## Where the moat lives

```
                    ┌──────────────────────────┐
                    │   LLM (paraphrases)      │
                    └─────────┬────────────────┘
                              │
              ┌───────────────┴───────────────┐
              ▼                               ▼
     ┌────────────────────┐       ┌────────────────────────┐
     │  SENSORY tools     │       │   COGNITIVE tools      │
     │  (any LLM could    │       │   (D2C operating       │
     │   write a SELECT)  │       │    knowledge encoded   │
     │                    │       │    as code)            │
     └────────────────────┘       └────────────────────────┘
                                              │
                                              │  ← THE MOAT
```

A generic LLM with raw DB access answers *"how many orders last week?"*.
It can't answer *"which orders are reconciliation gaps worth investigating?"*
without you teaching it what that means. The teaching can live in:

- a prompt (fragile, model-specific, expensive to evolve)
- a council of agents (over-engineered, expensive at scale)
- **a typed tool that returns the answer as a structured fact**  ← we chose this

The tool is versioned code. It outlives prompt fashions and model
upgrades.

## What we give up

- **No automatic "debate."** No second opinion emerges by itself. The
  plan provides for a skeptic loop that runs as a separate background
  process — same pattern, separate clock. Not built in v0.
- **No structural delegation.** Tools are the specialists. The
  architecture is flatter.
- **Multi-step planning is implicit.** The watcher prompt says "pick
  3-5 tools"; the model decides which. If the model is bad at planning,
  there's no separate planner layer to swap in.

These are acceptable trade-offs at v0 scale. They become interesting
again when the action space is huge, or when multiple specialist
domains genuinely need separate sub-agents — both v1.5+ problems.
