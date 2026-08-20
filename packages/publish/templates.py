"""Per-strategy YouTube publish-metadata templates: title, description,
tags. Strategy-owned code (packages/strategies/<slug>/publish_template.py),
registered into this shared registry the same way eligibility scorers
(packages/research/dispatch.py) and tier assigners
(packages/research/tiering.py) already are -- a strategy that never
registers one fails loudly the moment something asks for it, rather
than silently producing an empty or wrong-brand upload.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PublishMetadataInput:
    """Plain data a template needs to build title/description/tags --
    no Session, no ORM object, same reasoning ClaimForComposition
    documents for staying free of packages.db. Deliberately minimal:
    the pipeline stage that will actually call this
    (scripts/run_episode.py) isn't built yet -- see the task this was
    built under -- so this is kept small on purpose rather than
    guessing what a not-yet-built stage will have on hand."""

    subject_title: str
    thesis: str
    event_year: int | None


@dataclass(frozen=True)
class PublishMetadata:
    title: str
    description: str
    tags: list[str]


class PublishTemplate(Protocol):
    def __call__(self, data: PublishMetadataInput) -> PublishMetadata: ...


class UnknownPublishTemplateError(Exception):
    """Raised when a strategy has no registered publish template --
    e.g. criminal-cases, deliberately left unbuilt per the task this
    was built under. Fails loudly rather than uploading with an empty
    or generic title/description."""

    def __init__(self, slug: str) -> None:
        self.slug = slug
        super().__init__(f"no publish template registered for strategy {slug!r}")


_REGISTRY: dict[str, PublishTemplate] = {}


def register_publish_template(slug: str, template: PublishTemplate) -> None:
    _REGISTRY[slug] = template


def get_publish_template(slug: str) -> PublishTemplate:
    try:
        return _REGISTRY[slug]
    except KeyError:
        raise UnknownPublishTemplateError(slug) from None
