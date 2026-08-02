import { useState, type FormEvent, type ReactNode } from 'react';
import { Link, useNavigate } from 'react-router';
import { useCreateSubject, useEligibilityPreview, useStrategies, useSubjectNoun } from '../api/queries';
import type { ResolutionStatus, StrategyRead, SubjectCreate } from '../api/subjects';
import { humanize, resolutionStatusLabels } from '../lib/domain';
import { slugForManualEdit, slugForTitleChange } from '../lib/slugify';
import { useDebouncedValue } from '../lib/useDebouncedValue';
import { VerdictPanel, type VerdictState } from '../components/subjects/VerdictPanel';

const RESOLUTION_STATUSES = Object.keys(resolutionStatusLabels) as ResolutionStatus[];

/**
 * The shape packages/research/dispatch.py::validate_attributes actually
 * validates against, once the API has inlined its $refs (see
 * apps/api/routers/strategies.py). attributes_schema on StrategyRead is
 * typed dict[str, Any] on the Python side -- necessarily opaque here, since
 * its shape varies per strategy -- so this is a local, hand-maintained
 * contract with that endpoint rather than something schema.ts can generate.
 */
interface AttributesSchema {
  properties: Record<string, { enum?: string[] }>;
  required: string[];
}

function getAttributesSchema(strategy: StrategyRead | undefined): AttributesSchema {
  if (!strategy) return { properties: {}, required: [] };
  return strategy.attributes_schema as unknown as AttributesSchema;
}

