# Campaign Persona Agent — Repo Implementation Spec

## 0. Project Context for Codex

We are building a hackathon demo for WeaveHacks.

The product is a synthetic voter focus group for political event analysis. A campaign operator selects or enters a political stimulus. The system fans the stimulus out to 20 synthetic voter personas, each represented by an LLM-powered persona agent. Each persona responds in its own voice. A synthesis agent then aggregates reactions into demographic sentiment signals, red flags, and useful voter voice quotes. A benchmark agent compares the simulated reaction pattern against hardcoded historical polling data for the selected event.

The primary demo event is Dobbs v. Jackson, June 2022, when the Supreme Court overturned Roe v. Wade.

The core demo claim:

```text
Campaigns spend weeks and large amounts of money waiting for polling data. This system gives a directional voter reaction signal in seconds using 20 multi-model voter personas, observable agent traces, and persistent campaign memory.
```

The product is not meant to replace polling. It is a fast directional signal and qualitative research tool.

The demo must show:

1. A Dobbs preset selected in the app.
2. A memory toggle initially OFF.
3. 20 persona reaction cards streaming into the UI.
4. Persona cards showing different models and distinct voices.
5. A synthesis agent producing segment-level sentiment breakdowns.
6. A red flag alert for a meaningful unexpected voter segment reaction.
7. A benchmark comparison against static Dobbs polling data.
8. A Weave dashboard showing one coherent run with all persona agents, synthesis, and benchmark traces.
9. A Redis Iris Agent Memory story: turning memory ON means personas can remember prior campaign stimuli.

## 1. Finalized User Decisions

Use these decisions as fixed implementation requirements.

### Backend

Use a Python async backend.

Recommended framework:

```text
FastAPI
```

Reason:

* Async fan-out is central to the demo.
* Streaming events to the frontend is required.
* Python is convenient for model SDKs, Redis Agent Memory, and Weave instrumentation.

### Model Providers

The following API variables are already available in the user’s environment:

```bash
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GEMINI_API_KEY=
OPENROUTER_API_KEY=
```

Use all four providers if possible.

Provider strategy for 20 personas:

```text
OpenAI: 7 personas
Anthropic: 7 personas
Gemini: 4 personas
OpenRouter: 2 personas
```

OpenRouter should be used for overflow/model variety, not as the core dependency. The user has about $20 available there, so keep usage controlled.

Fallback rules:

1. If OpenRouter fails, reassign its personas to OpenAI.
2. If Gemini fails or is slow, reassign Gemini personas across OpenAI and Anthropic.
3. If Anthropic fails, reassign Anthropic personas across OpenAI and Gemini.
4. If OpenAI fails, reassign OpenAI personas across Anthropic and Gemini.
5. The demo should still run if at least one major provider works.
6. Log provider failures clearly, but do not crash the whole run.

### Persona Count

Use 20 personas for the demo.

Architect for 100 later, but do not optimize for 100 until the 20-person demo path is stable.

### Redis

The following Redis Agent Memory variables are already available:

```bash
REDIS_AGENT_MEMORY_ENDPOINT=
REDIS_AGENT_MEMORY_API_KEY=
REDIS_AGENT_MEMORY_STORE_ID=
```

Use Redis Iris Agent Memory for:

* Persona profile storage.
* Persona reaction history.
* Memory toggle behavior.
* Long-running campaign continuity story.

Do not build raw Redis hashes or pub/sub as the primary memory implementation.

### Weave

The following Weave variables are already available:

```bash
WEAVE_API_KEY=
WEAVE_PROJECT_NAME=campaign-persona-agent
```

Use Weave for all backend observability.

The Weave project name is:

```text
campaign-persona-agent
```

### Benchmark

Use a hardcoded Dobbs benchmark file plus a benchmark agent that interprets the static benchmark data.

Do not fetch live polling data during the demo.

### Memory Toggle Behavior

Memory OFF:

* Clean first run.
* Do not retrieve prior persona reaction history.
* Do not include prior reactions in prompts.
* Do not write new reactions back to memory.

Memory ON:

* Retrieve persona profile.
* Retrieve prior reaction history.
* Include prior reactions in persona context.
* Write the new reaction back to Redis Agent Memory after the persona completes.

