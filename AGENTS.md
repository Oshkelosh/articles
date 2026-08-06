# Articles (`articles`) — AGENTS

## Role

Lean Markdown articles hub for the storefront (intro + several posts). Addon ID: `articles`. Not a full CMS.

## File map

- `README.md`
- `__init__.py`
- `addon.py`
- `config.py`
- `store.py`
- `markdown_util.py`
- `oshkelosh-addon.json`
- `routes.py`
- `templates/`
- `tests/`

## Package specifics

**Category ceiling:** Many tools may be active.
**Storage:** object storage via `get_storage()` — `articles/manifest.json`, `articles/hub.md`, `articles/{id}/body.md` (same backend as product images). `addon_configs` is enable-only.
**Seams:** `list_storefront_nav_links`, `resolve_seo_meta`, `list_sitemap_entries` → core discovery/SEO.
**Public API:** `/api/v1/tools/articles/hub`, `/api/v1/tools/articles/posts/{slug}`
**Cache:** manifest + bodies loaded on `initialize` / after admin writes so SEO stays sync.

## Invariants

- Implement `ToolAddon`; do not patch host `app/services/*.py` with provider branches
- No categories, tags, comments, RSS, or media library
- Admin mutating forms need CSRF; use `render_addon_admin_page` correctly (do not pass `flash` via `**_common_ctx`)
- Nested `.git` (if present): this package is its own repo; the host gitignores this directory

## Prefer / Avoid

- Prefer: storage keys for content; thin manifest metadata
- Avoid: embedding post bodies in `addon_configs`; host SQLModel tables for posts

## See also

- [README.md](README.md)
- [../README.md](../README.md)
- [../../AGENTS.md](../../AGENTS.md)
- [../../../../AGENTS.md](../../../../AGENTS.md)
