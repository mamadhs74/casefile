# Archival retrieval layer

`packages/archive/`

Searches public archives for imagery and footage tied to a case, normalizes wildly
different metadata into one shape, and refuses anything whose license cannot be
positively identified.

This is where R6 stops being a docstring. The `Asset` table already requires a
`license` with no `UNKNOWN` value; this package is what earns the right to write
one.

---

## Core principle

**An unparseable license is a rejection, not a warning.**

Every provider expresses rights differently — Wikimedia has structured license
templates, the Library of Congress often has free-text rights statements, the
Internet Archive has an optional `licenseurl` and an unstructured `rights` field
that is frequently absent. The temptation is to fall back to "probably public
domain, it's from 1922." Don't. Age does not guarantee public domain status: the
photograph may be old while the *scan* carries a new claim, the item may be
public domain in the US but not in Germany, and archives routinely host material
they do not own.

`LicenseResolver` returns `LicenseType | None`. `None` means the candidate is
dropped and never reaches the operator. Log the rejection with the raw rights
string so the resolver can be improved from real data.

---

## Provider interface

```python
class ArchiveProvider(Protocol):
    name: str
    requires_key: bool

    async def search(self, query: ArchiveQuery) -> list[RawResult]: ...
    async def fetch_detail(self, external_id: str) -> RawResult: ...
```

`ArchiveQuery` carries: free-text terms, an optional year range, an optional
place, a media kind (`IMAGE` or `VIDEO`), and a result limit. Providers translate
it into their own query language. A provider that cannot express a constraint
ignores it rather than failing.

`RawResult` is deliberately loose — provider-specific fields land in a `raw: dict`
and normalization happens in one place, not inside each adapter.

All providers are async and go through a single `httpx.AsyncClient` with:

- A descriptive `User-Agent` including a contact URL. **Wikimedia blocks generic
  and absent user agents** and this is the most common reason a first integration
  silently returns nothing.
- Per-provider rate limiting. Be a good citizen; these are free public services
  funded by donations and grants.
- Retry with backoff on 429 and 5xx, no retry on 4xx.
- A hard timeout. An archive being slow must not hang the pipeline.

---

## Providers

Build in this order. The first three need no API key.

### 1. Wikimedia Commons

The best starting point: structured license metadata, huge historical holdings,
no key required.

Use the `action=query` API with `prop=imageinfo` and
`iiprop=url|size|extmetadata`. The `extmetadata` block carries `LicenseShortName`,
`License`, `UsageTerms`, `Artist`, and `Credit` — this is the richest rights
metadata of any provider and the reason to start here.

Filter to `File:` namespace. Request `iiurlwidth` to get a scaled thumbnail URL
for the picker without downloading originals.

### 2. Internet Archive

Enormous, includes public-domain film footage, no key for search.

Use the `advancedsearch.php` JSON endpoint with `rows`, `page`, and an `fl[]`
field list including `identifier`, `title`, `date`, `licenseurl`, `rights`,
`mediatype`, and `collection`. Then `metadata/{identifier}` for the file list.

Two things to know: the `rights` field is free text and often absent, so
expect a high rejection rate here. And `collection` is a strong signal — items
in known public-domain collections (`prelinger`, `usgovfilms`) are far more
reliably clean than general uploads.

### 3. Library of Congress

`loc.gov` returns JSON by appending `?fo=json` to any search URL. No key.
Predominantly US material, mostly public domain, with a `rights_advisory` field.

Excellent for early-20th-century American cases. Useless for European ones.

### 4. Europeana

Needs a free API key. This is the one that matters for German and European
cases — it aggregates hundreds of European institutions and returns structured
`rights` URLs pointing at rightsstatements.org or Creative Commons, which makes
resolution far more reliable than the Internet Archive.

### 5. Pexels and Pixabay

Free keys, generous limits, clear commercial licenses. Not archival — use for
generic texture and B-roll (fog, forest, rain on a window, old paper) where
nothing real is being depicted. Never for anything presented as being of the
case.

---

## License resolution

`packages/archive/licensing.py`

```python
def resolve(raw_rights: str | None, license_url: str | None,
            provider: str) -> LicenseType | None
```

Match in this order, most specific first:

1. **A recognized license URL.** creativecommons.org paths map cleanly:
   `/publicdomain/zero/` → `CC0`, `/publicdomain/mark/` → `PUBLIC_DOMAIN`,
   `/licenses/by/` → `CC_BY`. rightsstatements.org `NoC-*` and `InC-*` are
   *not* free licenses — reject them; they mean "no copyright in this
   jurisdiction" or "in copyright," neither of which is a grant to you.