### Failed Persona Calls

Recommendation accepted:

* Omit failed persona cards unless enough failures matter.
* Continue the run if at least 15 of 20 personas complete.
* If fewer than 15 complete, show a compact warning.
* Never let one failed LLM call crash the demo.

### Deployment

Recommendation accepted:

* Local-first deployment.
* Frontend local.
* Backend local.
* Redis remote.
* Weave remote.
* All secrets in local `.env`.

### AG-UI Contract

Draft the AG-UI contract now. No more input needed.

### Persona Set

The exact 20 personas are not important yet. Start with a small seed set, then expand to 20.

### Political Tone

Keep outputs framed as research and voter sentiment analysis. Do not turn the app into personalized persuasion-message generation.

### Backup Paths

For AG-UI streaming, Weave, and Redis:

* Try the real integration first.
* Add fallbacks only if needed.
* Still implement safe failure handling so the app does not crash.

## 2. Environment Setup

Create:

```text
apps/backend/.env.example
```

with:

```bash
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
GEMINI_API_KEY=
OPENROUTER_API_KEY=

REDIS_AGENT_MEMORY_ENDPOINT=
REDIS_AGENT_MEMORY_API_KEY=
REDIS_AGENT_MEMORY_STORE_ID=

WEAVE_API_KEY=
WEAVE_PROJECT_NAME=campaign-persona-agent

BACKEND_ENV=local
DEMO_MODE=true
PERSONA_COUNT=20
PERSONA_CONCURRENCY_LIMIT=25
```

Do not commit real secrets.

The backend should load `.env` locally and validate configuration at startup.

Startup output should be safe and should not print secrets.

Expected startup summary:

```text
Campaign Persona Agent backend starting...

Environment:
- BACKEND_ENV: local
- DEMO_MODE: true
- PERSONA_COUNT: 20
- PERSONA_CONCURRENCY_LIMIT: 25

Providers:
- OpenAI: configured
- Anthropic: configured
- Gemini: configured
- OpenRouter: configured

Memory:
- Redis Agent Memory: configured

Observability:
- Weave project: campaign-persona-agent
```

## 3. Repo Structure

Use this repo layout unless the existing repo already has a strong structure.

```text
apps/
  backend/
    app/
      main.py
      config.py
      orchestrator.py
      agents/
        persona.py
        synthesis.py
        benchmark.py
      providers/
        openai_provider.py
        anthropic_provider.py
        gemini_provider.py
        openrouter_provider.py
        router.py
      memory/
        redis_agent_memory.py
        local_persona_store.py
      observability/
        weave_client.py
      streaming/
        ag_ui_events.py
      scripts/
        check_services.py
        check_redis_memory.py
        check_weave.py
        smoke_test_demo.py
    .env.example
    requirements.txt

  frontend/
    src/
      app/
      components/
        PersonaReactionCard.tsx
        SentimentBreakdown.tsx
        RedFlagAlert.tsx
        BenchmarkComparison.tsx
      lib/
        agui.ts
        api.ts
      data/
        presets.ts

data/
  personas/
    personas.json
  benchmarks/
    dobbs_2022.json

docs/
  implementation-plan.md
  demo-script.md
```

## 4. Backend Responsibilities

The backend owns:

1. Environment loading and validation.
2. Provider health checks.
3. Redis Agent Memory health checks.
4. Weave initialization.
5. Persona loading.
6. Prompt construction.
7. Parallel persona fan-out.
8. Provider fallback.
9. Synthesis agent execution.
10. Benchmark agent execution.
11. AG-UI-compatible structured event streaming.
12. Safe run failure handling.
13. Local JSON fallback for personas.
14. Basic smoke test scripts.

Do not start with frontend polish. First prove the backend can run a 3-persona smoke test.

## 5. Frontend Responsibilities

The frontend owns:

1. Stimulus preset selector.
2. Dobbs preset.
3. Stimulus text display/input.
4. Memory toggle.
5. Run button.
6. Streaming run status.
7. Persona reaction card grid.
8. Synthesis breakdown area.
9. Red flag alert area.
10. Benchmark comparison area.
11. Optional Weave trace link.

Use CopilotKit and AG-UI for generative UI.

Important rule:

