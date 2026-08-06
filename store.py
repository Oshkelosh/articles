"""Object-storage helpers for the Articles tool (local or R2)."""

from __future__ import annotations

import json
from typing import Any

from app.addons.tools.articles.config import ArticleMeta, ArticlesManifest
from app.storage import StorageBackend, get_storage

MANIFEST_KEY = "articles/manifest.json"
HUB_KEY = "articles/hub.md"


def body_key(post_id: str) -> str:
    return f"articles/{post_id}/body.md"


async def download_text(storage: StorageBackend, key: str, default: str = "") -> str:
    try:
        raw = await storage.download(key)
    except FileNotFoundError:
        return default
    return raw.decode("utf-8")


async def upload_text(
    storage: StorageBackend,
    key: str,
    text: str,
    *,
    content_type: str = "text/plain; charset=utf-8",
) -> None:
    await storage.upload(key, text.encode("utf-8"), content_type)


async def load_manifest(storage: StorageBackend | None = None) -> ArticlesManifest:
    storage = storage or get_storage()
    try:
        raw = await storage.download(MANIFEST_KEY)
    except FileNotFoundError:
        return ArticlesManifest()
    data = json.loads(raw.decode("utf-8"))
    return ArticlesManifest.model_validate(data)


async def save_manifest(
    manifest: ArticlesManifest,
    storage: StorageBackend | None = None,
) -> None:
    storage = storage or get_storage()
    payload = manifest.model_dump(mode="json")
    await storage.upload(
        MANIFEST_KEY,
        json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8"),
        "application/json",
    )


async def load_hub_markdown(storage: StorageBackend | None = None) -> str:
    storage = storage or get_storage()
    return await download_text(storage, HUB_KEY, "")


async def save_hub_markdown(text: str, storage: StorageBackend | None = None) -> None:
    storage = storage or get_storage()
    await upload_text(storage, HUB_KEY, text, content_type="text/markdown; charset=utf-8")


async def load_body(post_id: str, storage: StorageBackend | None = None) -> str:
    storage = storage or get_storage()
    return await download_text(storage, body_key(post_id), "")


async def save_body(
    post_id: str,
    text: str,
    storage: StorageBackend | None = None,
) -> None:
    storage = storage or get_storage()
    await upload_text(
        storage,
        body_key(post_id),
        text,
        content_type="text/markdown; charset=utf-8",
    )


async def delete_body(post_id: str, storage: StorageBackend | None = None) -> None:
    storage = storage or get_storage()
    try:
        await storage.delete(body_key(post_id))
    except Exception:
        pass


async def migrate_legacy_config(
    config: dict[str, Any],
    storage: StorageBackend | None = None,
) -> ArticlesManifest | None:
    """If addon_configs still has embedded posts, write them to storage once.

    Returns the new manifest when migration ran, else None.
    """
    storage = storage or get_storage()
    posts_raw = config.get("posts")
    if not isinstance(posts_raw, list) or not posts_raw:
        return None

    # Prefer existing manifest if already present.
    try:
        await storage.download(MANIFEST_KEY)
        return None
    except FileNotFoundError:
        pass

    metas: list[ArticleMeta] = []
    for entry in posts_raw:
        if not isinstance(entry, dict):
            continue
        body = str(entry.get("body_markdown") or "")
        meta = ArticleMeta.model_validate(
            {k: v for k, v in entry.items() if k != "body_markdown"}
        )
        await save_body(meta.id, body, storage)
        metas.append(meta)

    intro_md = str(config.get("intro_markdown") or "")
    if intro_md:
        await save_hub_markdown(intro_md, storage)

    manifest = ArticlesManifest(
        intro_title=str(config.get("intro_title") or "Articles").strip() or "Articles",
        meta_title=config.get("meta_title") or None,
        meta_description=config.get("meta_description") or None,
        posts=metas,
    )
    await save_manifest(manifest, storage)
    return manifest
