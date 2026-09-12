"""film-tv-news's YouTube publish-metadata template -- title,
description, tags. Registered into packages.publish.templates as an
import side effect, same pattern this package already uses for its
eligibility scorer (packages/research/dispatch.py) and tier assigner
(packages/research/tiering.py).
"""

from __future__ import annotations

from packages.publish.templates import (
    PublishMetadata,
    PublishMetadataInput,
    register_publish_template,
)

_MAX_TITLE_CHARS = 100  # YouTube's own title limit

# R5 (CLAUDE.md): every upload discloses synthetic narration. This
# line is the human-readable half of that disclosure (the description
# text); the machine-readable half (the API's own altered/synthetic-
# content flag) is a known gap in packages/publish/youtube.py -- see
# that module's docstring. Both are required; neither one substitutes
# for the other. No mention of imagery -- render_episode.py produces
# text cards only, no generated imagery exists in the render path yet
# (see docs/HANDOFF.md sec 6 -- claim-to-image mapping is unbuilt).
_DISCLOSURE_LINE = (
    "This video uses AI-generated narration, disclosed per "
    "YouTube's altered/synthetic content policy."
)

_BASE_TAGS = ["film news", "TV news", "entertainment industry", "Hollywood"]


def build_metadata(data: PublishMetadataInput) -> PublishMetadata:
    title = data.subject_title
    if len(title) > _MAX_TITLE_CHARS:
        title = title[: _MAX_TITLE_CHARS - 1].rstrip() + "…"

    description = "\n".join([data.thesis, "", _DISCLOSURE_LINE])

    tags = list(_BASE_TAGS)
    if data.event_year is not None:
        tags.append(str(data.event_year))

    return PublishMetadata(title=title, description=description, tags=tags)


register_publish_template("film-tv-news", build_metadata)
