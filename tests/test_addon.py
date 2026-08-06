"""Package tests for the Articles tool addon (storage-backed)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.addons.tools.articles.addon import ArticlesToolAddon
from app.addons.tools.articles.config import ArticleMeta, ArticlesManifest
from app.addons.tools.articles.markdown_util import plain_excerpt
from app.addons.tools.articles import store as articles_store
from app.config import Settings
from app.storage.factory import create_storage, reset_storage
from app.storage.local import LocalStorageBackend


@pytest.fixture
def local_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "data" / "uploads").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DEPLOYMENT_PROFILE", "local")
    monkeypatch.setenv("PUBLIC_APP_URL", "http://testserver")
    reset_storage()
    backend = create_storage(Settings())
    yield backend
    reset_storage()


def test_plain_excerpt_strips_markup():
    text = plain_excerpt("Hello **world** with a [link](https://x.test)!", max_len=80)
    assert "Hello" in text
    assert "world" in text
    assert "link" in text
    assert "**" not in text
    assert "https" not in text


def test_manifest_rejects_duplicate_slugs():
    with pytest.raises(ValidationError):
        ArticlesManifest(
            posts=[
                ArticleMeta(id="a", slug="hello", title="One"),
                ArticleMeta(id="b", slug="hello", title="Two"),
            ]
        )


@pytest.mark.asyncio
async def test_published_filtering_and_seo(local_storage):
    assert isinstance(local_storage, LocalStorageBackend)
    storage = local_storage

    manifest = ArticlesManifest(
        intro_title="Articles",
        posts=[
            ArticleMeta(
                id="1",
                slug="live",
                title="Live post",
                published=True,
                published_at="2026-01-01T00:00:00Z",
                updated_at="2026-01-02T00:00:00Z",
            ),
            ArticleMeta(
                id="2",
                slug="draft",
                title="Draft",
                published=False,
                updated_at="2026-01-03T00:00:00Z",
            ),
        ],
    )
    await articles_store.save_manifest(manifest, storage)
    await articles_store.save_hub_markdown("Welcome", storage)
    await articles_store.save_body(
        "1", "Body of the live post with enough text.", storage
    )
    await articles_store.save_body("2", "Hidden", storage)

    addon = ArticlesToolAddon()
    await addon.initialize({})

    hub = addon.hub_payload()
    assert hub is not None
    assert hub["intro_markdown"] == "Welcome"
    assert [p["slug"] for p in hub["posts"]] == ["live"]
    assert addon.get_published_post("draft") is None
    assert addon.get_published_post("live") is not None
    assert "live post" in (addon.get_published_post("live") or {}).get(
        "body_markdown", ""
    ).lower()

    assert addon.list_storefront_nav_links() == [
        {"label": "Articles", "href": "/articles"}
    ]

    hub_seo = addon.resolve_seo_meta(
        "/articles",
        site_url="https://shop.example",
        store_name="Shop",
    )
    assert hub_seo is not None
    assert hub_seo["canonical_url"] == "https://shop.example/articles"
    assert any(b.get("@type") == "CollectionPage" for b in hub_seo["json_ld"])
    assert hub_seo["crawl_articles"][0][1].endswith("/articles/live")
    assert addon.list_crawl_article_links("https://shop.example") == [
        {"label": "Live post", "href": "https://shop.example/articles/live"}
    ]

    post_seo = addon.resolve_seo_meta(
        "/articles/live",
        site_url="https://shop.example",
        store_name="Shop",
    )
    assert post_seo is not None
    assert post_seo["og_type"] == "article"
    assert any(b.get("@type") == "Article" for b in post_seo["json_ld"])

    assert (
        addon.resolve_seo_meta(
            "/articles/draft",
            site_url="https://shop.example",
            store_name="Shop",
        )
        is None
    )

    entries = addon.list_sitemap_entries("https://shop.example")
    locs = [e["loc"] for e in entries]
    assert "https://shop.example/articles" in locs
    assert "https://shop.example/articles/live" in locs
    assert "https://shop.example/articles/draft" not in locs


@pytest.mark.asyncio
async def test_legacy_config_migration(local_storage):
    storage = local_storage
    migrated = await articles_store.migrate_legacy_config(
        {
            "intro_title": "Notes",
            "intro_markdown": "Hi there",
            "posts": [
                {
                    "id": "abc",
                    "slug": "first",
                    "title": "First",
                    "body_markdown": "Legacy body",
                    "published": True,
                    "updated_at": "2026-01-01T00:00:00Z",
                }
            ],
        },
        storage,
    )
    assert migrated is not None
    assert migrated.intro_title == "Notes"
    assert await articles_store.load_hub_markdown(storage) == "Hi there"
    assert await articles_store.load_body("abc", storage) == "Legacy body"

    # Second call is a no-op when manifest already exists.
    again = await articles_store.migrate_legacy_config(
        {"posts": [{"id": "x", "slug": "x", "title": "X", "body_markdown": "nope"}]},
        storage,
    )
    assert again is None
