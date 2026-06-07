import { useDeferredValue, useMemo, useRef, useState } from "react";
import { useAgentContext, useComponent, useFrontendTool } from "@copilotkit/react-core/v2";
import { z } from "zod";
import { BenchmarkComparison } from "../components/BenchmarkComparison";
import { PersonaReactionCard } from "../components/PersonaReactionCard";
import { RedFlagAlert } from "../components/RedFlagAlert";
import { SentimentBreakdown } from "../components/SentimentBreakdown";
import { SimulationControls } from "../components/SimulationControls";
import { dobbsPreset } from "../data/presets";
import type {
  BenchmarkPayload,
  EventEnvelope,
  PersonaFailedPayload,
  PersonaReactionPayload,
  RedFlagPayload,
  RunCompletedPayload,
  RunState,
  SynthesisCompletedPayload,
  SynthesisSegmentPayload
} from "../lib/agui";
import { generatePersonasForState, startSimulation, type PersonaGenerationResponse } from "../services/simulationClient";

const personaSchema = z.object({
  persona_id: z.string(),
  persona_name: z.string(),
  age: z.number(),
  location: z.string(),
  occupation: z.string(),
  segment_tags: z.array(z.string()),
  provider: z.string(),
  model_used: z.string(),
  reaction_text: z.string(),
  voter_voice_quote: z.string(),
  latency_ms: z.number().optional()
});

const segmentSchema = z.object({
  segment_id: z.string(),
  segment_name: z.string(),
  sentiment_direction: z.string(),
  movement_signal: z.string(),
  persona_count: z.number(),
  summary: z.string()
});

const benchmarkSchema = z.object({
  event_name: z.string(),
  calibration_score: z.number(),
  score_label: z.string(),
  simulated_distribution: z.array(z.object({ segment: z.string(), simulated: z.string() })),
  actual_polling_data: z.array(z.object({ segment: z.string(), actual: z.string(), source_label: z.string() })),
  interpretation: z.string()
});

type ActiveTab = "intake" | "sentiment";

