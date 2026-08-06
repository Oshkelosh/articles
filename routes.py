"""Articles tool addon admin + public API routes."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError

from app.addons.admin_helpers import (
    make_addon_jinja_env,
    render_addon_admin_page,
    require_addon_csrf,
    save_addon_from_form,
)
from app.addons.registry import addon_registry
from app.addons.tools.articles.addon import ArticlesToolAddon
from app.addons.tools.articles.config import ArticleMeta, ArticlesManifest
from app.addons.tools.articles import store as articles_store
from app.admin.routes import require_admin_session
from app.admin.session import set_flash_cookie
from app.storage import get_storage

_CONFIGURE_URL = "/admin/tools/articles"
_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

jinja_env = make_addon_jinja_env(_TEMPLATES_DIR)
admin_router = APIRouter()
api_router = APIRouter()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        parts = []
        for err in exc.errors():
            loc = ".".join(str(p) for p in err.get("loc", ()))
            msg = err.get("msg", "invalid")
            parts.append(f"{loc}: {msg}" if loc else msg)
        return "; ".join(parts) or str(exc)
    return str(exc)


def _slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.strip().lower()).strip("-")
    return slug or "post"


def _get_articles_addon(*, require_enabled: bool = True) -> ArticlesToolAddon | None:
    addon = addon_registry.get("articles")
    if addon is None or not isinstance(addon, ArticlesToolAddon):
        return None
    if require_enabled and not addon.is_enabled:
        return None
    return addon


async def _page(
    request: Request,
    *,
    flash: str | None = None,
    flash_type: str = "info",
    form_error: str | None = None,
    edit_post: dict[str, Any] | None = None,
    form_values: dict[str, Any] | None = None,
    show_new: bool = False,
) -> HTMLResponse:
    addon = addon_registry.get("articles")
    articles = addon if isinstance(addon, ArticlesToolAddon) else None
    if articles is not None and articles.is_enabled:
        await articles.reload_cache()
        hub = articles.hub_fields()
        posts = articles.all_posts_for_admin()
    else:
        storage = get_storage()
        manifest = await articles_store.load_manifest(storage)
        hub = {
            "intro_title": manifest.intro_title,
            "intro_markdown": await articles_store.load_hub_markdown(storage),
            "meta_title": manifest.meta_title,
            "meta_description": manifest.meta_description,
        }
        posts = []
        for meta in manifest.posts:
            data = meta.model_dump(mode="json")
            data["body_markdown"] = await articles_store.load_body(meta.id, storage)
            posts.append(data)
    posts.sort(key=lambda p: p.get("updated_at") or "", reverse=True)
    template = "article_edit.html" if (edit_post is not None or show_new) else "articles_list.html"
    return HTMLResponse(
        content=render_addon_admin_page(
            jinja_env,
            request,
            template,
            "Articles",
            flash=flash or form_error,
            flash_type="error" if form_error else flash_type,
            addon=addon,
            config=hub,
            posts=posts,
            edit_post=edit_post,
            form_values=form_values or {},
            is_new=show_new,
        ),
    )


@admin_router.get("")
async def articles_list_page(request: Request, db=Depends(require_admin_session)):
    return await _page(request)


@admin_router.get("/", include_in_schema=False)
async def articles_trailing_slash_redirect():
    return RedirectResponse(url=_CONFIGURE_URL, status_code=307)


@admin_router.get("/new")
async def articles_new_page(request: Request, db=Depends(require_admin_session)):
    return await _page(request, show_new=True)


@admin_router.get("/{post_id}/edit")
async def articles_edit_page(
    post_id: str,
    request: Request,
    db=Depends(require_admin_session),
):
    storage = get_storage()
    manifest = await articles_store.load_manifest(storage)
    meta = next((p for p in manifest.posts if p.id == post_id), None)
    if meta is None:
        return await _page(request, form_error="Post not found")
    post = meta.model_dump(mode="json")
    post["body_markdown"] = await articles_store.load_body(post_id, storage)
    return await _page(request, edit_post=post)


@admin_router.post("/settings")
async def articles_save_settings(request: Request, db=Depends(require_admin_session)):
    form = await request.form()
    require_addon_csrf(request, str(form.get("csrf_token", "")))
    enabled = form.get("is_enabled") == "on"
    storage = get_storage()
    try:
        manifest = await articles_store.load_manifest(storage)
        manifest.intro_title = (
            str(form.get("intro_title") or "Articles").strip() or "Articles"
        )
        manifest.meta_title = str(form.get("meta_title") or "").strip() or None
        manifest.meta_description = (
            str(form.get("meta_description") or "").strip() or None
        )
        ArticlesManifest.model_validate(manifest.model_dump())
        await articles_store.save_manifest(manifest, storage)
        await articles_store.save_hub_markdown(
            str(form.get("intro_markdown") or ""), storage
        )
        # Clear any legacy posts from addon_configs; content is in storage.
        resp = await save_addon_from_form(
            db,
            "articles",
            {},
            enabled=enabled,
            redirect_url=_CONFIGURE_URL,
            flash_message="Articles settings saved",
        )
        articles = _get_articles_addon(require_enabled=False)
        if articles is not None and articles.is_enabled:
            await articles.reload_cache()
        return resp
    except Exception as exc:
        return await _page(
            request, form_error=f"Error saving settings: {_format_error(exc)}"
        )


@admin_router.post("/add")
async def articles_add(request: Request, db=Depends(require_admin_session)):
    form = await request.form()
    require_addon_csrf(request, str(form.get("csrf_token", "")))
    title = str(form.get("title") or "").strip()
    slug = str(form.get("slug") or "").strip().lower() or _slugify(title)
    published = form.get("published") == "on"
    now = _utc_now()
    values = {
        "title": title,
        "slug": slug,
        "body_markdown": str(form.get("body_markdown") or ""),
        "meta_title": str(form.get("meta_title") or "").strip() or None,
        "meta_description": str(form.get("meta_description") or "").strip() or None,
        "published": published,
    }
    storage = get_storage()
    try:
        post = ArticleMeta(
            id=uuid.uuid4().hex[:16],
            slug=slug,
            title=title,
            meta_title=values["meta_title"],
            meta_description=values["meta_description"],
            published=published,
            published_at=now if published else None,
            updated_at=now,
        )
        manifest = await articles_store.load_manifest(storage)
        posts = list(manifest.posts) + [post]
        manifest = ArticlesManifest(
            intro_title=manifest.intro_title,
            meta_title=manifest.meta_title,
            meta_description=manifest.meta_description,
            posts=posts,
        )
        await articles_store.save_body(post.id, values["body_markdown"], storage)
        await articles_store.save_manifest(manifest, storage)
        articles = _get_articles_addon(require_enabled=False)
        if articles is not None and articles.is_enabled:
            await articles.reload_cache()
        resp = RedirectResponse(url=_CONFIGURE_URL, status_code=302)
        set_flash_cookie(resp, "Article created")
        return resp
    except Exception as exc:
        return await _page(
            request,
            show_new=True,
            form_error=_format_error(exc),
            form_values=values,
        )


@admin_router.post("/{post_id}/save")
async def articles_save(post_id: str, request: Request, db=Depends(require_admin_session)):
    form = await request.form()
    require_addon_csrf(request, str(form.get("csrf_token", "")))
    storage = get_storage()
    manifest = await articles_store.load_manifest(storage)
    idx = next((i for i, p in enumerate(manifest.posts) if p.id == post_id), None)
    if idx is None:
        return await _page(request, form_error="Post not found")

    existing = manifest.posts[idx]
    title = str(form.get("title") or "").strip()
    slug = str(form.get("slug") or "").strip().lower() or _slugify(title)
    published = form.get("published") == "on"
    now = _utc_now()
    was_published = bool(existing.published)
    published_at = existing.published_at
    if published and not was_published:
        published_at = now
    elif not published:
        published_at = None

    values = {
        "title": title,
        "slug": slug,
        "body_markdown": str(form.get("body_markdown") or ""),
        "meta_title": str(form.get("meta_title") or "").strip() or None,
        "meta_description": str(form.get("meta_description") or "").strip() or None,
        "published": published,
    }
    try:
        post = ArticleMeta(
            id=post_id,
            slug=slug,
            title=title,
            meta_title=values["meta_title"],
            meta_description=values["meta_description"],
            published=published,
            published_at=published_at,
            updated_at=now,
        )
        posts = list(manifest.posts)
        posts[idx] = post
        updated = ArticlesManifest(
            intro_title=manifest.intro_title,
            meta_title=manifest.meta_title,
            meta_description=manifest.meta_description,
            posts=posts,
        )
        await articles_store.save_body(post_id, values["body_markdown"], storage)
        await articles_store.save_manifest(updated, storage)
        articles = _get_articles_addon(require_enabled=False)
        if articles is not None and articles.is_enabled:
            await articles.reload_cache()
        resp = RedirectResponse(url=_CONFIGURE_URL, status_code=302)
        set_flash_cookie(resp, "Article saved")
        return resp
    except Exception as exc:
        return await _page(
            request,
            edit_post={**existing.model_dump(mode="json"), "id": post_id},
            form_error=_format_error(exc),
            form_values=values,
        )


@admin_router.post("/{post_id}/delete")
async def articles_delete(
    post_id: str, request: Request, db=Depends(require_admin_session)
):
    form = await request.form()
    require_addon_csrf(request, str(form.get("csrf_token", "")))
    storage = get_storage()
    try:
        manifest = await articles_store.load_manifest(storage)
        posts = [p for p in manifest.posts if p.id != post_id]
        updated = ArticlesManifest(
            intro_title=manifest.intro_title,
            meta_title=manifest.meta_title,
            meta_description=manifest.meta_description,
            posts=posts,
        )
        await articles_store.delete_body(post_id, storage)
        await articles_store.save_manifest(updated, storage)
        articles = _get_articles_addon(require_enabled=False)
        if articles is not None and articles.is_enabled:
            await articles.reload_cache()
        resp = RedirectResponse(url=_CONFIGURE_URL, status_code=302)
        set_flash_cookie(resp, "Article deleted")
        return resp
    except Exception as exc:
        return await _page(
            request, form_error=f"Error deleting: {_format_error(exc)}"
        )


@api_router.get("/hub")
async def articles_hub():
    addon = _get_articles_addon()
    if addon is None:
        raise HTTPException(status_code=404, detail="Articles is not enabled")
    payload = addon.hub_payload()
    if payload is None:
        raise HTTPException(status_code=404, detail="Articles is not enabled")
    return payload


@api_router.get("/")
async def articles_hub_root():
    return await articles_hub()


@api_router.get("/posts/{slug}")
async def articles_post(slug: str):
    if not _SLUG_RE.match(slug):
        raise HTTPException(status_code=404, detail="Article not found")
    addon = _get_articles_addon()
    if addon is None:
        raise HTTPException(status_code=404, detail="Article not found")
    post = addon.get_published_post(slug)
    if post is None:
        raise HTTPException(status_code=404, detail="Article not found")
    return {
        "slug": post["slug"],
        "title": post["title"],
        "body_markdown": post.get("body_markdown") or "",
        "meta_title": post.get("meta_title"),
        "meta_description": post.get("meta_description"),
        "published_at": post.get("published_at"),
        "updated_at": post.get("updated_at"),
    }
