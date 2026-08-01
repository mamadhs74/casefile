export function slugify(title: string): string {
  return title
    .normalize('NFKD')
    .replace(/\p{Diacritic}/gu, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

export interface SlugState {
  slug: string;
  slugTouched: boolean;
}

export const INITIAL_SLUG_STATE: SlugState = { slug: '', slugTouched: false };

/**
 * Call when the title field changes. Slug keeps following the title until
 * the operator edits the slug field directly -- once touched, title edits
 * no longer overwrite it. Touched must be set on the slug's onChange, not
 * onFocus: focusing the field to look at it (tabbing through, clicking to
 * copy) is not the same as editing it, and treating it as such was the bug.
 */
export function slugForTitleChange(current: SlugState, title: string): SlugState {
  return current.slugTouched ? current : { slug: slugify(title), slugTouched: false };
}

/** Call on the slug field's onChange -- any manual edit locks in slugTouched. */
export function slugForManualEdit(value: string): SlugState {
  return { slug: value, slugTouched: true };
}