export function SimulationPage() {
  const [stimulusText, setStimulusText] = useState(dobbsPreset.stimulus_text);
  const [memoryEnabled, setMemoryEnabled] = useState(false);
  const [personaCount, setPersonaCount] = useState(20);
  const [activeTab, setActiveTab] = useState<ActiveTab>("intake");
  const [generationLocation, setGenerationLocation] = useState("California");
  const [generationCount, setGenerationCount] = useState(20);
  const [generationState, setGenerationState] = useState<"idle" | "generating" | "completed" | "failed">("idle");
  const [generationResult, setGenerationResult] = useState<PersonaGenerationResponse | null>(null);
  const [runState, setRunState] = useState<RunState>("idle");
  const [personas, setPersonas] = useState<PersonaReactionPayload[]>([]);
  const deferredPersonas = useDeferredValue(personas);
  const [failedPersonas, setFailedPersonas] = useState<PersonaFailedPayload[]>([]);
  const [segments, setSegments] = useState<SynthesisSegmentPayload[]>([]);
  const [redFlags, setRedFlags] = useState<RedFlagPayload[]>([]);
  const [synthesis, setSynthesis] = useState<SynthesisCompletedPayload | null>(null);
  const [benchmark, setBenchmark] = useState<BenchmarkPayload | null>(null);
  const [completion, setCompletion] = useState<RunCompletedPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [activeSegment, setActiveSegment] = useState("all");
  const abortRef = useRef<AbortController | null>(null);

  const filteredPersonas = useMemo(() => {
    if (activeSegment === "all") return deferredPersonas;
    return deferredPersonas.filter((persona) => persona.segment_tags.includes(activeSegment));
  }, [activeSegment, deferredPersonas]);

  const segmentOptions = useMemo(() => {
    const tags = new Set<string>();
    for (const persona of personas) {
      for (const tag of persona.segment_tags) tags.add(tag);
    }
    return [...tags].sort();
  }, [personas]);

  const progressLabel = useMemo(() => {
    if (runState === "idle") return "Ready";
    if (runState === "starting") return "Starting run";
    if (runState === "streaming_personas") return `Streaming personas: ${personas.length}/${personaCount}`;
    if (runState === "synthesizing") return "Synthesizing segment signals";
    if (runState === "benchmarking") return "Comparing against Dobbs benchmark";
    if (runState === "completed") return "Run complete";
    return "Run failed";
  }, [personaCount, personas.length, runState]);

  const generationStatusLabel = useMemo(() => {
    if (generationState === "generating") return "Generating population";
    if (generationState === "completed") return `${generationResult?.personas.length ?? 0} personas ready`;
    if (generationState === "failed") return "Generation failed";
    return "Ready to generate";
  }, [generationResult?.personas.length, generationState]);

  const canRunSimulation =
    generationState === "completed" && (generationResult?.personas.length ?? 0) >= personaCount;

  useAgentContext({
    description:
      "Current state of the campaign persona simulator UI. Use this to answer questions about personas, red flags, sentiment, benchmark, filters, and run status.",
    value: {
      stimulusText,
      preset: dobbsPreset.event_name,
      activeTab,
      memoryEnabled,
      generationState,
      generationLocation,
      generationCount,
      generatedPersonaCount: generationResult?.personas.length ?? 0,
      generatedPersonas: generationResult?.personas.map((persona) => ({
        name: persona.name,
        age: persona.age,
        raceEthnicity: persona.race_ethnicity,
        occupation: persona.occupation,
        representationPct: persona.representation_pct ?? null,
        segments: persona.segment_tags
      })) ?? [],
      runState,
      activeSegment,
      personaCount,
      completedPersonaCount: personas.length,
      failedPersonaCount: failedPersonas.length,
      personas: personas.map((persona) => ({
        name: persona.persona_name,
        provider: persona.provider,
        model: persona.model_used,
        segments: persona.segment_tags,
        reaction: persona.reaction_text,
        quote: persona.voter_voice_quote
      })),
      segments,
      redFlags,
      synthesis,
      benchmark
    }
  });

  useFrontendTool(
    {
      name: "switchWorkspaceTab",
      description: "Switch between the persona intake and sentiment analysis tabs.",
      parameters: z.object({ tab: z.enum(["intake", "sentiment"]) }),
      handler: async ({ tab }) => {
        setActiveTab(tab);
        return `Switched to ${tab === "intake" ? "Persona Intake" : "Sentiment Analysis"}.`;
      }
    },
    []
  );

  useFrontendTool(
    {
      name: "explainPersonaReaction",
      description: "Explain one persona's reaction using the current simulation state.",
      parameters: z.object({ personaName: z.string() }),
      handler: async ({ personaName }) => {
        const persona = personas.find(
          (item) => item.persona_name.toLowerCase() === personaName.toLowerCase()
        );
        if (!persona) return `I could not find a persona named ${personaName} in the current run.`;
        return `${persona.persona_name} (${persona.segment_tags.join(", ")}) reacted through ${persona.model_used}: ${persona.reaction_text} Representative quote: "${persona.voter_voice_quote}"`;
      }
    },
    [personas]
  );

  useFrontendTool(
    {
      name: "showRedFlags",
      description: "Summarize the current simulation red flags.",
      handler: async () => {
        if (redFlags.length === 0) return "No red flags have been detected in the current run yet.";
        return redFlags
          .map(
            (flag) =>
              `${flag.severity.toUpperCase()}: ${flag.segment} - ${flag.flag_description} Affected personas: ${flag.affected_personas.join(", ")}.`
          )
          .join("\n");
      }
    },
    [redFlags]
  );

  useFrontendTool(
    {
      name: "explainBenchmark",
      description: "Explain the benchmark comparison from the current run.",
      handler: async () => {
        if (!benchmark) return "Benchmark results are not available yet.";
        return `${benchmark.event_name}: ${benchmark.calibration_score}/100 ${benchmark.score_label}. ${benchmark.interpretation}`;
      }
    },
    [benchmark]
  );

  useFrontendTool(
    {
      name: "summarizeOverallReaction",
      description: "Summarize the current run's overall voter reaction.",
      handler: async () => {
        if (personas.length === 0) return "No persona reactions have streamed yet.";
        const summary = synthesis?.executive_summary ?? "Synthesis is still pending.";
        return `${personas.length} personas completed and ${failedPersonas.length} failed. Overall sentiment: ${synthesis?.overall_sentiment ?? "pending"}. ${summary}`;
      }
    },
    [failedPersonas.length, personas.length, synthesis]
  );

  useFrontendTool(
    {
      name: "filterBySegment",
      description: "Filter the persona grid by a segment tag. Use 'all' to clear the filter.",
      parameters: z.object({ segment: z.string() }),
      handler: async ({ segment }) => {
        const normalized = segment.trim().toLowerCase().replaceAll(" ", "_");
        if (normalized === "all") {
          setActiveSegment("all");
          return "Cleared the segment filter.";
        }
        const match = segmentOptions.find((item) => item.toLowerCase() === normalized);
        if (!match) return `No segment named ${segment} exists in the current run.`;
        setActiveSegment(match);
        return `Filtered the persona grid to ${match.replaceAll("_", " ")}.`;
      }
    },
    [segmentOptions]
  );

  useComponent(
    {
      name: "showPersonaReactionCard",
      description: "Render a persona reaction card in the chat.",
      parameters: personaSchema,
      render: (persona) => <PersonaReactionCard persona={{ ...persona, latency_ms: persona.latency_ms ?? 0 }} />
    },
    []
  );

  useComponent(
    {
      name: "showSentimentBreakdown",
      description: "Render segment-level sentiment insight cards in the chat.",
      parameters: z.object({ segments: z.array(segmentSchema) }),
      render: ({ segments: chatSegments }) => (
        <SentimentBreakdown segments={chatSegments as SynthesisSegmentPayload[]} />
      )
    },
    []
  );

  useComponent(
    {
      name: "showBenchmarkComparison",
      description: "Render a Dobbs benchmark comparison card in the chat.",
      parameters: benchmarkSchema,
      render: (chatBenchmark) => <BenchmarkComparison benchmark={chatBenchmark as BenchmarkPayload} />
    },
    []
  );

  function resetRun() {
    setRunState("starting");
    setPersonas([]);
    setFailedPersonas([]);
    setSegments([]);
    setRedFlags([]);
    setSynthesis(null);
    setBenchmark(null);
    setCompletion(null);
    setError(null);
    setActiveSegment("all");
  }

  function handleEvent(event: EventEnvelope) {
    switch (event.event_type) {
      case "run.started":
        setRunState("streaming_personas");
        break;
      case "persona_reaction.completed":
        setPersonas((current) => [...current, event.payload as PersonaReactionPayload]);
        break;
      case "persona_reaction.failed":
        setFailedPersonas((current) => [...current, event.payload as PersonaFailedPayload]);
        break;
      case "synthesis.started":
        setRunState("synthesizing");
        break;
      case "synthesis.segment_completed":
        setSegments((current) => [...current, event.payload as SynthesisSegmentPayload]);
        break;
      case "synthesis.red_flag_detected":
        setRedFlags((current) => [...current, event.payload as RedFlagPayload]);
        break;
      case "synthesis.completed":
        setSynthesis(event.payload as SynthesisCompletedPayload);
        break;
      case "benchmark.started":
        setRunState("benchmarking");
        break;
      case "benchmark.completed":
        setBenchmark(event.payload as BenchmarkPayload);
        break;
      case "run.completed":
        setCompletion(event.payload as RunCompletedPayload);
        setRunState("completed");
        break;
      case "run.failed":
        setError(event.error?.message ?? "The run failed. Partial results are preserved.");
        setRunState("failed");
        break;
      default:
        break;
    }
  }

  async function runSimulation() {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    resetRun();

    try {
      await startSimulation(
        {
          stimulus_id: dobbsPreset.stimulus_id,
          stimulus_text: stimulusText,
          memory_enabled: memoryEnabled,
          persona_count: personaCount
        },
        {
          onEvent: handleEvent,
          onError: (caught) => {
            if (!controller.signal.aborted) {
              setError(caught.message);
              setRunState("failed");
            }
          }
        },
        controller.signal
      );
    } catch (caught) {
      if (!controller.signal.aborted) {
        setError(caught instanceof Error ? caught.message : "Simulation failed.");
        setRunState("failed");
      }
    }
  }

  async function generatePopulationPersonas() {
    setGenerationState("generating");
    setGenerationResult(null);
    setError(null);
    try {
      const result = await generatePersonasForState(generationLocation, generationCount);
      setGenerationResult(result);
      setPersonaCount(Math.min(result.personas.length, 20));
      setGenerationState("completed");
    } catch (caught) {
      setGenerationState("failed");
      setError(caught instanceof Error ? caught.message : "Persona generation failed.");
    }
  }

  return (
    <main className="weavers-shell">
      <aside className="weavers-sidebar">
        <div className="sidebar-brand">
          <strong>weavers</strong>
          <span aria-hidden="true">‹</span>
        </div>
        <nav className="workspace-tabs" aria-label="Workspace tabs">
          <button
            className={activeTab === "intake" ? "active" : ""}
            onClick={() => setActiveTab("intake")}
            type="button"
          >
            Persona Intake
          </button>
          <button
            className={activeTab === "sentiment" ? "active" : ""}
            onClick={() => setActiveTab("sentiment")}
            type="button"
          >
            Sentiment Analysis
          </button>
        </nav>
        <div className="service-list">
          <span>AI services</span>
          <p>Redis Agent Memory</p>
          <p>Weave traces</p>
          <p>CopilotKit</p>
        </div>
      </aside>

      <section className="weavers-main simulation-app">
        <header className="workspace-header">
          <div>
            <p className="eyebrow">Synthetic voter focus group</p>
            <h1>{activeTab === "intake" ? "Persona Intake" : "Sentiment Analysis"}</h1>
          </div>
          <aside className="status-panel compact">
            <span className={`status-dot ${activeTab === "intake" ? generationState : runState}`} />
            <strong>{activeTab === "intake" ? generationStatusLabel : progressLabel}</strong>
            <p>
              {generationResult?.personas.length ?? 0} generated | {personas.length} analyzed |{" "}
              {failedPersonas.length} failed
            </p>
            {completion?.weave_url ? (
              <a href={completion.weave_url} target="_blank" rel="noreferrer">
                Open Weave trace
              </a>
            ) : null}
          </aside>
        </header>

        {activeTab === "intake" ? (
          <>
            <section className="persona-generator-panel">
              <div>
                <p className="eyebrow">Census persona generator</p>
                <h2>Build a representative state population</h2>
                <p className="generator-copy">
                  Fetch ACS Census priors, draw weighted local ACS PUMS samples, initialize one persona
                  agent per sample, and save the generated population into the simulation persona store.
                </p>
              </div>
              <label>
                State
                <input value={generationLocation} onChange={(event) => setGenerationLocation(event.target.value)} />
              </label>
              <label>
                Personas
                <select value={generationCount} onChange={(event) => setGenerationCount(Number(event.target.value))}>
                  <option value={6}>6-person set</option>
                  <option value={10}>10-person set</option>
                  <option value={12}>12-person set</option>
                  <option value={20}>20-person set</option>
                </select>
              </label>
              <button
                disabled={generationState === "generating" || generationLocation.trim().length === 0}
                onClick={generatePopulationPersonas}
                type="button"
              >
                {generationState === "generating" ? "Generating..." : "Generate Population"}
              </button>
              {generationResult ? (
                <div className="generation-summary">
                  <strong>{generationResult.personas.length} personas saved</strong>
                  <span>{generationResult.representation_total_pct}% represented</span>
                  <span>{generationResult.saved_path ?? "Not persisted"}</span>
                </div>
              ) : null}
            </section>

            {error ? <section className="error-banner">{error}</section> : null}

            {generationResult ? (
              <section className="panel">
                <div className="section-heading inline-heading">
                  <div>
                    <p className="eyebrow">Generated population</p>
                    <h2>Representative personas</h2>
                  </div>
                  <button type="button" onClick={() => setActiveTab("sentiment")}>
                    Analyze Sentiment
                  </button>
                </div>
                <div className="generated-persona-grid">
                  {generationResult.personas.map((persona) => (
                    <article className="generated-persona-card" key={persona.persona_id}>
                      <div>
                        <strong>{persona.name}</strong>
                        <span>{persona.representation_pct ?? 0}%</span>
                      </div>
                      <p>{persona.age} · {persona.race_ethnicity} · {persona.occupation}</p>
                      <small>{persona.segment_tags.join(", ")}</small>
                    </article>
                  ))}
                </div>
              </section>
            ) : null}
          </>
        ) : (
          <>
            <section className="hero sentiment-hero">
              <div>
                <p className="eyebrow">Dobbs preset</p>
                <h2>Run the generated population against the event.</h2>
                <p className="hero-copy">
                  Stream persona reactions, synthesize segment-level signals, and compare against the static Dobbs
                  benchmark after persona intake has saved an evidence-backed population.
                </p>
              </div>
              <aside className="status-panel">
                <span className={`status-dot ${runState}`} />
                <strong>{progressLabel}</strong>
                <p>
                  {personas.length} complete | {failedPersonas.length} failed | evidence-backed live run
                </p>
                {completion?.weave_url ? (
                  <a href={completion.weave_url} target="_blank" rel="noreferrer">
                    Open Weave trace
                  </a>
                ) : null}
              </aside>
            </section>

            <SimulationControls
              stimulusText={stimulusText}
              memoryEnabled={memoryEnabled}
              personaCount={personaCount}
              runState={runState}
              canRun={canRunSimulation}
              onStimulusTextChange={setStimulusText}
              onMemoryEnabledChange={setMemoryEnabled}
              onPersonaCountChange={setPersonaCount}
              onRun={runSimulation}
            />

            {error ? <section className="error-banner">{error}</section> : null}

            <section className="panel">
              <div className="section-heading inline-heading">
                <div>
                  <p className="eyebrow">Persona stream</p>
                  <h2>Voter voice cards</h2>
                </div>
                <label className="segment-filter">
                  Segment
                  <select value={activeSegment} onChange={(event) => setActiveSegment(event.target.value)}>
                    <option value="all">All segments</option>
                    {segmentOptions.map((segment) => (
                      <option key={segment} value={segment}>
                        {segment.replaceAll("_", " ")}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="persona-grid">
                {filteredPersonas.map((persona) => (
                  <PersonaReactionCard key={persona.persona_id} persona={persona} />
                ))}
                {filteredPersonas.length === 0 ? (
                  <p className="empty-note">
                    {personas.length === 0 ? "Persona cards will stream here." : "No personas match this segment."}
                  </p>
                ) : null}
              </div>
            </section>

            <section className="panel split">
              <div>
                <div className="section-heading">
                  <p className="eyebrow">Synthesis</p>
                  <h2>Segment signals</h2>
                </div>
                <SentimentBreakdown segments={segments} />
              </div>
              <div>
                <div className="section-heading">
                  <p className="eyebrow">Executive readout</p>
                  <h2>What moved</h2>
                </div>
                <p className="summary-copy">{synthesis?.executive_summary ?? "Awaiting synthesis output."}</p>
                {synthesis?.best_quotes.map((quote) => (
                  <blockquote className="quote-strip" key={`${quote.persona_id}-${quote.quote}`}>
                    {quote.quote}
                  </blockquote>
                ))}
                <RedFlagAlert redFlags={redFlags} />
              </div>
            </section>

            <section className="panel">
              <div className="section-heading">
                <p className="eyebrow">Calibration</p>
                <h2>Benchmark comparison</h2>
              </div>
              <BenchmarkComparison benchmark={benchmark} />
            </section>
          </>
        )}
      </section>
    </main>
  );
}
