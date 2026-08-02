import type { GateResultRead, SourceGateFailureReason } from '../../api/subjects';

interface Condition {
  key: SourceGateFailureReason;
  label: string;
}

interface GateStatusProps {
  gate: GateResultRead;
  /** The subject's own strategy sets these -- see docs/SCHEMA.md's "Strategy" section. */
  minVerifiedSources: number;
  minPrimaryRecords: number;
  minDistinctDomains: number;
}

/** Reads as a status, not a form field — the answer to "can I write this yet." */
export function GateStatus({
  gate,
  minVerifiedSources,
  minPrimaryRecords,
  minDistinctDomains,
}: GateStatusProps) {
  const conditions: Condition[] = [
    {
      key: 'insufficient_verified_sources',
      label: `${gate.verified_source_count} of ${minVerifiedSources} verified sources`,
    },
    {
      key: 'missing_primary_record',
      label: `${gate.primary_record_count} of ${minPrimaryRecords} primary record`,
    },
    {
      key: 'insufficient_distinct_domains',
      label: `${gate.distinct_domain_count} of ${minDistinctDomains} distinct domains`,
    },
  ];

  return (
    <div
      className={`rounded-lg border p-4 ${
        gate.passed
          ? 'border-folder-green/40 bg-folder-green/8'
          : 'border-folder-rust/40 bg-folder-rust/8'
      }`}
    >
      <h3
        className={`font-sans text-sm font-semibold ${
          gate.passed ? 'text-folder-green' : 'text-folder-rust'
        }`}
      >
        {gate.passed ? 'Clears the source gate' : 'Not yet clear to write'}
      </h3>
      <ul className="mt-3 flex flex-col gap-1.5">
        {conditions.map((condition) => {
          const passed = !gate.reasons.includes(condition.key);
          return (
            <li key={condition.key} className="flex items-center gap-2 font-mono text-xs">
              <span
                className={passed ? 'text-folder-green' : 'text-folder-rust'}
                aria-hidden="true"
              >
                {passed ? '✓' : '✕'}
              </span>
              <span className="text-ink">{condition.label}</span>
              <span className="text-ink-muted">{passed ? '— met' : '— not met'}</span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
