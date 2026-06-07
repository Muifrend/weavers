import type { SynthesisSegmentPayload } from "../lib/agui";

type Props = {
  segment?: SynthesisSegmentPayload;
};

export function SegmentInsightCard({ segment }: Props) {
  if (!segment) return null;

  const sentiment = segment.sentiment_direction ?? "mixed";
  const movement = segment.movement_signal ?? "unclear";

  return (
    <article className={`segment-card sentiment-${sentiment}`}>
      <div className="segment-card-header">
        <span className="pill">{sentiment.replaceAll("_", " ")}</span>
        <span className="pill ghost">{movement.replaceAll("_", " ")}</span>
      </div>
      <h3>{segment.segment_name ?? "Segment"}</h3>
      <p>{segment.summary ?? ""}</p>
      <small>{segment.persona_count ?? 0} persona(s)</small>
    </article>
  );
}
