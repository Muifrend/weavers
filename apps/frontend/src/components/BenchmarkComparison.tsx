import type { BenchmarkPayload } from "../lib/agui";

type Props = {
  benchmark: BenchmarkPayload | null;
};

export function BenchmarkComparison({ benchmark }: Props) {
  if (!benchmark) {
    return <p className="empty-note">Benchmark comparison waits for synthesis output.</p>;
  }

  const simulatedDistribution = benchmark.simulated_distribution ?? [];
  const actualPollingData = benchmark.actual_polling_data ?? [];
  const rows = simulatedDistribution.map((simulated) => {
    const actual = actualPollingData.find((item) => item.segment === simulated.segment);
    return { simulated, actual };
  });

  return (
    <article className="benchmark-card">
      <div className="score-orb">
        <strong>{benchmark.calibration_score}</strong>
        <span>{benchmark.score_label}</span>
      </div>
      <div>
        <h3>{benchmark.event_name}</h3>
        <p>{benchmark.interpretation}</p>
      </div>
      <div className="benchmark-grid">
        {rows.map(({ simulated, actual }) => (
          <div className="benchmark-row" key={simulated.segment}>
            <span className="match-indicator">Match</span>
            <h4>{simulated.segment}</h4>
            <p>
              <strong>Simulated:</strong> {simulated.simulated}
            </p>
            {actual ? (
              <p>
                <strong>Historical:</strong> {actual.actual} <em>{actual.source_label}</em>
              </p>
            ) : null}
          </div>
        ))}
      </div>
    </article>
  );
}