2. **A known template string.** Wikimedia's `PD-old-70`, `PD-US-expired`,
   `CC0`, `CC BY 4.0` and their common variants.
3. **A provider-wide default**, only where the provider guarantees it. Pexels
   and Pixabay licenses are uniform across their catalogs, so those map
   directly. No other provider gets a blanket default.
4. **Otherwise `None`.**

`CC_BY` and anything share-alike sets `attribution_required = True` and populates
`attribution_text` from the artist and credit fields. An asset that requires
attribution but has no attribution text is a rejection — you cannot comply with
a term you failed to record.

Keep a `tests/fixtures/rights_strings.json` of real strings harvested from live
responses, and grow it every time the resolver rejects something it shouldn't.
That file is the actual asset here; the resolver is just a function over it.

---

## Fitness for Ken Burns

A candidate that passes the license gate can still be unusable.

`packages/archive/fitness.py` computes a `FitnessReport`:

- **Resolution.** For 1080p output, a static shot needs 1920px on the long edge.
  Any zoom needs `1920 × max_zoom_factor` — at a 1.3× push that's roughly 2500px.
  Below 1920, reject. Between 1920 and 2500, allow but restrict `MotionType` to
  `STATIC` and `DRIFT`. Upscaling to fake a zoom looks exactly like what it is.
- **Aspect ratio.** Archival stills are frequently 4:3 or portrait against a 16:9
  frame. Record the ratio so the renderer can choose: pan across a wide image,
  fill the sides with a blurred copy, or letterbox against a flat card. Portrait
  images below 1080px wide are effectively only usable letterboxed.
- **Format.** Reject formats ffmpeg can't decode without extra work. Flag
  animated GIFs — they're almost never what you want in a documentary.

Fitness is advisory and stored on the candidate, not a hard gate. The operator
may accept a soft image for a shot where nothing better exists.

---

## Candidates and selection

Search results are not assets. Add one table:

**`AssetCandidate`** — `case_id`, `provider`, `external_id`, `title`,
`thumbnail_url`, `full_url`, `width`, `height`, `mime_type`, `resolved_license`,
`attribution_text`, `source_url`, `fitness` (JSON), `raw` (JSON),
`selected` (bool), `rejected_reason`.

Unique on `(provider, external_id, case_id)` so re-running a search doesn't
duplicate. Deduplicate across providers by perceptual hash once downloaded —
Wikimedia and the Internet Archive hold many of the same scans.

Promotion to `Asset` happens only on operator selection: download the original,
compute the sha256, write the file, create the `Asset` with the resolved license
and attribution. `AssetStore.add()` already refuses anything without a license,
so this path cannot bypass R6.

---

## Query construction

Given a `Case` and its `Fact` rows, build queries that archives actually answer.
Naive full-text search on a case summary returns noise.

Useful query shapes, in rough order of yield: the place name plus the decade;
surnames of principals plus the place; the name of the building, ship, or
institution involved; the newspaper name plus the year for scanned press; and
generic period-and-place terms for establishing shots ("Bavaria farmhouse 1920s").

Run several narrow queries rather than one broad one, and keep the query string
on the candidate so the operator can see why something surfaced.

---

## Endpoints

```
POST /cases/{id}/archive/search      body: ArchiveQuery, returns candidates
GET  /cases/{id}/archive/candidates  filter by selected, provider, license
POST /candidates/{id}/select         downloads, creates Asset, returns it
POST /candidates/{id}/reject         records a reason
```

Search is slow and network-bound. Run it as a `Job` rather than blocking the
request, and have the frontend poll.

---

## Tests

- `resolve()` against every string in the fixtures file, both directions —
  known-good licenses resolve, and `NoC-*`, `InC-*`, empty strings, and free-text
  rights notes all return `None`.
- An `AssetCandidate` with `resolved_license=None` can never be promoted.
- A `CC_BY` candidate with empty attribution text is rejected at promotion.
- Fitness: a 1600px image forbids zoom motion; a 3000px image permits it.
- Provider adapters against recorded HTTP fixtures, not the live network. Live
  archives change and a test suite that fails because Wikimedia reindexed is a
  test suite you'll start ignoring.

---

## Not in scope yet

No automatic selection. No relevance ranking beyond what the providers return.
No image editing. The operator picks from candidates; teaching the system to pick
comes much later, and only once there's selection history to learn from.
