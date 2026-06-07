import type { ModelProvider } from "../services/simulationClient";

export type ModelConfig = {
  enabled: Record<string, boolean>;
  models: Record<string, string>;
};

type Props = {
  providers: ModelProvider[];
  config: ModelConfig;
  onToggle: (providerId: string, enabled: boolean) => void;
  onModelChange: (providerId: string, model: string) => void;
};

export function SettingsPanel({ providers, config, onToggle, onModelChange }: Props) {
  const enabledCount = providers.filter((provider) => config.enabled[provider.id]).length;

  return (
    <>
      <section className="panel">
        <div className="section-heading">
          <p className="eyebrow">Models</p>
          <h2>Choose which models run</h2>
          <p className="summary-copy">
            Pick the providers personas are routed across during a sentiment run. Enabled models are used
            round-robin; you can override the exact model id per provider. Greyed-out providers are missing an
            API key on the backend.
          </p>
        </div>

        {providers.length === 0 ? (
          <p className="empty-note">No providers reported by the backend.</p>
        ) : (
          <div className="model-list">
            {providers.map((provider) => {
              const enabled = Boolean(config.enabled[provider.id]);
              return (
                <article
                  key={provider.id}
                  className={`model-row ${enabled ? "enabled" : ""} ${provider.configured ? "" : "unconfigured"}`}
                >
                  <label className="model-toggle">
                    <input
                      type="checkbox"
                      checked={enabled}
                      disabled={!provider.configured}
                      onChange={(event) => onToggle(provider.id, event.target.checked)}
                    />
                    <span className="model-name">{provider.id}</span>
                    {provider.configured ? null : <span className="model-flag">no key</span>}
                  </label>
                  <input
                    className="wv-input model-id"
                    value={config.models[provider.id] ?? provider.default_model}
                    placeholder={provider.default_model}
                    disabled={!provider.configured}
                    onChange={(event) => onModelChange(provider.id, event.target.value)}
                  />
                </article>
              );
            })}
          </div>
        )}
      </section>

      <p className="settings-footnote">
        {enabledCount === 0
          ? "No models enabled — runs fall back to the backend default (OpenAI)."
          : `${enabledCount} model${enabledCount === 1 ? "" : "s"} enabled. Saved automatically on this device.`}
      </p>
    </>
  );
}
