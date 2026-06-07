import type { SynthesisSegmentPayload } from "../lib/agui";
import { SegmentInsightCard } from "./SegmentInsightCard";

type Props = {
  segments?: SynthesisSegmentPayload[];
};

export function SentimentBreakdown({ segments }: Props) {
  const items = Array.isArray(segments) ? segments : [];

  if (items.length === 0) {
    return <p className="empty-note">Segment synthesis will appear after persona reactions finish.</p>;
  }

  const counts = items.reduce(
    (acc, segment) => {
      const rawDirection = segment?.sentiment_direction ?? "";
      const direction = rawDirection.includes("positive")
        ? "positive"
        : rawDirection.includes("negative")
          ? "negative"
          : "mixed";
      acc[direction] += segment?.persona_count ?? 0;
      return acc;
    },
    { positive: 0, negative: 0, mixed: 0 }
  );
  const total = Math.max(1, counts.positive + counts.negative + counts.mixed);

  return (
    <div className="sentiment-block">
      <div className="sentiment-bars" aria-label="Sentiment breakdown">
        <span className="sentiment-bar negative" style={{ width: `${(counts.negative / total) * 100}%` }} />
        <span className="sentiment-bar mixed" style={{ width: `${(counts.mixed / total) * 100}%` }} />
        <span className="sentiment-bar positive" style={{ width: `${(counts.positive / total) * 100}%` }} />
      </div>
      <div className="sentiment-legend">
        <span>Negative {counts.negative}</span>
        <span>Mixed {counts.mixed}</span>
        <span>Positive {counts.positive}</span>
      </div>
      <div className="segment-list">
        {items.map((segment, index) => (
          <SegmentInsightCard key={`${segment?.segment_id ?? "segment"}-${index}`} segment={segment} />
        ))}
      </div>
    </div>
  );
}
