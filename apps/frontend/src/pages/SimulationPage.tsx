import { useCallback, useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import { useAgentContext, useComponent, useFrontendTool } from "@copilotkit/react-core/v2";
import { z } from "zod";
import { BenchmarkComparison } from "../components/BenchmarkComparison";
import { PersonaReactionCard } from "../components/PersonaReactionCard";
import { RedFlagAlert } from "../components/RedFlagAlert";
import { SentimentBreakdown } from "../components/SentimentBreakdown";
import { SimulationControls } from "../components/SimulationControls";
import { SettingsPanel, type ModelConfig } from "../components/SettingsPanel";
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
import {
  generatePersonasForState,
  listModels,
  listPersonaSets,
  startSimulation,
  type ModelProvider,
  type PersonaGenerationResponse,
  type PersonaSetSummary
} from "../services/simulationClient";

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

const personaSetSchema = z.object({
  set_id: z.string(),
  label: z.string(),
  location: z.string(),
  persona_count: z.number(),
  representation_total_pct: z.number().optional()
});

type ActiveTab = "intake" | "sentiment" | "settings" | "data";

const MODEL_CONFIG_STORAGE_KEY = "weavers.modelConfig";

function loadModelConfig(): ModelConfig {
  try {
    const raw = localStorage.getItem(MODEL_CONFIG_STORAGE_KEY);
    if (raw) return JSON.parse(raw) as ModelConfig;
  } catch {
    // ignore malformed storage
  }
  return { enabled: {}, models: {} };
}

export function SimulationPage() {
  const [stimulusText, setStimulusText] = useState(dobbsPreset.stimulus_text);
  const [memoryEnabled, setMemoryEnabled] = useState(false);
  const [activeTab, setActiveTab] = useState<ActiveTab>("intake");
  const [demoMode, setDemoMode] = useState(() => {
    try {
      return localStorage.getItem("weavers.demoMode") === "true";
    } catch {
      return false;
    }
  });

  // Tab 1 — generation
  const [generationLocation, setGenerationLocation] = useState("California");
  const [generationCount, setGenerationCount] = useState(12);
  const [generationLabel, setGenerationLabel] = useState("");
  const [generationState, setGenerationState] = useState<"idle" | "generating" | "completed" | "failed">("idle");
  const [generationResult, setGenerationResult] = useState<PersonaGenerationResponse | null>(null);

  // Persona sets (shared)
  const [personaSets, setPersonaSets] = useState<PersonaSetSummary[]>([]);
  const [selectedSetId, setSelectedSetId] = useState<string | null>(null);

  // Settings — model configuration
  const [modelProviders, setModelProviders] = useState<ModelProvider[]>([]);
  const [modelConfig, setModelConfig] = useState<ModelConfig>(loadModelConfig);

  // Tab 2 — run
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

  const selectedSet = useMemo(
    () => personaSets.find((set) => set.set_id === selectedSetId) ?? null,
    [personaSets, selectedSetId]
  );
  const targetCount = selectedSet?.persona_count ?? 0;

  const refreshPersonaSets = useCallback(async () => {
    try {
      const sets = await listPersonaSets();
      setPersonaSets(sets);
      return sets;
    } catch (caught) {
      console.warn("Failed to load persona sets", caught);
      return [] as PersonaSetSummary[];
    }
  }, []);

  useEffect(() => {
    void refreshPersonaSets();
  }, [refreshPersonaSets]);

  // Load the provider catalog and backfill sensible defaults (OpenAI on, matching the backend).
  useEffect(() => {
    listModels()
      .then((providers) => {
        setModelProviders(providers);
        setModelConfig((prev) => {
          const enabled = { ...prev.enabled };
          const models = { ...prev.models };
          for (const provider of providers) {
            if (!(provider.id in enabled)) enabled[provider.id] = provider.configured && provider.id === "openai";
            if (!(provider.id in models)) models[provider.id] = provider.default_model;
          }
          return { enabled, models };
        });
      })
      .catch((caught) => console.warn("Failed to load models", caught));
  }, []);

  useEffect(() => {
    try {
      localStorage.setItem(MODEL_CONFIG_STORAGE_KEY, JSON.stringify(modelConfig));
    } catch {
      // ignore storage failures
    }
  }, [modelConfig]);

  useEffect(() => {
    try {
      localStorage.setItem("weavers.demoMode", String(demoMode));
    } catch {
      // ignore storage failures
    }
  }, [demoMode]);

  const enabledProviders = useMemo(
    () => modelProviders.filter((provider) => modelConfig.enabled[provider.id]).map((provider) => provider.id),
    [modelProviders, modelConfig]
  );

  const providerModels = useMemo(() => {
    const out: Record<string, string> = {};
    for (const provider of modelProviders) {
      if (!modelConfig.enabled[provider.id]) continue;
      const model = (modelConfig.models[provider.id] ?? "").trim();
      if (model) out[provider.id] = model;
    }
    return out;
  }, [modelProviders, modelConfig]);

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
    if (runState === "streaming_personas") return `Streaming personas: ${personas.length}/${targetCount}`;
    if (runState === "synthesizing") return "Synthesizing segment signals";
    if (runState === "benchmarking") return "Comparing against Dobbs benchmark";
    if (runState === "completed") return "Run complete";
    return "Run failed";
  }, [personas.length, runState, targetCount]);

  const generationStatusLabel = useMemo(() => {
    if (generationState === "generating") return "Generating population";
    if (generationState === "completed") return `${generationResult?.personas.length ?? 0} personas ready`;
    if (generationState === "failed") return "Generation failed";
    return "Ready to generate";
  }, [generationResult?.personas.length, generationState]);

  const headerTitle =
    activeTab === "intake"
      ? "Generate Personas"
      : activeTab === "sentiment"
        ? "Sentiment Analysis"
        : activeTab === "data"
          ? "Named Data"
          : "Settings";
  const headerStatus = activeTab === "intake" ? generationStatusLabel : activeTab === "sentiment" ? progressLabel : null;
  const headerStatusState = activeTab === "intake" ? generationState : runState;

  const canRunSimulation = selectedSetId !== null;

  useAgentContext({
    description:
      "Current state of the campaign persona simulator UI. Use this to answer questions about persona sets, personas, red flags, sentiment, benchmark, filters, model selection, and run status.",
    value: {
      stimulusText,
      preset: dobbsPreset.event_name,
      activeTab,
      memoryEnabled,
      enabledProviders,
      generationState,
      generationLocation,
      generationCount,
      generatedPersonaCount: generationResult?.personas.length ?? 0,
      personaSets: personaSets.map((set) => ({
        setId: set.set_id,
        label: set.label,
        location: set.location,
        personaCount: set.persona_count
      })),
      selectedSetId,
      selectedSetLabel: selectedSet?.label ?? null,
      runState,
      activeSegment,
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

  const runSimulationForSet = useCallback(
    async (setId: string | null) => {
      if (!setId) {
        setError("Choose a persona set before running the analysis.");
        return;
      }
      const set = personaSets.find((item) => item.set_id === setId) ?? null;
      const count = set ? set.persona_count : 20;

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
            persona_count: count,
            persona_set_id: setId,
            providers: enabledProviders.length > 0 ? enabledProviders : undefined,
            provider_models: Object.keys(providerModels).length > 0 ? providerModels : undefined,
            skip_benchmark: demoMode
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
    },
    [demoMode, enabledProviders, memoryEnabled, personaSets, providerModels, stimulusText]
  );

  const runGeneration = useCallback(
    async (location: string, count: number, label?: string) => {
      setGenerationState("generating");
      setGenerationResult(null);
      setError(null);
      try {
        const result = await generatePersonasForState(location, count, label);
        setGenerationResult(result);
        setGenerationState("completed");
        await refreshPersonaSets();
        if (result.set_id) setSelectedSetId(result.set_id);
        return result;
      } catch (caught) {
        setGenerationState("failed");
        const message = caught instanceof Error ? caught.message : "Persona generation failed.";
        setError(message);
        throw caught;
      }
    },
    [refreshPersonaSets]
  );

  function generatePopulationPersonas() {
    void runGeneration(generationLocation, generationCount, generationLabel);
  }

  const toggleProvider = useCallback((providerId: string, enabled: boolean) => {
    setModelConfig((config) => ({ ...config, enabled: { ...config.enabled, [providerId]: enabled } }));
  }, []);

  const changeModel = useCallback((providerId: string, model: string) => {
    setModelConfig((config) => ({ ...config, models: { ...config.models, [providerId]: model } }));
  }, []);

  // --------------------------------------------------------------------------
  // Copilot — frontend tools (action-driving)
  // --------------------------------------------------------------------------
  useFrontendTool(
    {
      name: "switchWorkspaceTab",
      description: "Switch between the generate personas, sentiment analysis, named data, and settings tabs.",
      parameters: z.object({ tab: z.enum(["intake", "sentiment", "data", "settings"]) }),
      handler: async ({ tab }) => {
        setActiveTab(tab);
        const names: Record<ActiveTab, string> = {
          intake: "Generate Personas",
          sentiment: "Sentiment Analysis",
          data: "Named Data",
          settings: "Settings"
        };
        return `Switched to ${names[tab]}.`;
      }
    },
    []
  );

  useFrontendTool(
    {
      name: "generatePersonaSet",
      description:
        "Generate a new evidence-backed persona set for a US state. Choose how many personas to create.",
      parameters: z.object({
        location: z.string().describe("US state or location, e.g. 'California'"),
        count: z.number().int().min(1).max(100).describe("How many personas to generate"),
        label: z.string().optional().describe("Optional name for the set")
      }),
      handler: async ({ location, count, label }) => {
        setActiveTab("intake");
        setGenerationLocation(location);
        setGenerationCount(count);
        if (label) setGenerationLabel(label);
        try {
          const result = await runGeneration(location, count, label);
          return `Generated and saved "${result.set_label ?? location}" with ${result.personas.length} personas. It is now selected for sentiment analysis.`;
        } catch (caught) {
          return `Persona generation failed: ${caught instanceof Error ? caught.message : "unknown error"}.`;
        }
      }
    },
    [runGeneration]
  );

  useFrontendTool(
    {
      name: "listAvailablePersonaSets",
      description: "List the saved persona sets that can be used for sentiment analysis.",
      handler: async () => {
        const sets = await refreshPersonaSets();
        if (sets.length === 0) return "No persona sets are saved yet. Generate one first.";
        return sets
          .map((set) => `${set.label} — ${set.location}, ${set.persona_count} personas (id: ${set.set_id})`)
          .join("\n");
      }
    },
    [refreshPersonaSets]
  );

  useFrontendTool(
    {
      name: "selectPersonaSet",
      description: "Select which saved persona set to use for sentiment analysis, by id or label.",
      parameters: z.object({ setIdOrLabel: z.string() }),
      handler: async ({ setIdOrLabel }) => {
        const needle = setIdOrLabel.trim().toLowerCase();
        const match = personaSets.find(
          (set) => set.set_id.toLowerCase() === needle || set.label.toLowerCase() === needle
        );
        if (!match) return `No persona set matches "${setIdOrLabel}".`;
        setSelectedSetId(match.set_id);
        setActiveTab("sentiment");
        return `Selected "${match.label}" (${match.persona_count} personas) for analysis.`;
      }
    },
    [personaSets]
  );

  useFrontendTool(
    {
      name: "runSentimentAnalysis",
      description: "Run the Dobbs sentiment analysis against the currently selected persona set.",
      handler: async () => {
        if (!selectedSetId) return "Select a persona set first, then I can run the analysis.";
        setActiveTab("sentiment");
        void runSimulationForSet(selectedSetId);
        return `Started the sentiment run against "${selectedSet?.label ?? selectedSetId}".`;
      }
    },
    [runSimulationForSet, selectedSet?.label, selectedSetId]
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

  // --------------------------------------------------------------------------
  // Copilot — generative components
  // --------------------------------------------------------------------------
  useComponent(
    {
      name: "showGenerationProgress",
      description: "Show a live progress card while a persona set is being generated.",
      parameters: z.object({ label: z.string().optional(), count: z.number().optional() }),
      render: ({ label, count }) => (
        <div className="generation-progress">
          <span className="spinner" />
          <span className="track" />
          <strong>
            Building {count ?? ""} personas{label ? ` · ${label}` : ""}
          </strong>
        </div>
      )
    },
    []
  );

  useComponent(
    {
      name: "showPersonaSetSummary",
      description: "Render a summary card for a saved persona set in the chat.",
      parameters: personaSetSchema,
      render: (set) => (
        <article className="persona-set-summary-card">
          <strong>{set.label}</strong>
          <span className="set-meta">
            {set.location} · {set.persona_count} personas
            {set.representation_total_pct ? ` · ${set.representation_total_pct}% represented` : ""}
          </span>
        </article>
      )
    },
    []
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
            Generate Personas
          </button>
          <button
            className={activeTab === "sentiment" ? "active" : ""}
            onClick={() => setActiveTab("sentiment")}
            type="button"
          >
            Sentiment Analysis
          </button>
          <button
            className={activeTab === "data" ? "active" : ""}
            onClick={() => setActiveTab("data")}
            type="button"
          >
            Named Data
          </button>
          <button
            className={activeTab === "settings" ? "active" : ""}
            onClick={() => setActiveTab("settings")}
            type="button"
          >
            Settings
          </button>
        </nav>
        <div className="service-list">
          <span>AI services</span>
          <p>Redis Agent Memory</p>
          <p>Weave traces</p>
          <p>CopilotKit</p>
        </div>
        <div className="sidebar-footer">
          <button
            type="button"
            className={`demo-toggle ${demoMode ? "on" : ""}`}
            onClick={() => setDemoMode((value) => !value)}
            aria-pressed={demoMode}
            title="Demo mode skips the hard-coded benchmark comparison"
          >
            <span className="demo-dot" />
            Demo mode {demoMode ? "ON" : "OFF"}
          </button>
        </div>
      </aside>

      <section className="weavers-main simulation-app">
        <header className="workspace-header">
          <p className="eyebrow">Synthetic voter focus group</p>
          <h1>{headerTitle}</h1>
          {headerStatus ? (
            <span className="header-status">
              <span className={`status-dot ${headerStatusState}`} />
              {headerStatus}
            </span>
          ) : null}
        </header>

        {activeTab === "intake" ? (
          <>
            <section className="persona-generator-panel">
              <div>
                <p className="eyebrow">Census persona generator</p>
                <h2>Build a representative population</h2>
                <p className="generator-copy">
                  Choose a state and how many personas to create. We fetch ACS Census priors, draw weighted
                  local PUMS samples, and save the result as a reusable persona set you can analyze next.
                </p>
              </div>
              <label>
                State
                <input
                  value={generationLocation}
                  onChange={(event) => setGenerationLocation(event.target.value)}
                  placeholder="California"
                />
              </label>
              <label>
                How many
                <input
                  className="wv-number"
                  type="number"
                  min={1}
                  max={100}
                  value={generationCount}
                  onChange={(event) => setGenerationCount(Math.max(1, Math.min(100, Number(event.target.value) || 1)))}
                />
              </label>
              <label>
                Set name (optional)
                <input
                  value={generationLabel}
                  onChange={(event) => setGenerationLabel(event.target.value)}
                  placeholder={`${generationLocation || "State"} · ${generationCount}`}
                />
              </label>
              <button
                disabled={generationState === "generating" || generationLocation.trim().length === 0}
                onClick={generatePopulationPersonas}
                type="button"
              >
                {generationState === "generating" ? "Generating..." : "Generate Personas"}
              </button>
              {generationState === "generating" ? (
                <div className="generation-progress">
                  <span className="spinner" />
                  <span className="track" />
                  <strong>Drawing {generationCount} evidence-backed personas…</strong>
                </div>
              ) : null}
              {generationResult ? (
                <div className="generation-summary">
                  <strong>{generationResult.set_label ?? `${generationResult.personas.length} personas`}</strong>
                  <span>{generationResult.personas.length} personas saved</span>
                  <span>{generationResult.representation_total_pct}% represented</span>
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
                    Continue to Sentiment →
                  </button>
                </div>
                <div className="generated-persona-grid">
                  {generationResult.personas.map((persona) => (
                    <article className="generated-persona-card" key={persona.persona_id}>
                      <div>
                        <strong>{persona.name}</strong>
                        <span>{persona.representation_pct ?? 0}%</span>
                      </div>
                      <p>
                        {persona.age} · {persona.race_ethnicity} · {persona.occupation}
                      </p>
                      <small>{persona.segment_tags.join(", ")}</small>
                    </article>
                  ))}
                </div>
              </section>
            ) : null}
          </>
        ) : activeTab === "settings" ? (
          <SettingsPanel
            providers={modelProviders}
            config={modelConfig}
            onToggle={toggleProvider}
            onModelChange={changeModel}
          />
        ) : activeTab === "data" ? (
          <>
            <section className="panel">
              <div className="section-heading">
                <p className="eyebrow">Named data</p>
                <h2>Add reference datasets</h2>
                <p className="summary-copy">
                  Attach polling files, voter rolls, or survey exports and give each one a name, so personas
                  and the copilot can ground their reactions in your own data.
                </p>
              </div>

              <label className="wv-field data-name">
                Dataset name
                <input className="wv-input" placeholder="e.g. Ohio 2024 turnout model" />
              </label>

              <div className="dropzone" role="button" tabIndex={0}>
                <span className="dropzone-icon" aria-hidden="true">
                  ↑
                </span>
                <strong>Drag &amp; drop files here</strong>
                <span className="dropzone-or">or</span>
                <span className="dropzone-browse">Browse files</span>
                <small>CSV, XLSX, JSON, or PDF · up to 25&nbsp;MB</small>
              </div>

              <div className="data-actions">
                <span className="settings-footnote">Preview only — uploads aren’t connected yet.</span>
                <button type="button" className="wv-button">
                  Add dataset
                </button>
              </div>
            </section>

            <section className="panel">
              <div className="section-heading">
                <p className="eyebrow">Library</p>
                <h2>Named datasets</h2>
              </div>
              <div className="data-library-empty">
                <span className="dropzone-icon" aria-hidden="true">
                  ⌫
                </span>
                <p className="empty-note">No datasets yet. Files you add will appear here.</p>
              </div>
            </section>
          </>
        ) : (
          <>
            <section className="panel">
              <div className="section-heading">
                <p className="eyebrow">Persona set</p>
                <h2>Choose a set</h2>
              </div>
              {personaSets.length === 0 ? (
                <p className="set-empty">
                  No persona sets yet. Generate one on the <strong>Generate Personas</strong> tab first.
                </p>
              ) : (
                <div className="set-grid">
                  {personaSets.map((set) => (
                    <button
                      key={set.set_id}
                      type="button"
                      className={`set-option ${selectedSetId === set.set_id ? "selected" : ""}`}
                      onClick={() => setSelectedSetId(set.set_id)}
                      aria-pressed={selectedSetId === set.set_id}
                    >
                      <span className="set-check" aria-hidden="true" />
                      <strong>{set.label}</strong>
                      <span className="set-meta">
                        {set.location} · {set.persona_count} personas
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </section>

            <SimulationControls
              stimulusText={stimulusText}
              memoryEnabled={memoryEnabled}
              runState={runState}
              canRun={canRunSimulation}
              onStimulusTextChange={setStimulusText}
              onMemoryEnabledChange={setMemoryEnabled}
              onRun={() => runSimulationForSet(selectedSetId)}
            />

            {error ? <section className="error-banner">{error}</section> : null}

            {runState !== "idle" || personas.length > 0 ? (
              <>
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

                {demoMode ? null : (
                  <section className="panel">
                    <div className="section-heading">
                      <p className="eyebrow">Calibration</p>
                      <h2>Benchmark comparison</h2>
                    </div>
                    <BenchmarkComparison benchmark={benchmark} />
                  </section>
                )}
              </>
            ) : null}
          </>
        )}
      </section>
    </main>
  );
}
