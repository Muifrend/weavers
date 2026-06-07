# Weavers Hackathon Narrative

Weavers is a synthetic voter focus group for campaign event analysis. A campaign operator generates or selects a representative persona set, gives the system a political stimulus, and the backend fans that stimulus out to many LLM-powered voter persona agents. Their reactions stream into the UI, a synthesis agent turns those reactions into segment-level signals, a benchmark agent compares the result against a fixed Dobbs v. Jackson reference dataset, Redis Agent Memory gives personas continuity across runs, CopilotKit gives the operator an AI control surface, and Weave records the agent work.

The demo claim:

> Campaigns wait weeks and spend real money for polling. Weavers gives a fast, directional qualitative signal in seconds using multiagent orchestration, evidence-backed synthetic personas, persistent campaign memory, and observable agent traces.

Important framing: this is a research and qualitative analysis tool. It does not replace polling, it complements it 

## Why This Fits The Multiagent Theme

The repo has two orchestration systems.

The first system builds persona populations:

```text
User / CopilotKit
  -> FastAPI /api/personas/generate
  -> PersonaCreationAgent
  -> PopulationPipeline
      -> population_geo_agent
      -> demographic_agent
      -> pums_population_sampler
      -> openai_sample_persona_agent_1
      -> openai_sample_persona_agent_2
      -> ...
      -> openai_sample_persona_agent_N
  -> LocalPersonaStore
  -> saved named persona set
```

The second system runs the live focus group:

```text
Frontend / CopilotKit
  -> FastAPI POST /api/runs
  -> CampaignOrchestrator
      -> ProviderRouter assigns models
      -> PersonaAgent[1..N] run concurrently
          -> Redis Agent Memory read, if memory is ON
          -> OpenAI / Anthropic / Gemini / OpenRouter call
          -> Redis Agent Memory write, if memory is ON
          -> Weave trace
          -> persona_reaction.completed SSE event
      -> SynthesisAgent
          -> segment sentiment
          -> red flags
          -> best quotes
          -> Weave trace
      -> BenchmarkAgent
          -> static Dobbs benchmark comparison
          -> Weave trace
      -> run.completed SSE event
```

That gives the hackathon story a real multiagent backbone:

- Agent graph for evidence-backed persona creation.
- Parallel agent fan-out for live persona reactions.
- A synthesis agent that reasons over agent outputs.
- A benchmark agent that evaluates the synthesized pattern against known reference data.
- A copilot agent that can drive the UI and explain results.
- A memory layer that changes agent behavior across runs.
- Observability that lets judges inspect agent traces instead of taking our word for it.

## Agent Inventory

### CampaignOrchestrator

File: `apps/backend/app/orchestrator.py`

The top-level runtime coordinator. It creates a run id, emits ordered SSE events, loads personas, assigns providers, launches persona tasks with `asyncio.create_task`, streams results with `asyncio.as_completed`, enforces the completion threshold, runs synthesis, runs benchmark, and emits `run.completed` or `run.failed`.

This is the heart of the demo. It is not a single chatbot. It is a controller coordinating many smaller agents and services.

### PersonaCreationAgent

File: `apps/backend/app/agents/persona_creation.py`

Bridges the FastAPI app to the population pipeline. It turns a request like "California, 12 personas" into a saved named persona set. It uses Census-backed demographic context, local PUMS cache, and OpenAI structured output to create evidence-backed personas.

### PopulationPipeline

File: `persona_pipeline/population.py`

Builds a representative set from public demographic evidence:

- Resolves the location to Census geography.
- Pulls ACS demographic priors.
- Samples anonymized ACS PUMS records, weighted by person weights.
- Runs one OpenAI sampled-persona agent per PUMS sample.
- Normalizes representation percentages across the generated set.

The OpenAI sampled persona agents run in a `ThreadPoolExecutor`, so persona generation is parallelized rather than one slow serial chain.

### PersonaPipeline

File: `persona_pipeline/pipeline.py`

