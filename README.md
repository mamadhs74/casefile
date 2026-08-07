# casefile

Automated documentary video production system. See `CLAUDE.md` for the
architecture, non-negotiable rules, and conventions.

## Development

### Seeding local data

`scripts/seed_dev.py` populates `data/casefile.db` with seven cases spanning
every monetization tier and legal-risk level (green/yellow/red/unknown,
low/medium/high), plus sources on two of them -- one with a passing R1 source
gate, one with a failing one. It's meant for exercising the case library UI
against real data rather than an empty database.

```
uv run python -m scripts.seed_dev
```

Safe to re-run: it checks for existing cases first and does nothing if the
database is already seeded. It writes through the same SQLModel listeners as
the API, so `monetization_tier`, `legal_risk`, `eligibility_notes`, and
`Source.domain` are computed, never set directly.