```text
The backend emits structured JSON events. The frontend maps those events to predefined React components. The backend does not send HTML.
```

## 6. Data Models

### 6.1 Persona

Each persona should have this shape:

```json
{
  "persona_id": "maria_milwaukee",
  "name": "Maria",
  "age": 52,
  "location": {
    "city": "Milwaukee",
    "state": "WI",
    "geo_type": "suburban"
  },
  "race_ethnicity": "Latina",
  "education": "Some college",
  "occupation": "Union electrician",
  "industry": "Construction",
  "income_bracket": "$75k-$100k",
  "party_affiliation": "Democrat",
  "ideology": "Center-left",
  "top_issues": [
    "union jobs",
    "healthcare",
    "reproductive rights"
  ],
  "media_diet": [
    "local TV",
    "Facebook",
    "MSNBC clips"
  ],
  "institutional_trust": {
    "government": "low",
    "media": "medium",
    "experts": "medium"
  },
  "personal_stake": "Has an adult daughter and worries about reproductive healthcare access.",
  "segment_tags": [
    "suburban_women",
    "working_class",
    "union_household"
  ],
  "assigned_provider": "anthropic",
  "assigned_model": "claude-sonnet"
}
```

Fields that matter:

* Name
* Age
* City/state
* Urban/suburban/rural
* Race/ethnicity
* Education
* Occupation
* Industry
* Income bracket
* Party affiliation
* Ideology
* Top issues
* Media diet
* Institutional trust
* Personal stake
* Segment tags
* Assigned provider/model

### 6.2 Stimulus

For Dobbs:

```json
{
  "stimulus_id": "dobbs_2022",
  "event_name": "Dobbs v. Jackson Women's Health Organization",
  "event_date": "2022-06-24",
  "issue_area": "abortion_reproductive_rights",
  "stimulus_text": "The Supreme Court has overturned Roe v. Wade in the Dobbs v. Jackson decision, ending the constitutional right to abortion and returning the matter to states.",
  "benchmark_id": "dobbs_2022"
}
```

### 6.3 Persona Reaction Output

Each persona agent must return:

```json
{
  "persona_id": "maria_milwaukee",
  "persona_name": "Maria",
  "model_used": "claude-sonnet",
  "reaction_text": "I am furious. This feels like politicians decided my daughter's future for her, and I do not trust my state legislature to protect women.",
  "voter_voice_quote": "I never thought my daughter would grow up with fewer rights than I had.",
  "latency_ms": 1320
}
```

Rules:

* `reaction_text` must be 2–4 sentences.
* `voter_voice_quote` must be one short first-person sentence.
* Do not include sentiment score.
* Do not include long analysis.
* Do not output markdown-heavy content.
* Keep the persona voice distinct.

### 6.4 Synthesis Output

The synthesis agent returns:

```json
{
  "overall_sentiment": "negative_majority",
  "segments": [
    {
      "segment_id": "suburban_women",
      "segment_name": "Suburban women",
      "sentiment_direction": "strongly_negative",
      "movement_signal": "high_activation",
      "persona_count": 4,
      "summary": "Strong emotional opposition, especially among mothers and college-educated moderates."
    }
  ],
  "red_flags": [
    {
      "segment": "Moderate Republican women in suburban districts",
      "flag_description": "Unexpectedly negative reaction despite Republican affiliation; possible persuasion vulnerability.",
      "affected_personas": [
        "maria_milwaukee"
      ],
      "severity": "high"
    }
  ],
  "best_quotes": [
    {
      "persona_id": "maria_milwaukee",
      "quote": "I never thought my daughter would grow up with fewer rights than I had."
    }
  ],
  "executive_summary": "The strongest negative reaction is concentrated among women, especially younger women and suburban moderates. Rural conservative men are more supportive."
}
```

Allowed `sentiment_direction` values:

```text
strongly_negative
negative
mixed
neutral
positive
strongly_positive
```

Allowed `movement_signal` values:

```text
low_salience
persuasion_risk
persuasion_opportunity
high_activation
base_reinforcement
unclear
```

### 6.5 Benchmark Output

The benchmark agent returns:

```json
{
  "event_name": "Dobbs v. Jackson, June 2022",
  "calibration_score": 87,
  "score_label": "Directional accuracy",
  "simulated_distribution": [
    {
      "segment": "Women overall",
      "simulated": "Strongly negative"
    },
    {
      "segment": "Republicans",
      "simulated": "Positive / base intact"
    }
  ],
  "actual_polling_data": [
    {
      "segment": "Women overall",
      "actual": "47% of women strongly disapproved",
      "source_label": "Gallup/Pew June-July 2022"
    },
    {
      "segment": "National overall",
      "actual": "61% called overturning Roe a bad thing",
      "source_label": "Gallup/Pew June-July 2022"
    },
    {
      "segment": "Democrats",
      "actual": "85% of Democrats said abortion should be legal",
      "source_label": "Gallup/Pew June-July 2022"
    },
    {
      "segment": "Republicans",
      "actual": "Base largely held firm",
      "source_label": "Gallup/Pew June-July 2022"
    },
    {
      "segment": "Independents",
      "actual": "Negative lean; susceptible to attitude shifts post-Dobbs",
      "source_label": "Gallup/Pew June-July 2022"
    }
  ],
  "interpretation": "The system matched the broad direction of segment-level reactions without claiming to replace polling."
}
```

The benchmark is for demo credibility. Do not over-engineer it.

## 7. Redis Agent Memory Design

Use Redis Agent Memory as the primary memory layer.

### 7.1 Owner IDs

Each persona gets a stable owner ID:

```text
persona:maria_milwaukee
persona:raymond_georgia
persona:destiny_atlanta
```

### 7.2 Run IDs

Each run gets a unique run ID:

```text
run:dobbs_2022:2026-06-06T20-45-12Z
```

Use the same run ID for:

* Backend orchestration
* Frontend run state
* Redis session memory
* Weave session grouping

### 7.3 Long-Term Memory

Use long-term memory for stable persona profiles.

Logical shape:

```json
{
  "owner_id": "persona:maria_milwaukee",
  "namespace": "profile",
  "content": {
    "persona_id": "maria_milwaukee",
    "name": "Maria",
    "profile_text": "Maria is a 52-year-old union electrician from suburban Milwaukee..."
  }
}
```

### 7.4 Session Memory

Use session memory for reactions.

Logical shape:

```json
{
  "session_id": "run:dobbs_2022:2026-06-06T20-45-12Z",
  "owner_id": "persona:maria_milwaukee",
  "namespace": "reactions",
  "content": {
    "stimulus_id": "dobbs_2022",
    "reaction_text": "I am furious...",
    "voter_voice_quote": "I never thought my daughter would grow up with fewer rights than I had.",
    "model_used": "claude-sonnet"
  }
}
```

### 7.5 Redis Behavior

Implement:

```text
get_persona_profile(persona_id)
get_persona_with_history(persona_id, memory_enabled)
save_persona_reaction(persona_id, run_id, stimulus_id, reaction)
seed_personas()
check_redis_memory()
```

Memory OFF:

* Return profile with `prior_reactions=[]`.
* Do not write reaction.

Memory ON:

* Return profile plus prior reactions.
* Write reaction after successful persona completion.

### 7.6 Redis Fallback

Keep:

```text
data/personas/personas.json
```

If Redis read fails:

* Load personas from local JSON.
* Continue with empty history.
* Log warning.
* Do not crash.

If Redis write fails:

* Log warning.
* Continue demo.

## 8. Weave Observability Design

Initialize Weave once at backend startup.

Use project:

```text
campaign-persona-agent
```

Trace every major function:

```text
orchestrator:run_stimulus
persona_agent:<persona_id>:<model>
synthesis_agent
benchmark_agent:dobbs_2022
redis:get_persona_with_history
redis:save_persona_reaction
```

Each stimulus run should appear as one coherent Weave session/run, not disconnected traces.

Weave trace names must be readable in the dashboard.

Expected dashboard shape:

```text
campaign-persona-agent session
  ├─ persona_agent:maria_milwaukee:claude-sonnet
  ├─ persona_agent:raymond_georgia:gpt-4o
  ├─ persona_agent:destiny_atlanta:gemini
  ├─ ...
  ├─ synthesis_agent
  └─ benchmark_agent:dobbs_2022
```

