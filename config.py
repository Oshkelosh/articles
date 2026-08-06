"""Articles tool config + storage manifest models.

Content lives in object storage (``articles/manifest.json``, ``articles/{id}/body.md``,
``articles/hub.md``). ``ArticlesConfig`` is an enable-only stub for addon_configs.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ArticlesConfig(BaseModel):
    """Enable-only stub; article bodies/index live in object storage."""

    model_config = ConfigDict(extra="ignore")

    @classmethod
    def config_model(cls):
        return cls


class ArticleMeta(BaseModel):
    """Post metadata stored in ``articles/manifest.json`` (no body)."""

    id: str = Field(min_length=1, max_length=64)
    slug: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=200)
    meta_title: str | None = Field(default=None, max_length=200)
    meta_description: str | None = Field(default=None, max_length=500)
    published: bool = False
    published_at: datetime | None = None
    updated_at: datetime = Field(default_factory=utc_now)

    @field_validator("title", "slug")
    @classmethod
    def strip_required(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("required")
        return cleaned

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str) -> str:
        slug = value.strip().lower()
        if not _SLUG_RE.match(slug):
            raise ValueError("slug must be lowercase letters, numbers, and hyphens")
        return slug

    @field_validator("meta_title", "meta_description")
    @classmethod
    def empty_meta_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class ArticlesManifest(BaseModel):
    intro_title: str = Field(default="Articles", min_length=1, max_length=200)
    meta_title: str | None = Field(default=None, max_length=200)
    meta_description: str | None = Field(default=None, max_length=500)
    posts: list[ArticleMeta] = Field(default_factory=list)

    @field_validator("intro_title")
    @classmethod
    def strip_intro_title(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("intro_title is required")
        return cleaned

    @field_validator("meta_title", "meta_description")
    @classmethod
    def empty_meta_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @model_validator(mode="after")
    def unique_ids_and_slugs(self) -> ArticlesManifest:
        ids = [p.id for p in self.posts]
        if len(ids) != len(set(ids)):
            raise ValueError("post ids must be unique")
        slugs = [p.slug for p in self.posts]
        if len(slugs) != len(set(slugs)):
            raise ValueError("post slugs must be unique")
        return self


# Back-compat alias for older imports/tests during migration.
ArticlePost = ArticleMeta
