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
- **Optional:** `PUID` / `PGID` — if set, beets runs as this user/group so
  imported files are owned by that user from the start. Use `id -u` / `id -g`
  to find your host user's values. When set, the app also chowns `MUSIC_DIR`
  to `PUID:PGID` at startup (top-level only, not recursive).

### 2. Configure beets

Copy `beets-config.yaml` to your beets config path and adjust:
- `directory` — must match `MUSIC_DIR`
- Enable/disable plugins as needed

The config supports `${MUSIC_DIR}` and `${BEETS_DIR}` placeholders which are
substituted at runtime from the corresponding environment variables.

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
image: ghcr.io/cuibonobo/dropzone:latest
```

## Development

The app runs inside a VS Code devcontainer (see `.devcontainer/devcontainer.json`).
Port 8000 is forwarded to the host, and uvicorn starts automatically with
`--reload` on container start.

Devcontainer credentials (set in `remoteEnv`):
- Username: `admin`
- Password: `dev`

Test an upload from the host:
```bash
curl -u admin:dev \
  -F "workflow=music" \
  -F "file=@/path/to/album.zip" \
  http://localhost:8000/upload
```

Instance data (music, books, beets database, etc.) lives in `instance/` which
is part of the bind-mounted workspace and persists across container restarts.

## Security

- HTTP Basic Auth over HTTPS (enforced by reverse proxy)
- Use a strong random password: `openssl rand -base64 24`
- All credentials via environment variables, never baked into the image

## Troubleshooting

### Music import permission errors

When `PUID`/`PGID` are set, beets runs as an unprivileged user. Several
things must be true for this to work:

- **`MUSIC_DIR` must be writable by `PUID:PGID`.** The app chowns it at
  startup, but if the directory was just created by root (e.g. first run),
  you may need to restart the container once so `startup_checks` can run.
- **The beets config file must be readable.** The app writes a resolved
  temp config and chmods it to `0o644` before passing it to beets.
- **The extracted zip contents must be owned by `PUID:PGID`.** Beets
  *moves* files (copy + unlink), and unlinking requires write permission on
  the source directory. The app chowns the extracted tree before running
  beets.

### Duplicate file suffixes (`.1.mp3`, `.2.mp3`, …)

Beets appends a numeric suffix when it finds a track already in its database.
If you want to re-import an album from scratch, clear the beets state:

```bash
rm instance/beets/library.db instance/beets/import.log
```

Then delete any previously imported files and retry.

### Beets not found

Ensure `beet` is installed in the container. Check `requirements.txt` and
rebuild the image if needed.

## Adding workflows

Add a new tab in `index.html` and a new `elif workflow == "..."` branch in
`main.py`.