function capitalize(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

interface FormState {
  strategySlug: string;
  title: string;
  slug: string;
  slugTouched: boolean;
  attributes: Record<string, string>;
  eventYear: string;
  country: string;
  region: string;
  summary: string;
  resolutionStatus: ResolutionStatus | '';
  livingPersonsInvolved: boolean;
  riskFlags: string[];
  documentationScore: string;
  estimatedRuntimeMin: string;
}

const INITIAL_FORM: FormState = {
  strategySlug: '',
  title: '',
  slug: '',
  slugTouched: false,
  attributes: {},
  eventYear: '',
  country: '',
  region: '',
  summary: '',
  resolutionStatus: '',
  livingPersonsInvolved: false,
  riskFlags: [],
  documentationScore: '',
  estimatedRuntimeMin: '',
};

function buildPayload(form: FormState, schema: AttributesSchema): SubjectCreate | null {
  const eventYear = Number(form.eventYear);
  const attributesComplete = schema.required.every((field) => form.attributes[field]?.trim());

  if (
    !form.strategySlug ||
    !form.title.trim() ||
    !form.slug.trim() ||
    !form.country.trim() ||
    !form.summary.trim() ||
    !form.resolutionStatus ||
    form.eventYear.trim() === '' ||
    !Number.isFinite(eventYear) ||
    !attributesComplete
  ) {
    return null;
  }

  return {
    strategy_slug: form.strategySlug,
    slug: form.slug.trim(),
    title: form.title.trim(),
    event_year: eventYear,
    country: form.country.trim(),
    region: form.region.trim() || null,
    summary: form.summary.trim(),
    resolution_status: form.resolutionStatus,
    living_persons_involved: form.livingPersonsInvolved,
    risk_flags: form.riskFlags,
    attributes: form.attributes,
    documentation_score:
      form.documentationScore.trim() === '' ? null : Number(form.documentationScore),
    estimated_runtime_min:
      form.estimatedRuntimeMin.trim() === '' ? null : Number(form.estimatedRuntimeMin),
    status: 'candidate',
  };
}

const REQUIRED_FIELD_CHECKS: [key: keyof FormState, label: string, isEmpty: (f: FormState) => boolean][] =
  [
    ['title', 'title', (f) => !f.title.trim()],
    ['eventYear', 'year', (f) => f.eventYear.trim() === '' || !Number.isFinite(Number(f.eventYear))],
    ['country', 'country', (f) => !f.country.trim()],
    ['resolutionStatus', 'resolution', (f) => !f.resolutionStatus],
    ['summary', 'summary', (f) => !f.summary.trim()],
  ];

function missingRequiredFields(form: FormState, schema: AttributesSchema): string[] {
  if (!form.strategySlug) return ['strategy'];
  const base = REQUIRED_FIELD_CHECKS.filter(([, , isEmpty]) => isEmpty(form)).map(([, label]) => label);
  const missingAttributes = schema.required
    .filter((field) => !form.attributes[field]?.trim())
    .map((field) => humanize(field).toLowerCase());
  return [...base, ...missingAttributes];
}

function Field({
  label,
  htmlFor,
  children,
  hint,
}: {
  label: string;
  htmlFor: string;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={htmlFor} className="text-sm font-medium text-ink">
        {label}
      </label>
      {children}
      {hint && <p className="text-xs text-ink-muted">{hint}</p>}
    </div>
  );
}

const inputClasses =
  'rounded-md border border-ink/15 bg-paper px-3 py-2 font-sans text-sm text-ink placeholder:text-ink-muted focus-visible:outline-2 focus-visible:outline-ledger-blue';

export function NewSubjectPage() {
  const [form, setForm] = useState<FormState>(INITIAL_FORM);
  const navigate = useNavigate();
  const noun = useSubjectNoun();
  const { data: strategies } = useStrategies();
  const selectedStrategy = strategies?.find((s) => s.slug === form.strategySlug);
  const schema = getAttributesSchema(selectedStrategy);

  const payload = buildPayload(form, schema);
  const debouncedPayload = useDebouncedValue(payload, 400);
  const isDebouncing = JSON.stringify(payload) !== JSON.stringify(debouncedPayload);

  const previewQuery = useEligibilityPreview(debouncedPayload);
  const createSubjectMutation = useCreateSubject();

  let verdictState: VerdictState;
  if (!payload) {
    verdictState = 'incomplete';
  } else if (isDebouncing || previewQuery.isFetching) {
    verdictState = previewQuery.data ? 'pending-refresh' : 'pending-first';
  } else if (previewQuery.isError) {
    verdictState = 'error';
  } else {
    verdictState = 'resolved';
  }

  const missingFields = payload ? [] : missingRequiredFields(form, schema);

  function update<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function handleStrategyChange(strategySlug: string) {
    // Risk flags and attributes are that strategy's own vocabulary --
    // carrying them across a strategy change would let a value from one
    // strategy silently masquerade as valid for another.
    setForm((prev) => ({ ...prev, strategySlug, attributes: {}, riskFlags: [] }));
  }

  function updateAttribute(field: string, value: string) {
    setForm((prev) => ({ ...prev, attributes: { ...prev.attributes, [field]: value } }));
  }

  function handleTitleChange(value: string) {
    setForm((prev) => ({
      ...prev,
      title: value,
      ...slugForTitleChange(prev, value),
    }));
  }

  function handleSlugChange(value: string) {
    setForm((prev) => ({ ...prev, ...slugForManualEdit(value) }));
  }

  function toggleRiskFlag(flag: string) {
    setForm((prev) => ({
      ...prev,
      riskFlags: prev.riskFlags.includes(flag)
        ? prev.riskFlags.filter((f) => f !== flag)
        : [...prev.riskFlags, flag],
    }));
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!payload) return;
    const created = await createSubjectMutation.mutateAsync(payload);
    navigate(`/subjects/${created.id}`);
  }

  const identityLegend = selectedStrategy
    ? `${capitalize(selectedStrategy.subject_noun_singular)} identity`
    : 'Identity';

  return (
    <div className="max-w-5xl">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <Link to="/subjects" className="text-sm text-ink-muted hover:text-ledger-blue">
            ← Back to {noun.plural}
          </Link>
          <h1 className="mt-2 font-sans text-2xl font-semibold text-ink">
            Add a {selectedStrategy?.subject_noun_singular ?? noun.singular}
          </h1>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="grid grid-cols-1 gap-8 lg:grid-cols-3">
        <div className="flex flex-col gap-8 lg:col-span-2">
          <fieldset className="flex flex-col gap-4 rounded-lg border border-ink/10 bg-paper-raised p-5">
            <legend className="px-1 text-xs font-semibold uppercase tracking-wide text-ink-muted">
              Strategy
            </legend>

            <Field
              label="Strategy"
              htmlFor="strategy_slug"
              hint="Determines which risk factors and categories apply below."
            >
              <select
                id="strategy_slug"
                required
                value={form.strategySlug}
                onChange={(e) => handleStrategyChange(e.target.value)}
                className={inputClasses}
              >
                <option value="">Select a strategy</option>
                {(strategies ?? []).map((strategy) => (
                  <option key={strategy.slug} value={strategy.slug}>
                    {strategy.name}
                  </option>
                ))}
              </select>
            </Field>
          </fieldset>

          {selectedStrategy && (
            <>
              <fieldset className="flex flex-col gap-4 rounded-lg border border-ink/10 bg-paper-raised p-5">
                <legend className="px-1 text-xs font-semibold uppercase tracking-wide text-ink-muted">
                  {identityLegend}
                </legend>

                <Field label="Title" htmlFor="title">
                  <input
                    id="title"
                    type="text"
                    required
                    value={form.title}
                    onChange={(e) => handleTitleChange(e.target.value)}
                    className={inputClasses}
                    placeholder="The Vanishing of the SS Meridian"
                  />
                </Field>

                <Field
                  label="URL slug"
                  htmlFor="slug"
                  hint="Derived from the title until you edit it."
                >
                  <input
                    id="slug"
                    type="text"
                    required
                    value={form.slug}
                    onChange={(e) => handleSlugChange(e.target.value)}
                    className={`${inputClasses} font-mono text-xs`}
                  />
                </Field>

                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  {Object.entries(schema.properties).map(([field, prop]) => (
                    <Field key={field} label={humanize(field)} htmlFor={field}>
                      {prop.enum ? (
                        <select
                          id={field}
                          required
                          value={form.attributes[field] ?? ''}
                          onChange={(e) => updateAttribute(field, e.target.value)}
                          className={inputClasses}
                        >
                          <option value="">Select {humanize(field).toLowerCase()}</option>
                          {prop.enum.map((value) => (
                            <option key={value} value={value}>
                              {humanize(value)}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <input
                          id={field}
                          type="text"
                          required
                          value={form.attributes[field] ?? ''}
                          onChange={(e) => updateAttribute(field, e.target.value)}
                          className={inputClasses}
                        />
                      )}
                    </Field>
                  ))}

                  <Field label="Year" htmlFor="event_year">
                    <input
                      id="event_year"
                      type="number"
                      required
                      value={form.eventYear}
                      onChange={(e) => update('eventYear', e.target.value)}
                      className={inputClasses}
                      placeholder="1948"
                    />
                  </Field>

                  <Field label="Country" htmlFor="country">
                    <input
                      id="country"
                      type="text"
                      required
                      value={form.country}
                      onChange={(e) => update('country', e.target.value)}
                      className={inputClasses}
                    />
                  </Field>

                  <Field label="Region" htmlFor="region" hint="Optional.">
                    <input
                      id="region"
                      type="text"
                      value={form.region}
                      onChange={(e) => update('region', e.target.value)}
                      className={inputClasses}
                    />
                  </Field>
                </div>

                <Field label="Summary" htmlFor="summary">
                  <textarea
                    id="summary"
                    required
                    rows={4}
                    value={form.summary}
                    onChange={(e) => update('summary', e.target.value)}
                    className={inputClasses}
                  />
                </Field>
              </fieldset>

              <fieldset className="flex flex-col gap-4 rounded-lg border border-ink/10 bg-paper-raised p-5">
                <legend className="px-1 text-xs font-semibold uppercase tracking-wide text-ink-muted">
                  Resolution &amp; risk
                </legend>

                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <Field label="Resolution" htmlFor="resolution_status">
                    <select
                      id="resolution_status"
                      required
                      value={form.resolutionStatus}
                      onChange={(e) =>
                        update('resolutionStatus', e.target.value as ResolutionStatus)
                      }
                      className={inputClasses}
                    >
                      <option value="">Select a resolution</option>
                      {RESOLUTION_STATUSES.map((status) => (
                        <option key={status} value={status}>
                          {resolutionStatusLabels[status]}
                        </option>
                      ))}
                    </select>
                  </Field>

                  <Field label="Documentation score" htmlFor="documentation_score" hint="Optional.">
                    <input
                      id="documentation_score"
                      type="number"
                      min={0}
                      value={form.documentationScore}
                      onChange={(e) => update('documentationScore', e.target.value)}
                      className={inputClasses}
                    />
                  </Field>

                  <Field
                    label="Estimated runtime (min)"
                    htmlFor="estimated_runtime_min"
                    hint="Optional."
                  >
                    <input
                      id="estimated_runtime_min"
                      type="number"
                      min={0}
                      value={form.estimatedRuntimeMin}
                      onChange={(e) => update('estimatedRuntimeMin', e.target.value)}
                      className={inputClasses}
                    />
                  </Field>
                </div>

                <label className="flex items-center gap-2 text-sm text-ink">
                  <input
                    type="checkbox"
                    checked={form.livingPersonsInvolved}
                    onChange={(e) => update('livingPersonsInvolved', e.target.checked)}
                    className="h-4 w-4 rounded border-ink/25 accent-ledger-blue"
                  />
                  Living persons involved
                </label>

                <div className="flex flex-col gap-2">
                  <span className="text-sm font-medium text-ink">Risk factors</span>
                  <div className="grid grid-cols-1 gap-x-4 gap-y-2 sm:grid-cols-2">
                    {selectedStrategy.risk_flags.map((flag) => (
                      <label key={flag} className="flex items-center gap-2 text-sm text-ink-muted">
                        <input
                          type="checkbox"
                          checked={form.riskFlags.includes(flag)}
                          onChange={() => toggleRiskFlag(flag)}
                          className="h-4 w-4 rounded border-ink/25 accent-ledger-blue"
                        />
                        {humanize(flag)}
                      </label>
                    ))}
                  </div>
                </div>
              </fieldset>
            </>
          )}
        </div>

        <div className="flex flex-col gap-4 lg:sticky lg:top-8 lg:self-start">
          <VerdictPanel
            state={verdictState}
            missingFields={missingFields}
            result={previewQuery.data}
            subjectNoun={selectedStrategy?.subject_noun_singular ?? noun.singular}
            errorMessage={
              previewQuery.error instanceof Error ? previewQuery.error.message : undefined
            }
          />

          {payload && (
            <div className="flex flex-col gap-2">
              <button
                type="submit"
                disabled={createSubjectMutation.isPending}
                className="rounded-md bg-ledger-blue px-4 py-2 font-sans text-sm font-semibold text-paper disabled:opacity-40"
              >
                {createSubjectMutation.isPending
                  ? `Adding ${selectedStrategy?.subject_noun_singular ?? noun.singular}…`
                  : `Add ${selectedStrategy?.subject_noun_singular ?? noun.singular}`}
              </button>
              {createSubjectMutation.isError && (
                <p className="text-sm text-folder-rust">
                  Couldn't add {selectedStrategy?.subject_noun_singular ?? noun.singular}:{' '}
                  {createSubjectMutation.error instanceof Error
                    ? createSubjectMutation.error.message
                    : 'Something went wrong.'}
                </p>
              )}
            </div>
          )}
        </div>
      </form>
    </div>
  );
}
