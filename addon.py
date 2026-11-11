"""Articles tool addon — Markdown hub + posts for the storefront."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter

from app.addons.config_serialization import dump_addon_config
from app.addons.log import info, warning
from app.addons.tools.articles.config import ArticlesConfig, ArticlesManifest
from app.addons.tools.articles.markdown_util import plain_excerpt
from app.addons.tools.articles import store as articles_store
from app.addons.tools.base import ToolAddon
from app.storage import StorageBackend, get_storage


class ArticlesToolAddon(ToolAddon):
    """Manage a small set of Markdown articles for the storefront."""

    addon_id: str = "articles"
    addon_name: str = "Articles"
    addon_description: str = (
        "Simple Markdown articles hub for the storefront (intro + several posts)."
    )
    addon_category: str = "tool"
    version: str = "1.0.0"

    _config: Dict[str, Any] | None = None
    _manifest: ArticlesManifest | None = None
    _hub_markdown: str = ""
    _bodies: Dict[str, str]

    def __init__(self) -> None:
        super().__init__()
        self._config = None
        self._manifest = None
        self._hub_markdown = ""
        self._bodies = {}

    @classmethod
    def config_schema(cls):
        return ArticlesConfig

    async def initialize(self, config: dict) -> None:
        schema = self.config_schema()
        validated = schema(**config)
        self._config = dump_addon_config(validated)
        self.is_enabled = True
        await self.reload_cache(legacy_config=config)
        n = len(self._manifest.posts) if self._manifest else 0
        info("Articles", "Initialized with {} post(s) from storage", n)

    async def shutdown(self) -> None:
        self._config = None
        self._manifest = None
        self._hub_markdown = ""
        self._bodies = {}
        self.is_enabled = False

    async def reload_cache(
        self,
        *,
        legacy_config: dict[str, Any] | None = None,
        storage: StorageBackend | None = None,
    ) -> None:
        """Load manifest + hub + bodies into memory (SEO stays sync)."""
        storage = storage or get_storage()
        if legacy_config:
            try:
                migrated = await articles_store.migrate_legacy_config(
                    legacy_config, storage
                )
                if migrated is not None:
                    info(
                        "Articles",
                        "Migrated {} legacy config post(s) into storage",
                        len(migrated.posts),
                    )
            except Exception as exc:
                warning("Articles", "Legacy config migration failed: {}", exc)

        self._manifest = await articles_store.load_manifest(storage)
        self._hub_markdown = await articles_store.load_hub_markdown(storage)
        bodies: Dict[str, str] = {}
        for post in self._manifest.posts:
            bodies[post.id] = await articles_store.load_body(post.id, storage)
        self._bodies = bodies

    def _require_manifest(self) -> ArticlesManifest | None:
        if not self.is_enabled or self._manifest is None:
            return None
        return self._manifest

    def published_posts(self) -> list[dict[str, Any]]:
        manifest = self._require_manifest()
        if manifest is None:
            return []
        posts = [p for p in manifest.posts if p.published]
        posts.sort(
            key=lambda p: p.published_at or p.updated_at,
            reverse=True,
        )
        out: list[dict[str, Any]] = []
        for post in posts:
            data = post.model_dump(mode="json")
            data["body_markdown"] = self._bodies.get(post.id, "")
            out.append(data)
        return out

    def all_posts_for_admin(self) -> list[dict[str, Any]]:
        manifest = self._require_manifest()
        if manifest is None:
            return []
        out: list[dict[str, Any]] = []
        for post in manifest.posts:
            data = post.model_dump(mode="json")
            data["body_markdown"] = self._bodies.get(post.id, "")
            out.append(data)
        return out

    def hub_fields(self) -> dict[str, Any]:
        manifest = self._require_manifest()
        if manifest is None:
            return {
                "intro_title": "Articles",
                "intro_markdown": "",
                "meta_title": None,
                "meta_description": None,
            }
        return {
            "intro_title": manifest.intro_title,
            "intro_markdown": self._hub_markdown,
            "meta_title": manifest.meta_title,
            "meta_description": manifest.meta_description,
        }

    def get_published_post(self, slug: str) -> dict[str, Any] | None:
        for post in self.published_posts():
            if post["slug"] == slug:
                return post
        return None

    def get_post_by_id(self, post_id: str) -> dict[str, Any] | None:
        for post in self.all_posts_for_admin():
            if post["id"] == post_id:
                return post
        return None

    def hub_payload(self) -> dict[str, Any] | None:
        hub = self.hub_fields()
        if not self.is_enabled:
            return None
        posts = []
        for post in self.published_posts():
            posts.append(
                {
                    "slug": post["slug"],
                    "title": post["title"],
                    "published_at": post.get("published_at"),
                    "excerpt": plain_excerpt(post.get("body_markdown") or ""),
                }
            )
        return {
            "intro_title": hub["intro_title"],
            "intro_markdown": hub["intro_markdown"],
            "meta_title": hub["meta_title"],
            "meta_description": hub["meta_description"],
            "posts": posts,
        }

    def list_storefront_nav_links(self) -> list[dict[str, str]]:
        if not self.is_enabled:
            return []
        return [{"label": "Articles", "href": "/articles"}]

    def list_crawl_article_links(self, site_url: str) -> list[dict[str, str]]:
        if not self.is_enabled:
            return []
        origin = site_url.rstrip("/")
        return [
            {
                "label": post["title"],
                "href": f"{origin}/articles/{post['slug']}",
            }
            for post in self.published_posts()
        ]

    def list_sitemap_entries(self, site_url: str) -> list[dict[str, str | None]]:
        if self._require_manifest() is None:
            return []
        origin = site_url.rstrip("/")
        entries: list[dict[str, str | None]] = [
            {"loc": f"{origin}/articles", "lastmod": None},
        ]
        for post in self.published_posts():
            lastmod = None
            updated = post.get("updated_at")
            if updated:
                lastmod = str(updated)[:10]
            entries.append(
                {
                    "loc": f"{origin}/articles/{post['slug']}",
                    "lastmod": lastmod,
                }
            )
        return entries

    def resolve_seo_meta(
        self,
        path: str,
        *,
        site_url: str,
        store_name: str,
        default_description: str | None = None,
        logo_url: str | None = None,
    ) -> dict[str, Any] | None:
        manifest = self._require_manifest()
        if manifest is None:
            return None

        hub = self.hub_fields()
        normalized = path.rstrip("/") or "/"
        origin = site_url.rstrip("/")
        published = self.published_posts()

        if normalized == "/articles":
            title = (hub["meta_title"] or hub["intro_title"]).strip()
            page_title = f"{title} | {store_name}"
            description = (
                hub["meta_description"]
                or plain_excerpt(hub["intro_markdown"] or "")
                or default_description
                or f"Articles from {store_name}"
            )
            canonical = f"{origin}/articles"
            item_links = [
                (p["title"], f"{origin}/articles/{p['slug']}") for p in published
            ]
            return {
                "title": page_title,
                "description": description,
                "canonical_url": canonical,
                "og_type": "website",
                "og_image": logo_url,
                "site_name": store_name,
                "robots": "index, follow",
                "json_ld": [
                    {
                        "@context": "https://schema.org",
                        "@type": "BreadcrumbList",
                        "itemListElement": [
                            {
                                "@type": "ListItem",
                                "position": 1,
                                "name": "Home",
                                "item": f"{origin}/",
                            },
                            {
                                "@type": "ListItem",
                                "position": 2,
                                "name": hub["intro_title"],
                                "item": canonical,
                            },
                        ],
                    },
                    {
                        "@context": "https://schema.org",
                        "@type": "CollectionPage",
                        "name": page_title,
                        "url": canonical,
                        "mainEntity": {
                            "@type": "ItemList",
                            "itemListElement": [
                                {
                                    "@type": "ListItem",
                                    "position": i + 1,
                                    "url": href,
                                    "name": name,
                                }
                                for i, (name, href) in enumerate(item_links)
                            ],
                        },
                    },
                ],
                "crawl_hubs": [
                    ("Articles", canonical),
                ],
                "crawl_articles": item_links,
            }

        prefix = "/articles/"
        if normalized.startswith(prefix):
            slug = normalized[len(prefix) :]
            if not slug or "/" in slug:
                return None
            post = self.get_published_post(slug)
            if post is None:
                return None
            title = (post.get("meta_title") or post["title"]).strip()
            page_title = f"{title} | {store_name}"
            description = (
                post.get("meta_description")
                or plain_excerpt(post.get("body_markdown") or "")
                or default_description
            )
            canonical = f"{origin}/articles/{slug}"
            date_published = post.get("published_at") or post.get("updated_at")
            date_modified = post.get("updated_at") or date_published
            article_ld: dict[str, Any] = {
                "@context": "https://schema.org",
                "@type": "Article",
                "headline": post["title"],
                "mainEntityOfPage": canonical,
                "author": {"@type": "Organization", "name": store_name},
            }
            if description:
                article_ld["description"] = description
            if date_published:
                article_ld["datePublished"] = date_published
            if date_modified:
                article_ld["dateModified"] = date_modified
            return {
                "title": page_title,
                "description": description,
                "canonical_url": canonical,
                "og_type": "article",
                "og_image": logo_url,
                "site_name": store_name,
                "robots": "index, follow",
                "json_ld": [
                    {
                        "@context": "https://schema.org",
                        "@type": "BreadcrumbList",
                        "itemListElement": [
                            {
                                "@type": "ListItem",
                                "position": 1,
                                "name": "Home",
                                "item": f"{origin}/",
                            },
                            {
                                "@type": "ListItem",
                                "position": 2,
                                "name": hub["intro_title"],
                                "item": f"{origin}/articles",
                            },
                            {
                                "@type": "ListItem",
                                "position": 3,
                                "name": post["title"],
                                "item": canonical,
                            },
                        ],
                    },
                    article_ld,
                ],
                "crawl_hubs": [
                    ("Articles", f"{origin}/articles"),
                ],
                "crawl_articles": [
                    (p["title"], f"{origin}/articles/{p['slug']}") for p in published
                ],
            }

        return None

    def get_routers(self) -> List[APIRouter]:
        from app.addons.tools.articles.routes import api_router

        return [api_router]

    def get_admin_routes(self) -> List[APIRouter]:
        from app.addons.tools.articles.routes import admin_router

        return [admin_router]

    def get_admin_templates(self) -> str:
        return str(Path(__file__).resolve().parent / "templates")