A LangGraph graph for a single evidence-backed persona flow. Nodes include parsing, supervision, geography, demographics, occupation context, local context, evidence packet creation, and final OpenAI persona generation.

It is separate from the live focus-group path, but it strengthens the multiagent story because the system can both create evidence-backed agents and then orchestrate those agents in a later simulation.

### PersonaAgent

File: `apps/backend/app/agents/persona.py`

Runs one synthetic voter in the focus group. For each persona it:

- Retrieves the persona profile and prior reactions from Redis if memory is ON.
- Builds a persona-specific prompt.
- Calls the provider router for structured JSON.
- Validates `reaction_text` and `voter_voice_quote`.
- Writes reaction history back to Redis if memory is ON.
- Wraps the model call in a Weave operation named like `persona_agent:<persona_id>:<model>`.

### ProviderRouter

File: `apps/backend/app/providers/router.py`

Routes model calls across OpenAI, Anthropic, Gemini, and OpenRouter. The current default is cost-saving: route persona traffic to OpenAI unless the UI settings choose a provider pool. If multiple providers are enabled in the frontend settings, personas are assigned round-robin across that pool. If a preferred provider fails, the router tries fallback providers before failing that persona.

This matters for the demo because the app can show different models on persona cards, while still being resilient if one provider is slow or unavailable.

### SynthesisAgent

File: `apps/backend/app/agents/synthesis.py`

Consumes completed persona reactions and produces:

- Overall sentiment.
- Segment-level sentiment cards.
- Movement signals.
- Red flags.
- Best voter voice quotes.
- Executive summary.

It prefers OpenAI for synthesis and falls back to deterministic local logic if the model call fails.

### BenchmarkAgent

File: `apps/backend/app/agents/benchmark.py`

Loads `data/benchmarks/dobbs_2022.json` and compares the synthesized simulated distribution with static post-Dobbs reference data. This keeps the demo grounded without live polling dependencies or overclaiming.

### CopilotKit BuiltInAgent

Files:

- `apps/frontend/src/App.tsx`
- `apps/frontend/src/pages/SimulationPage.tsx`
- `apps/copilot-runtime/src/server.js`

This is the operator-facing AI assistant. It can use frontend state and frontend tools to drive the workflow:

- Switch tabs.
- Generate persona sets.
- List and select persona sets.
- Run sentiment analysis.
- Explain a persona reaction.
- Show red flags.
- Explain the benchmark.
- Summarize the overall reaction.
- Filter cards by segment.

It is not the same as the backend persona agents. It is the human-in-the-loop control plane for the simulation.

## Runtime Event Flow

The frontend/backend contract is documented in `docs/frontend-backend-contract.md`. The backend streams `text/event-stream` events from `POST /api/runs`.

Expected event order:

```text
run.started
persona_reaction.completed
persona_reaction.failed
synthesis.started
synthesis.segment_completed
synthesis.red_flag_detected
synthesis.completed
benchmark.started
benchmark.completed
run.completed
run.failed
```

The persona reaction events arrive as each persona finishes, not in a fixed persona order. That visible streaming is part of the orchestration story: judges can see parallel agent work landing incrementally.

The completion threshold is:

- For 20-persona runs, at least 15 must complete.
- For smaller runs, every requested persona must complete.

This makes the demo resilient to individual provider failures without silently pretending every agent succeeded.

## Sponsor Integration Stories

### OpenAI

OpenAI is used in three distinct places.

1. Evidence-backed persona generation

Files:

- `persona_pipeline/openai_agent.py`
- `persona_pipeline/generator.py`
- `persona_pipeline/population.py`

The persona pipeline uses the OpenAI Responses API with JSON-schema structured output. It turns ACS aggregate data and anonymized PUMS samples into synthetic persona JSON. The default model for that pipeline is `gpt-4.1`.

2. Live persona reaction runtime

Files:

- `apps/backend/app/providers/openai_provider.py`
- `apps/backend/app/providers/router.py`
- `apps/backend/app/agents/persona.py`

