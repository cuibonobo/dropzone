# dropzone

A lightweight self-hosted web app for dispatching files and text snippets to
your home server workflows. Built with FastAPI.

## Workflows

| Tab | Input | Action |
|-----|-------|--------|
| Music | `.zip` | Extract → beets import (auto-tag + organize) → Navidrome rescan |
| Books | `.epub`, `.pdf`, `.mobi` | Copy to books folder |
| Inbox | Any file | Copy to inbox folder (sync to desktop via Syncthing) |
| Text | Text snippet | Append to a text file |

## Setup

### 1. Configure environment

Copy `docker-compose.yml` and fill in:

- `DROPZONE_PASSWORD` — use a strong password, this is internet-facing
- Volume paths — map your host directories to the container paths
- `NAVIDROME_URL` / `NAVIDROME_USER` / `NAVIDROME_PASSWORD`

### 2. Configure beets

Copy `beets-config.yaml` to your beets config path and adjust:
- `directory` — must match `MUSIC_DIR`
- Enable/disable plugins as needed

The `chroma` plugin (acoustic fingerprinting) gives much better matches for
non-English metadata. Install `chromaprint` on the host or in the container.

### 3. Deploy

```bash
docker compose up -d
```

Put a reverse proxy (nginx, Caddy, Traefik) in front on port 443 with a valid
TLS cert. Do not expose port 8000 directly to the internet.

### 4. GitHub Container Registry (optional)

Push to your own fork and GitHub Actions will build and publish to GHCR
automatically on every push to `main`.

Update the image name in `docker-compose.yml`:
```yaml
image: ghcr.io/YOURUSERNAME/dropzone:latest
```

## Security

- HTTP Basic Auth over HTTPS (enforced by reverse proxy)
- Use a strong random password: `openssl rand -base64 24`
- All credentials via environment variables, never baked into the image

## Adding workflows

Add a new tab in `templates/index.html` and a new `elif workflow == "..."` 
branch in `app/main.py`.
