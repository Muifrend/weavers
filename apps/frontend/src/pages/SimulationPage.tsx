import { useDeferredValue, useMemo, useRef, useState } from "react";
import { useAgentContext, useComponent, useConfigureSuggestions, useFrontendTool } from "@copilotkit/react-core/v2";
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
import { startSimulation } from "../services/simulationClient";

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

export function SimulationPage() {
  const [stimulusText, setStimulusText] = useState(dobbsPreset.stimulus_text);
  const [memoryEnabled, setMemoryEnabled] = useState(false);
  const [personaCount, setPersonaCount] = useState(20);
  const [useMockMode, setUseMockMode] = useState(import.meta.env.VITE_USE_MOCK_SIMULATION === "true");
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
  const [copiedPromptTitle, setCopiedPromptTitle] = useState<string | null>(null);
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

  const copilotPrompts = useMemo(() => {
    const topPersona = personas[0]?.persona_name ?? "the first completed persona";
    const activeFilterLabel = activeSegment === "all" ? "all segments" : activeSegment.replaceAll("_", " ");

    return [
      {
        title: "Executive readout",
        message:
          "Summarize the current simulation in five bullets: overall sentiment, moved segments, strongest quotes, red flags, and benchmark fit."
      },
      {
        title: "Persona deep dive",
        message: `Explain ${topPersona}'s reaction, what values are driving it, and what campaign risk it signals.`
      },
      {
        title: "Red flags",
        message: "Show the red flags in the current run and rank them by campaign urgency."
      },
      {
        title: "Benchmark fit",
        message: "Explain how this simulation compares with the Dobbs benchmark and where it may be over- or under-reading sentiment."
      },
      {
        title: "Segment lens",
        message: `Filter the persona grid to ${activeFilterLabel === "all segments" ? "suburban_women" : activeFilterLabel} and summarize what that segment is saying.`
      }
    ];
  }, [activeSegment, personas]);

  useConfigureSuggestions(
    {
      suggestions: copilotPrompts,
      available: "always"
    },
    [copilotPrompts]
  );

  useAgentContext({
    description:
      "Current state of the campaign persona simulator UI. Use this to answer questions about personas, red flags, sentiment, benchmark, filters, and run status.",
    value: {
      stimulusText,
      preset: dobbsPreset.event_name,
      memoryEnabled,
      runState,
      useMockMode,
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
        controller.signal,
        { useMockSimulation: useMockMode }
      );
    } catch (caught) {
      if (!controller.signal.aborted) {
        setError(caught instanceof Error ? caught.message : "Simulation failed.");
        setRunState("failed");
      }
    }
  }

  async function copyCopilotPrompt(title: string, message: string) {
    try {
      await navigator.clipboard.writeText(message);
      setCopiedPromptTitle(title);
      window.setTimeout(() => setCopiedPromptTitle(null), 1600);
    } catch {
      setCopiedPromptTitle(null);
    }
  }

  return (
    <main className="simulation-app">
      <section className="hero">
        <div>
          <p className="eyebrow">Synthetic voter focus group</p>
          <h1>Directional reaction signal in seconds.</h1>
          <p className="hero-copy">
            Run 20 multi-model personas against the Dobbs preset, stream voter voice cards,
            synthesize segment-level signals, and compare against static benchmark data.
          </p>
        </div>
        <aside className="status-panel">
          <span className={`status-dot ${runState}`} />
          <strong>{progressLabel}</strong>
          <p>
            {personas.length} complete | {failedPersonas.length} failed | {useMockMode ? "mock" : "live"}
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
        useMockMode={useMockMode}
        onStimulusTextChange={setStimulusText}
        onMemoryEnabledChange={setMemoryEnabled}
        onPersonaCountChange={setPersonaCount}
        onUseMockModeChange={setUseMockMode}
        onRun={runSimulation}
      />

      <section className="copilot-command-center">
        <div className="copilot-command-copy">
          <p className="eyebrow">Copilot layer</p>
          <h2>Ask against the live run state.</h2>
          <p>
            The assistant can see streamed persona cards, active segment filters, synthesis,
            red flags, benchmark results, memory mode, and mock/live status.
          </p>
        </div>
        <div className="copilot-context-grid" aria-label="Copilot context summary">
          <div>
            <span>Runtime</span>
            <strong>Sidebar ready</strong>
          </div>
          <div>
            <span>Persona context</span>
            <strong>{personas.length}/{personaCount}</strong>
          </div>
          <div>
            <span>Active segment</span>
            <strong>{activeSegment === "all" ? "All" : activeSegment.replaceAll("_", " ")}</strong>
          </div>
          <div>
            <span>Memory</span>
            <strong>{memoryEnabled ? "Enabled" : "Disabled"}</strong>
          </div>
        </div>
        <div className="copilot-prompt-rail" aria-label="Suggested Copilot prompts">
          {copilotPrompts.map((prompt) => (
            <button
              key={prompt.title}
              type="button"
              title={prompt.message}
              onClick={() => void copyCopilotPrompt(prompt.title, prompt.message)}
            >
              {copiedPromptTitle === prompt.title ? "Copied" : prompt.title}
            </button>
          ))}
        </div>
      </section>

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
    </main>
  );
}
