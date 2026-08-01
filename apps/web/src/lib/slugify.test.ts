import { describe, expect, it } from 'vitest';
import { slugForManualEdit, slugForTitleChange, slugify } from './slugify';

describe('slugify', () => {
  it('kebab-cases a plain title', () => {
    expect(slugify('The Vanishing of the SS Meridian')).toBe('the-vanishing-of-the-ss-meridian');
  });

  it('strips diacritics rather than dropping the letter', () => {
    expect(slugify('Café Núñez')).toBe('cafe-nunez');
  });

  it('collapses punctuation and whitespace runs into a single hyphen', () => {
    expect(slugify('A Case: What Happened?!')).toBe('a-case-what-happened');
  });

  it('trims leading and trailing hyphens', () => {
    expect(slugify('  --weird--  ')).toBe('weird');
  });

  it('returns an empty string for input with no alphanumerics', () => {
    expect(slugify('---')).toBe('');
  });
});

describe('slug derive-until-edited', () => {
  it('derives the slug from the title while untouched', () => {
    let state = { slug: '', slugTouched: false };
    state = slugForTitleChange(state, 'The Cedar Street Fire');
    expect(state).toEqual({ slug: 'the-cedar-street-fire', slugTouched: false });
  });

  it('keeps deriving on every title change until the slug is edited', () => {
    let state = { slug: '', slugTouched: false };
    state = slugForTitleChange(state, 'First Draft Title');
    state = slugForTitleChange(state, 'Second Draft Title');
    expect(state.slug).toBe('second-draft-title');
    expect(state.slugTouched).toBe(false);
  });

  it('stops following the title once the slug is edited manually', () => {
    let state = { slug: '', slugTouched: false };
    state = slugForTitleChange(state, 'Original Title');
    state = slugForManualEdit('a-custom-slug');
    state = slugForTitleChange(state, 'Retitled Case');

    expect(state.slug).toBe('a-custom-slug');
    expect(state.slugTouched).toBe(true);
  });

  it('does not treat merely focusing the field as an edit -- only slugForManualEdit does', () => {
    // Regression: the bug was wiring slugTouched to onFocus. Nothing in this
    // module reacts to focus; slugForTitleChange must keep deriving unless
    // slugForManualEdit was actually called.
    let state = { slug: '', slugTouched: false };
    state = slugForTitleChange(state, 'A Title');
    state = slugForTitleChange(state, 'A Title, Continued');
    expect(state.slug).toBe('a-title-continued');
    expect(state.slugTouched).toBe(false);
  });

  it('clearing the slug manually still counts as touched, not a reset', () => {
    let state = { slug: '', slugTouched: false };
    state = slugForTitleChange(state, 'Original Title');
    state = slugForManualEdit('');
    state = slugForTitleChange(state, 'A New Title');

    expect(state.slug).toBe('');
    expect(state.slugTouched).toBe(true);
  });
});
