import type { EventEnvelope } from "../lib/agui";

export type SimulationRequest = {
  stimulus_id: string;
  stimulus_text: string;
  memory_enabled: boolean;
  persona_count: number;
  persona_set_id?: string;
  providers?: string[];
  provider_models?: Record<string, string>;
  skip_benchmark?: boolean;
};

export type ModelProvider = {
  id: string;
  default_model: string;
  configured: boolean;
};

export type SimulationEventHandlers = {
  onEvent: (event: EventEnvelope) => void;
  onError?: (error: Error) => void;
  onDone?: () => void;
};

export type GeneratedPersonaSummary = {
  persona_id: string;
  name: string;
  age: number;
  race_ethnicity: string;
  occupation: string;
  representation_pct?: number;
  segment_tags: string[];
};

export type PersonaGenerationResponse = {
  status: string;
  location: string;
  personas: GeneratedPersonaSummary[];
  representation_total_pct: number;
  saved_path?: string;
  set_id?: string;
  set_label?: string;
  warnings: string[];
};

export type PersonaSetSummary = {
  set_id: string;
  label: string;
  location: string;
  persona_count: number;
  created_at: number;
  representation_total_pct: number;
};

function resolveApiUrl() {
  return (import.meta.env.VITE_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
}

export async function listModels(): Promise<ModelProvider[]> {
  const response = await fetch(`${resolveApiUrl()}/api/models`);
  if (!response.ok) {
    throw new Error(`Failed to load models (HTTP ${response.status})`);
  }
  const payload = await response.json();
  return (payload?.providers ?? []) as ModelProvider[];
}

export async function listPersonaSets(): Promise<PersonaSetSummary[]> {
  const response = await fetch(`${resolveApiUrl()}/api/persona-sets`);
  if (!response.ok) {
    throw new Error(`Failed to load persona sets (HTTP ${response.status})`);
  }
  const payload = await response.json();
  return (payload?.sets ?? []) as PersonaSetSummary[];
}

export async function startSimulation(
  request: SimulationRequest,
  handlers: SimulationEventHandlers,
  signal?: AbortSignal
) {
  await streamLiveSimulation(request, handlers, signal);
}

export async function subscribeToSimulationEvents(
  request: SimulationRequest,
  handlers: SimulationEventHandlers,
  signal?: AbortSignal
) {
  await startSimulation(request, handlers, signal);
}

export async function generatePersonasForState(location: string, personaCount: number, setLabel?: string) {
  const apiUrl = resolveApiUrl();
  const response = await fetch(`${apiUrl}/api/personas/generate`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      location,
      persona_count: personaCount,
      persist: true,
      set_label: setLabel && setLabel.trim().length > 0 ? setLabel.trim() : null
    })
  });

  const payload = await response.json();
  if (!response.ok) {
    const message = payload?.detail?.message ?? `Persona generation failed with HTTP ${response.status}`;
    throw new Error(message);
  }
  return payload as PersonaGenerationResponse;
}

async function streamLiveSimulation(
  request: SimulationRequest,
  handlers: SimulationEventHandlers,
  signal?: AbortSignal
) {
  const apiUrl = (import.meta.env.VITE_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
  const response = await fetch(`${apiUrl}/api/runs`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream"
    },
    body: JSON.stringify(request),
    signal
  });

  if (!response.ok || !response.body) {
    throw new Error(`Run request failed with HTTP ${response.status}`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const blocks = buffer.split("\n\n");
      buffer = blocks.pop() ?? "";
      for (const block of blocks) {
        const event = parseSseBlock(block);
        if (event) handlers.onEvent(event);
      }
    }

    const tail = parseSseBlock(buffer);
    if (tail) handlers.onEvent(tail);
    handlers.onDone?.();
  } catch (error) {
    if (!signal?.aborted) {
      handlers.onError?.(error instanceof Error ? error : new Error("Live simulation stream failed."));
    }
  }
}

function parseSseBlock(block: string): EventEnvelope | null {
  const dataLines = block
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice("data:".length).trim());

  if (dataLines.length === 0) return null;
  return JSON.parse(dataLines.join("\n")) as EventEnvelope;
}
