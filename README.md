# Articles tool

Simple Markdown articles for the storefront: a hub at `/articles` plus individual posts at `/articles/{slug}`.

## Install

Clone or ZIP-install into `app/addons/tools/articles/` (gitignored by the host). Enable under **Admin → Tools**. Restart the app after install (`data/restart.flag` + watcher).

## Storage

Content uses the host media backend (local `data/uploads/` or R2), same as product images:

| Key | Content |
|-----|---------|
| `articles/manifest.json` | Hub title/meta + post index (no bodies) |
| `articles/hub.md` | Hub intro Markdown |
| `articles/{id}/body.md` | Post body Markdown |

`addon_configs` only tracks whether the addon is enabled. Legacy configs that still embed `posts[]` are migrated into storage once on initialize.

## Admin

**Admin → Tools → Articles** (or `/admin/tools/articles`):

- Hub intro title / Markdown / optional meta
- Create, edit, delete posts (Markdown editor with live preview)
- Publish toggle — drafts stay out of the public API, SEO, and sitemap

## Storefront

When enabled, contributes:

- `tools.nav_links` → `{ label: "Articles", href: "/articles" }`
- SEO + sitemap entries via core tool discovery
- Public JSON:
  - `GET /api/v1/tools/articles/hub`
  - `GET /api/v1/tools/articles/posts/{slug}`

Bodies are Markdown; the default SPA renders them client-side.

## Ceiling

Intended for a handful of articles, not a blogging platform.
