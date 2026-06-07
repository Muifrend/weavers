import type { RunState } from "../lib/agui";

type Props = {
  stimulusText: string;
  memoryEnabled: boolean;
  runState: RunState;
  canRun: boolean;
  onStimulusTextChange: (value: string) => void;
  onMemoryEnabledChange: (value: boolean) => void;
  onRun: () => void;
};

export function SimulationControls({
  stimulusText,
  memoryEnabled,
  runState,
  canRun,
  onStimulusTextChange,
  onMemoryEnabledChange,
  onRun
}: Props) {
  const isRunning = !["idle", "completed", "failed"].includes(runState);

  return (
    <section className="run-panel panel">
      <label className="run-prompt">
        Your prompt
        <textarea
          value={stimulusText}
          onChange={(event) => onStimulusTextChange(event.target.value)}
          placeholder="Paste the statement, ad, or event the personas should react to…"
        />
      </label>
      <div className="run-actions">
        <label className="toggle">
          <input
            checked={memoryEnabled}
            onChange={(event) => onMemoryEnabledChange(event.target.checked)}
            type="checkbox"
          />
          Memory {memoryEnabled ? "ON" : "OFF"}
        </label>
        <button disabled={isRunning || !canRun || stimulusText.trim().length === 0} onClick={onRun}>
          {isRunning ? "Running…" : "Run analysis"}
        </button>
      </div>
    </section>
  );
}
