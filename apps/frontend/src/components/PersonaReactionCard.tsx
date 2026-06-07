import type { PersonaReactionPayload } from "../lib/agui";

type Props = {
  persona: PersonaReactionPayload;
};

export function PersonaReactionCard({ persona }: Props) {
  return (
    <article className="persona-card">
      <div className="card-kicker">
        <span className={`model-badge ${persona.provider}`}>{persona.provider}</span>
        <span>{persona.latency_ms ? `${persona.latency_ms}ms` : "streamed"}</span>
      </div>
      <h3>{persona.persona_name}</h3>
      <p className="persona-meta">
        {persona.age} | {persona.location} | {persona.occupation}
      </p>
      <p>{persona.reaction_text}</p>
      <blockquote>{persona.voter_voice_quote}</blockquote>
      <div className="tag-row">
        {(persona.segment_tags ?? []).slice(0, 4).map((tag, index) => (
          <span key={`${tag}-${index}`}>{tag.replaceAll("_", " ")}</span>
        ))}
      </div>
      <footer>{persona.model_used}</footer>
    </article>
  );
}
