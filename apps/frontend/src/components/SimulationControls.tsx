import type { RunState } from "../lib/agui";

type Props = {
  stimulusText: string;
  memoryEnabled: boolean;
  personaCount: number;
  runState: RunState;
  canRun: boolean;
  onStimulusTextChange: (value: string) => void;
  onMemoryEnabledChange: (value: boolean) => void;
  onPersonaCountChange: (value: number) => void;
  onRun: () => void;
};

export function SimulationControls({
  stimulusText,
  memoryEnabled,
  personaCount,
  runState,
  canRun,
  onStimulusTextChange,
  onMemoryEnabledChange,
  onPersonaCountChange,
  onRun
}: Props) {
  const isRunning = !["idle", "completed", "failed"].includes(runState);
  const personaOptions = Array.from(new Set([3, 6, 10, 12, 20, personaCount])).sort((left, right) => left - right);

  return (
    <section className="control-deck">
      <label>
        Event preset
        <select value="dobbs_2022" disabled>
          <option value="dobbs_2022">Dobbs v. Jackson, June 2022</option>
        </select>
      </label>
      <label className="wide">
        Stimulus text
        <textarea value={stimulusText} onChange={(event) => onStimulusTextChange(event.target.value)} />
      </label>
      <label>
        Personas
        <select value={personaCount} onChange={(event) => onPersonaCountChange(Number(event.target.value))}>
          {personaOptions.map((option) => (
            <option key={option} value={option}>
              {option}-person run
            </option>
          ))}
        </select>
      </label>
      <label className="toggle">
        <input
          checked={memoryEnabled}
          onChange={(event) => onMemoryEnabledChange(event.target.checked)}
          type="checkbox"
        />
        Memory {memoryEnabled ? "ON" : "OFF"}
      </label>
      <button disabled={isRunning || !canRun || stimulusText.trim().length === 0} onClick={onRun}>
        Run Simulation
      </button>
    </section>
  );
}