The backend OpenAI provider uses Chat Completions with JSON mode and default model `gpt-4o-mini`. Persona agents call through `ProviderRouter.generate_json`, so OpenAI can serve as the primary runtime model or a fallback from another provider.

3. Synthesis

File: `apps/backend/app/agents/synthesis.py`

The synthesis agent prefers OpenAI for turning many persona outputs into structured segment sentiment and red flags. If the model call fails, the code uses a deterministic fallback so the demo still completes.

Sponsor line:

> OpenAI is not just answering a chat prompt. It creates evidence-backed synthetic agents from public data, powers live persona reactions, and synthesizes many agent outputs into structured research signals.

### Redis Agent Memory

File: `apps/backend/app/memory/redis_agent_memory.py`

Redis is the persistent memory layer. It is not being used as a simple cache. The memory toggle changes how persona agents behave.

When memory is OFF:

- No Redis profile read.
- No Redis reaction-history read.
- No Redis writeback.
- Persona prompts say this is a clean first-run simulation.

When memory is ON:

- The agent searches long-term memory for the persona profile in namespace `profile`.
- The agent searches long-term memory for prior reactions in namespace `reactions`.
- Prior reactions are injected into the persona prompt.
- The completed reaction is written to session memory events.
- The completed reaction is also written to long-term episodic memory.

Key Redis shapes:

```text
ownerId: persona-<persona_id>
sessionId: run-<stimulus_id>-<timestamp>
namespace: profile
namespace: reactions
memoryType: semantic for profile
memoryType: episodic for reactions
```

Useful implementation details:

- `seed_personas()` can write persona profiles into long-term Redis memory.
- `get_persona_with_history()` reads profile and reaction history when memory is ON.
- `save_persona_reaction()` writes both session events and long-term episodic memories.
- The HTTP client sends an explicit normal `User-Agent`, based on a verified Redis Agent Memory WAF behavior noted in `repo-spec.md`.
- Redis failures return warnings and do not crash the demo.

Current-state note:

- Persona reaction writeback is implemented.
- Profile seeding exists as a method, but it is not automatically called by the normal persona generation endpoint yet. If profiles are not seeded in Redis, the code falls back to the local persona profile while still retrieving and writing reaction history.

Sponsor line:

> Redis Agent Memory turns stateless persona calls into continuing synthetic research participants. Turning memory ON makes the same persona remember prior campaign stimuli and lets the campaign continuity story survive across runs.

### CopilotKit

Files:

- `apps/frontend/src/App.tsx`
- `apps/frontend/src/pages/SimulationPage.tsx`
- `apps/copilot-runtime/src/server.js`
- `apps/backend/app/main.py`

CopilotKit gives Weavers an AI operator interface.

In the frontend:

- `CopilotKit` wraps the app.
- `CopilotSidebar` exposes the "Campaign Copilot".
- `useAgentContext` shares current UI state, persona sets, provider settings, streamed persona reactions, synthesis, red flags, and benchmark data with the copilot.
- `useFrontendTool` registers action tools the copilot can call.
- `useComponent` registers generative UI components that can render persona cards, generation progress, sentiment breakdowns, and benchmark cards inside chat.

In the runtime:

- `apps/copilot-runtime/src/server.js` runs an Express CopilotKit runtime.
- It creates a `BuiltInAgent` with instructions to stay in qualitative research mode and avoid persuasion claims.
- The default runtime model is configured by `COPILOT_MODEL`, currently defaulting to `openai/gpt-4o-mini`.

In the backend:

- FastAPI proxies `/api/copilotkit` to the CopilotKit runtime using `COPILOT_RUNTIME_URL`.
- This lets the browser use one backend origin while CopilotKit runs as its own local service.

Sponsor line:

> CopilotKit turns the multiagent system into an interactive cockpit. The operator can ask the copilot to generate a population, select a dataset, run the focus group, explain a reaction, show red flags, or filter the UI by segment.

### Weave

Files:

- `apps/backend/app/observability/weave_client.py`
- `apps/backend/app/agents/persona.py`
- `apps/backend/app/agents/synthesis.py`
- `apps/backend/app/agents/benchmark.py`
- `persona_pipeline/weave_support.py`
- `persona_pipeline/population.py`
- `persona_pipeline/pipeline.py`
- `persona_pipeline/generator.py`
- `persona_pipeline/openai_agent.py`

Weave is the observability layer for agent work.

Backend runtime:

- `WeaveClient.init()` runs at FastAPI startup.
- It uses `WEAVE_API_KEY`, maps it to `WANDB_API_KEY`, and initializes the configured `WEAVE_PROJECT_NAME`, defaulting to `campaign-persona-agent`.
- `WeaveClient.run_op()` wraps the persona, synthesis, and benchmark agent calls.
- If Weave fails, the function still runs normally and the demo continues.
- `weave_url()` is included in `run.started` and `run.completed` when available.

Persona pipeline:

- `traceable_op` wraps OpenAI JSON generation and persona pipeline operations.
- The wrapper becomes a no-op if Weave is not initialized, so local development remains simple.

Expected trace names include:

```text
persona_agent:<persona_id>:<model>
synthesis_agent
benchmark_agent:dobbs_2022
population_pipeline_initialize
openai_sample_persona_generate
persona_pipeline_run
persona_generator_generate
openai_create_json
```

Current-state note:

- The runtime wraps the major agent operations.
- The entire `CampaignOrchestrator.stream_run` function is not currently wrapped as a single parent Weave op. For judging, show the project dashboard and the named child operations. If time remains, wrapping the full run as `orchestrator:run_stimulus` would make the Weave story even cleaner.

Sponsor line:

> Weave makes the multiagent system inspectable. Judges can see which persona agents ran, which models were used, where synthesis happened, and where benchmark comparison happened instead of treating the demo as a black box.

## Demo Script

### 1. Open with the problem

"Polling is slow and expensive. Weavers is a synthetic focus group that gives campaigns a fast qualitative read. It does not replace polling; it helps teams understand directional segment reactions before formal data arrives."

### 2. Generate a persona set

In the UI or Copilot sidebar:

```text
Generate 12 personas for California
```

What to point out:

- This is not a hand-written fixture.
- The backend uses Census ACS context and weighted ACS PUMS samples.
- Each sampled record becomes one OpenAI persona-generation agent.
- The generated set is saved and selectable.

### 3. Select the Dobbs stimulus

Use the existing preset:

```text
The Supreme Court has overturned Roe v. Wade in the Dobbs v. Jackson decision, ending the constitutional right to abortion and returning the matter to states.
```

Keep memory OFF for the first run.

What to say:

"The first run is stateless. Redis is intentionally not read or written. That gives us a clean baseline."

### 4. Run the simulation

Click "Run analysis" or ask CopilotKit:

```text
Run the sentiment analysis
```

What to point out:

- Persona cards stream one by one because backend tasks run concurrently.
- Each persona card shows provider and model.
- The app does not wait for all agents before updating the UI.
- If one provider fails, the system attempts fallback and can still finish above the threshold.

### 5. Show synthesis and red flags

When synthesis completes, point at:

- Segment signals.
- Executive summary.
- Best quotes.
- Red flag alert.

What to say:

"The synthesis agent is not another persona. It is a separate analyst agent operating over the completed persona outputs."

### 6. Show benchmark comparison

If demo mode is OFF, show the benchmark card.

What to say:

"The benchmark agent compares the simulated pattern to a static post-Dobbs reference file. We use directional accuracy language because this is qualitative research, not a poll."

### 7. Turn memory ON

Change the stimulus text or rerun after a prior memory-enabled run. Turn Memory ON.

What to say:

"Now Redis Agent Memory is in the loop. The persona agent retrieves prior reactions and writes this new reaction back. The same synthetic participant can carry campaign context forward across stimuli."

### 8. Show CopilotKit controls

Ask:

```text
Show red flags
Explain the benchmark
Filter by suburban women
Explain Maria's reaction
```

What to say:

"The copilot is not just a chat box. It has tools wired to the app state and can operate the multiagent workflow."

### 9. Show Weave

Open the Weave project URL from the backend output or `run.completed`.

What to point out:

- Persona agent traces.
- Synthesis trace.
- Benchmark trace.
- Persona generation traces, if the generation path was run with Weave initialized.

## What Is Already Implemented

- FastAPI backend with `/api/runs` streaming SSE.
- `CampaignOrchestrator` for live simulation orchestration.
- Concurrent persona fan-out with `asyncio`.
- Persona reaction agent.
- Provider router for OpenAI, Anthropic, Gemini, and OpenRouter.
- UI settings to choose enabled providers and model ids.
- Redis Agent Memory client with profile search, reaction history search, session event writes, and long-term episodic writes.
- Weave wrapper for persona, synthesis, benchmark, and persona-pipeline operations.
- Synthesis agent with OpenAI path and deterministic fallback.
- Benchmark agent using `data/benchmarks/dobbs_2022.json`.
- CopilotKit sidebar, context sharing, frontend tools, and generative UI components.
- Persona generation endpoint backed by Census/PUMS/OpenAI pipeline.
- Named persona sets.
- Smoke scripts for services, Redis, Weave, demo run, and intake-to-simulation.

## Honest Current-State Notes

- The original spec describes a 7 OpenAI / 7 Anthropic / 4 Gemini / 2 OpenRouter split. The current code defaults to OpenAI for cost-saving unless providers are enabled in the Settings page. For the strongest multi-model demo, enable multiple configured providers before running.
- `FULL_DEMO_PROVIDER_PLAN` exists in `ProviderRouter` but is not used by the assignment code.
- Redis profile seeding exists but is not automatically invoked after persona generation. Reaction-history memory is implemented, and local profile fallback protects the demo.
- Weave traces major agent operations, but the whole orchestrator run is not wrapped as one parent operation yet.
- The Named Data upload UI is currently a preview and is not connected to backend ingestion.
- Attachments in the run prompt UI are previewed client-side, but image/files are not sent into the backend run request yet.

## If There Is Time Before Judging

Highest-impact polish:

1. Wrap `CampaignOrchestrator._stream_run_after_start` in a parent Weave op named `orchestrator:run_stimulus`.
2. Call `RedisAgentMemory.seed_personas()` after saving a generated persona set, or add a one-click seed script for the selected set.
3. Add a visible "memory used" indicator on persona cards when prior reactions were retrieved.
4. Add a one-click "multi-provider demo" preset in Settings that enables OpenAI, Anthropic, Gemini, and OpenRouter when configured.
5. Surface the `weave_url` as a visible link after `run.completed`.

## Validation Commands

Run from `apps/backend` with the local `.env` configured:

```bash
python -m app.scripts.check_services
python -m app.scripts.check_redis_memory
python -m app.scripts.check_weave
python -m app.scripts.smoke_test_demo
python -m app.scripts.smoke_test_intake_to_simulation
```

Run the local app stack:

```bash
cd apps/backend
uvicorn app.main:app --reload --port 8000
```

```bash
cd apps/copilot-runtime
npm run dev
```

```bash
cd apps/frontend
npm run dev
```

## One-Minute Pitch

Weavers is a multiagent synthetic focus group. First, an evidence pipeline creates representative synthetic personas from Census ACS data, weighted PUMS samples, and OpenAI structured output. Then the runtime orchestrator fans a political stimulus out to many persona agents in parallel. Redis Agent Memory gives those personas continuity across campaign stimuli. A synthesis agent turns the raw reactions into segment signals and red flags. A benchmark agent compares the result against known Dobbs reference data. CopilotKit gives the operator an AI cockpit for running and explaining the workflow. Weave traces the agent work so the whole run is inspectable.

The point is not to replace polling. The point is to give campaign teams a fast, observable, memory-aware qualitative signal while they wait for slower formal research.