The frontend should receive a `weave_url` or `trace_id` when available.

If Weave fails:

* Log warning.
* Continue the demo.
* Do not crash.

## 9. AG-UI / CopilotKit Event Contract

The backend emits structured events. The frontend maps those events to registered components.

### 9.1 Event Envelope

All streamed events use this envelope:

```json
{
  "event_type": "persona_reaction.completed",
  "run_id": "run:dobbs_2022:2026-06-06T20-45-12Z",
  "sequence": 7,
  "timestamp": "2026-06-06T20:45:19Z",
  "payload": {}
}
```

Required fields:

```text
event_type
run_id
sequence
timestamp
payload
```

Optional fields:

```text
trace_id
weave_url
error
```

### 9.2 Event Types

Use:

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

### 9.3 PersonaReactionCard

Event:

```text
persona_reaction.completed
```

Payload:

```json
{
  "persona_id": "maria_milwaukee",
  "persona_name": "Maria",
  "age": 52,
  "location": "Suburban Milwaukee, WI",
  "occupation": "Union electrician",
  "model_used": "claude-sonnet",
  "reaction_text": "I am furious. This feels like politicians decided my daughter’s future for her, and I do not trust my state legislature to protect women.",
  "voter_voice_quote": "I never thought my daughter would grow up with fewer rights than I had.",
  "latency_ms": 1320
}
```

Frontend component:

```text
PersonaReactionCard
```

### 9.4 SentimentBreakdown

Event:

```text
synthesis.segment_completed
```

Payload:

```json
{
  "segment_id": "suburban_women",
  "segment_name": "Suburban women",
  "sentiment_direction": "strongly_negative",
  "movement_signal": "high_activation",
  "persona_count": 4,
  "summary": "Strong emotional opposition, especially among mothers and college-educated moderates."
}
```

Frontend component:

```text
SentimentBreakdown
```

### 9.5 RedFlagAlert

Event:

```text
synthesis.red_flag_detected
```

Payload:

```json
{
  "segment": "Moderate Republican women in suburban districts",
  "flag_description": "Unexpectedly negative reaction despite Republican affiliation; possible persuasion vulnerability.",
  "affected_personas": [
    "maria_milwaukee",
    "linda_phoenix"
  ],
  "severity": "high"
}
```

Frontend component:

```text
RedFlagAlert
```

### 9.6 BenchmarkComparison

Event:

```text
benchmark.completed
```

Payload:

```json
{
  "event_name": "Dobbs v. Jackson, June 2022",
  "calibration_score": 87,
  "score_label": "Directional accuracy",
  "simulated_distribution": [],
  "actual_polling_data": [],
  "interpretation": "The system matched the broad direction of segment-level reactions without claiming to replace polling."
}
```

Frontend component:

```text
BenchmarkComparison
```

## 10. Backend Run Lifecycle

### 10.1 Request

Endpoint:

```text
POST /api/runs
```

Request body:

```json
{
  "stimulus_id": "dobbs_2022",
  "stimulus_text": "The Supreme Court has overturned Roe v. Wade...",
  "memory_enabled": false,
  "persona_count": 20
}
```

### 10.2 Streamed Event Order

Expected order:

1. `run.started`
2. `persona_reaction.completed` as each persona finishes
3. Optional `persona_reaction.failed`
4. `synthesis.started`
5. `synthesis.segment_completed`
6. Optional `synthesis.red_flag_detected`
7. `synthesis.completed`
8. `benchmark.started`
9. `benchmark.completed`
10. `run.completed`

### 10.3 Completion Payload

```json
{
  "run_id": "run:dobbs_2022:2026-06-06T20-45-12Z",
  "stimulus_id": "dobbs_2022",
  "completed_personas": 19,
  "failed_personas": 1,
  "memory_enabled": false,
  "total_latency_ms": 14200,
  "weave_url": "https://..."
}
```

## 11. Agent Prompt Requirements

### 11.1 Persona Agent

Persona agent must receive:

* Persona profile.
* Stimulus text.
* Prior reaction history only if memory is ON.
* Strict output schema.

Persona agent should produce:

* Short reaction, 2–4 sentences.
* One-line voter voice quote.
* No sentiment score.
* No demographic analysis.
* No generic essay.
* Voice should match persona.

