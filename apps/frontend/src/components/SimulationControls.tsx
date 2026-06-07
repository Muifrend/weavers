import { useRef, useState } from "react";
import type { ClipboardEvent } from "react";
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

type Attachment = { id: string; name: string; kind: "image" | "file"; url?: string };

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
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  function addFiles(files: File[]) {
    const next = files.map((file) => {
      const isImage = file.type.startsWith("image/");
      return {
        id: `${file.name}-${file.size}-${Math.random().toString(36).slice(2)}`,
        name: file.name,
        kind: isImage ? ("image" as const) : ("file" as const),
        url: isImage ? URL.createObjectURL(file) : undefined
      };
    });
    setAttachments((current) => [...current, ...next]);
  }

  function removeAttachment(id: string) {
    setAttachments((current) => {
      const target = current.find((item) => item.id === id);
      if (target?.url) URL.revokeObjectURL(target.url);
      return current.filter((item) => item.id !== id);
    });
  }

  function handlePaste(event: ClipboardEvent<HTMLTextAreaElement>) {
    const pasted = Array.from(event.clipboardData?.items ?? [])
      .filter((item) => item.kind === "file")
      .map((item) => item.getAsFile())
      .filter((file): file is File => file !== null);
    if (pasted.length > 0) addFiles(pasted);
  }

  return (
    <section className="run-panel panel">
      <label className="run-prompt">
        Your prompt
        <textarea
          value={stimulusText}
          onChange={(event) => onStimulusTextChange(event.target.value)}
          onPaste={handlePaste}
          placeholder="Paste the statement, ad, or event the personas should react to… you can also paste or attach an image."
        />
      </label>

      {attachments.length > 0 ? (
        <div className="attachment-row">
          {attachments.map((attachment) => (
            <div className="attachment" key={attachment.id}>
              {attachment.kind === "image" && attachment.url ? (
                <img src={attachment.url} alt={attachment.name} />
              ) : (
                <span className="attachment-file">{attachment.name}</span>
              )}
              <button
                type="button"
                className="attachment-remove"
                onClick={() => removeAttachment(attachment.id)}
                aria-label={`Remove ${attachment.name}`}
              >
                ×
              </button>
            </div>
          ))}
        </div>
      ) : null}

      <div className="run-actions">
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          multiple
          hidden
          onChange={(event) => {
            if (event.target.files) addFiles(Array.from(event.target.files));
            event.target.value = "";
          }}
        />
        <button
          type="button"
          className="wv-button--ghost attach-button"
          onClick={() => fileInputRef.current?.click()}
        >
          📎 Attach image
        </button>
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