Output must be valid JSON.

### 11.2 Synthesis Agent

Synthesis agent receives all persona outputs.

It should:

* Infer sentiment from natural language.
* Aggregate by segment.
* Identify movement signals.
* Identify red flags.
* Extract best quotes.
* Output structured JSON only.

### 11.3 Benchmark Agent

Benchmark agent receives:

* Synthesis output.
* Static benchmark file for Dobbs.

It should:

* Compare simulated vs actual direction.
* Return calibration score.
* Use “directional accuracy” language.
* Avoid statistical overclaiming.

## 12. Validation Scripts

Create scripts under:

```text
apps/backend/app/scripts/
```

### 12.1 Check All Services

Command:

```bash
python -m app.scripts.check_services
```

Tests:

* OpenAI minimal request.
* Anthropic minimal request.
* Gemini minimal request.
* OpenRouter minimal request.
* Redis Agent Memory write/read probe.
* Weave initialization and test trace.

Expected output:

```text
[ok] OpenAI configured
[ok] Anthropic configured
[ok] Gemini configured
[ok] OpenRouter configured
[ok] Redis Agent Memory configured
[ok] Weave configured: campaign-persona-agent
```

### 12.2 Check Redis

Command:

```bash
python -m app.scripts.check_redis_memory
```

Test flow:

1. Connect to Redis Agent Memory.
2. Write test persona profile.
3. Read test persona profile.
4. Write test reaction history.
5. Read test reaction history.
6. Print success.

Expected output:

```text
[ok] Connected to Redis Agent Memory
[ok] Wrote test persona profile
[ok] Read test persona profile
[ok] Wrote test reaction history
[ok] Read test reaction history
Redis Agent Memory validation passed
```

### 12.3 Check Weave

Command:

```bash
python -m app.scripts.check_weave
```

Test flow:

1. Initialize Weave.
2. Create one traced function.
3. Run it once.
4. Print project name and trace status.

Expected output:

```text
[ok] Weave initialized
[ok] Test trace created
Project: campaign-persona-agent
```

### 12.4 Smoke Test Demo

Command:

```bash
python -m app.scripts.smoke_test_demo
```

Test flow:

1. Load 20 personas from local JSON or Redis.
2. Select 3 personas.
3. Use one OpenAI persona, one Anthropic persona, and one Gemini persona if possible.
4. Run persona agents.
5. Run synthesis.
6. Run benchmark.
7. Create Weave traces.
8. Print success.

Expected output:

```text
[ok] Loaded personas
[ok] Ran 3 persona agents
[ok] Ran synthesis agent
[ok] Ran benchmark agent
[ok] Created Weave traces
Smoke test passed
```

## 13. Build Order for Codex

### Phase 1 — Configuration and Validation

Implement first:

1. Backend config module.
2. `.env.example`.
3. Safe environment loading.
4. Safe startup summary.
5. Provider config validation.
6. Redis validation script.
7. Weave validation script.
8. 3-persona smoke test.

Do not implement full frontend first.

### Phase 2 — Local Data

Implement:

1. `data/personas/personas.json`
2. Minimum 3 personas first.
3. Then expand to 20.
4. `data/benchmarks/dobbs_2022.json`
5. Local persona loader.
6. Local benchmark loader.

### Phase 3 — Persona Agents

Implement:

1. Provider router.
2. Provider fallback.
3. Persona prompt builder.
4. Persona JSON output parser.
5. 3-persona fan-out.
6. 20-persona fan-out.
7. Concurrency limit of 25.

### Phase 4 — Weave

Implement:

1. Weave init.
2. `@weave.op` on orchestrator.
3. `@weave.op` on persona agent.
4. `@weave.op` on synthesis agent.
5. `@weave.op` on benchmark agent.
6. Trace names include persona ID and model.

### Phase 5 — Redis Agent Memory

Implement:

1. Seed personas to Redis long-term memory.
2. Retrieve persona profile.
3. Retrieve prior reactions when memory ON.
4. Write reactions when memory ON.
5. Local JSON fallback.
6. Redis failure warnings.

### Phase 6 — Synthesis and Benchmark

Implement:

1. Synthesis agent.
2. Segment aggregation.
3. Red flag detection.
4. Quote extraction.
5. Benchmark comparison using static Dobbs file.
6. Directional accuracy output.

### Phase 7 — AG-UI Streaming

Implement:

1. Event envelope.
2. Run endpoint.
3. Streaming response.
4. Persona card events.
5. Synthesis events.
6. Red flag event.
7. Benchmark event.
8. Run completion event.

### Phase 8 — Frontend

Implement:

1. Stimulus page.
2. Dobbs preset.
3. Memory toggle.
4. Run button.
5. CopilotKit/AG-UI connection.
6. PersonaReactionCard.
7. SentimentBreakdown.
8. RedFlagAlert.
9. BenchmarkComparison.
10. Run status.

### Phase 9 — Demo Hardening

Implement:

1. Full 20-persona run.
2. Repeat 10 times locally.
3. Test memory OFF.
4. Test memory ON.
5. Test one provider failure.
6. Test Redis failure fallback.
7. Test Weave trace visibility.
8. Keep Weave tab ready.
9. Keep Redis dashboard ready.
10. Keep backup laptop ready.

## 14. Cut Order If Behind

Cut in this order:

1. Redis Context Retriever.
2. Second historical event.
3. OpenRouter provider.
4. Gemini provider.
5. Benchmark agent logic; use static benchmark component instead.
6. Persona count from 20 to 10.
7. Memory writeback; keep Redis profile storage.
8. Weave trace link in frontend.

Do not cut:

* Persona cards.
* Parallel fan-out.
* CopilotKit generative UI.
* Weave observable traces.
* Redis Agent Memory story.
* Dobbs preset.
* Synthesis output.

## 15. Guardrails

This app is a research and qualitative analysis demo.

Do not implement:

* Individualized persuasion-message generation.
* Voter targeting exports.
* Claims that synthetic personas are real voters.
* Claims that the system replaces polling.
* Autonomous political outreach.
* Broadcast campaign messaging.

Use language like:

```text
directional signal
synthetic focus group
qualitative insight
segment-level reaction
research tool
```

Avoid language like:

```text
guaranteed voter behavior
poll replacement
manipulation engine
microtargeting system
```

## 16. Immediate Codex Task

Start here:

```text
Implement the backend configuration and validation layer for Campaign Persona Agent.

Context:
We are building a WeaveHacks demo: a synthetic voter focus group that runs 20 multi-model persona agents against a Dobbs v. Jackson stimulus, streams persona reactions into a CopilotKit/AG-UI frontend, synthesizes demographic sentiment, compares against hardcoded Dobbs benchmark data, traces every agent in Weave, and stores persona profiles/reaction history in Redis Iris Agent Memory.

Already available environment variables:
OPENAI_API_KEY
ANTHROPIC_API_KEY
GEMINI_API_KEY
OPENROUTER_API_KEY
REDIS_AGENT_MEMORY_ENDPOINT
REDIS_AGENT_MEMORY_API_KEY
REDIS_AGENT_MEMORY_STORE_ID
WEAVE_API_KEY
WEAVE_PROJECT_NAME=campaign-persona-agent

Build first:
1. Backend config module.
2. .env.example.
3. Safe environment loading.
4. Safe startup summary that never prints secrets.
5. Provider availability validation.
6. Redis Agent Memory validation script.
7. Weave validation script.
8. 3-persona smoke test.
9. Local persona JSON fallback.
10. Local Dobbs benchmark JSON file.

Do not build the full frontend yet.
Do not commit real secrets.
Do not over-engineer generalized polling.
Optimize for a reliable 20-person Dobbs demo.
```

## 17. Acceptance Criteria for First Codex Pass

The first implementation pass is complete when:

1. Backend starts locally.
2. `.env.example` exists.
3. Startup prints safe config summary.
4. Missing secrets are reported clearly.
5. No secret values are printed.
6. Redis Agent Memory can be checked independently.
7. Weave can be checked independently.
8. At least one model provider can be checked independently.
9. Local persona fallback exists.
10. Local Dobbs benchmark file exists.
11. A 3-persona smoke test runs persona agents, synthesis, benchmark, and Weave trace creation.
12. No frontend implementation is required yet.
