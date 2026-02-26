import os
import shutil
import secrets
import zipfile
import tempfile
import subprocess
from pathlib import Path
from typing import Annotated
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx
from fastapi import FastAPI, File, UploadFile, Form, Depends, HTTPException, status, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# ── Config from environment ──────────────────────────────────────────────────

DROPZONE_USER     = os.environ.get("DROPZONE_USER", "admin")
DROPZONE_PASSWORD = os.environ.get("DROPZONE_PASSWORD", "changeme")

MUSIC_DIR         = Path(os.environ.get("MUSIC_DIR", "/data/music"))
BOOKS_DIR         = Path(os.environ.get("BOOKS_DIR", "/data/books"))
INBOX_DIR         = Path(os.environ.get("INBOX_DIR", "/data/inbox"))
SNIPPETS_FILE     = Path(os.environ.get("SNIPPETS_FILE", "/data/snippets.txt"))

NAVIDROME_URL     = os.environ.get("NAVIDROME_URL", "http://navidrome:4533")
NAVIDROME_USER    = os.environ.get("NAVIDROME_USER", "admin")
NAVIDROME_PASSWORD= os.environ.get("NAVIDROME_PASSWORD", "")

BEETS_DIR         = os.environ.get("BEETS_DIR", "/config/beets")
BEETS_CONFIG      = os.environ.get("BEETS_CONFIG", f"{BEETS_DIR}/config.yaml")

PUID              = int(os.environ["PUID"]) if os.environ.get("PUID") else None
PGID              = int(os.environ["PGID"]) if os.environ.get("PGID") else None

TIMEZONE          = os.environ.get("TIMEZONE", "America/New_York")

# ── App setup ─────────────────────────────────────────────────────────────────

app = FastAPI(title="Dropzone")
security = HTTPBasic()
templates = Jinja2Templates(directory="/app")

@app.on_event("startup")
async def startup_checks():
    """Verify required directories and configuration files exist."""
    # Ensure upload directories exist
    ensure_dirs()
    
    # Ensure beets library directory exists
    Path(BEETS_DIR).mkdir(parents=True, exist_ok=True)
    
    if not Path(BEETS_CONFIG).exists():
        raise RuntimeError(f"Beets config file does not exist: {BEETS_CONFIG}")

# ── Auth ──────────────────────────────────────────────────────────────────────

def require_auth(credentials: Annotated[HTTPBasicCredentials, Depends(security)]):
    ok_user = secrets.compare_digest(credentials.username.encode(), DROPZONE_USER.encode())
    ok_pass = secrets.compare_digest(credentials.password.encode(), DROPZONE_PASSWORD.encode())
    if not (ok_user and ok_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

Auth = Annotated[str, Depends(require_auth)]

# ── Helpers ───────────────────────────────────────────────────────────────────

def ensure_dirs():
    for d in [MUSIC_DIR, BOOKS_DIR, INBOX_DIR]:
        d.mkdir(parents=True, exist_ok=True)
    SNIPPETS_FILE.parent.mkdir(parents=True, exist_ok=True)

def navidrome_rescan():
    """Trigger a Navidrome library rescan via its API."""
    try:
        # Navidrome uses subsonic-compatible API
        url = f"{NAVIDROME_URL}/rest/startScan.view"
        params = {
            "u": NAVIDROME_USER,
            "p": NAVIDROME_PASSWORD,
            "v": "1.16.1",
            "c": "dropzone",
            "f": "json",
        }
        with httpx.Client(timeout=10) as client:
            resp = client.get(url, params=params)
            resp.raise_for_status()
        return True, "Navidrome rescan triggered."
    except Exception as e:
        return False, f"Navidrome rescan failed: {e}"

def chown_music_dir() -> tuple[bool, str]:
    """Recursively chown MUSIC_DIR to PUID:PGID if configured."""
    if PUID is None or PGID is None:
        return True, ""
    try:
        os.chown(MUSIC_DIR, PUID, PGID)
        for item in MUSIC_DIR.rglob("*"):
            os.chown(item, PUID, PGID)
        return True, ""
    except OSError as e:
        return False, f"Warning: could not chown music files: {e}"

def import_music_with_beets(source_dir: Path) -> tuple[bool, str]:
    """Run beets import on a directory."""
    # beets does not reliably expand ${VAR} in config path values when the
    # variables aren't set in its environment.  Substitute them here in Python
    # and pass a resolved temporary config file so the paths are always literal.
    resolved_config = None
    try:
        with open(BEETS_CONFIG) as f:
            raw = f.read()
        resolved = raw.replace("${BEETS_DIR}", BEETS_DIR).replace("${MUSIC_DIR}", str(MUSIC_DIR))
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as tmp:
            tmp.write(resolved)
            resolved_config = tmp.name

        result = subprocess.run(
            ["beet", "--config", resolved_config, "import", "-q", str(source_dir)],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            text=True,
            timeout=300,
        )
        if result.returncode == 0:
            return True, result.stdout or "Beets import complete."
        else:
            detail = "\n".join(filter(None, [result.stderr, result.stdout]))
            return False, detail or "Beets import failed."
    except FileNotFoundError:
        return False, "beets not found — is it installed in the container?"
    except subprocess.TimeoutExpired:
        return False, "Beets import timed out after 5 minutes."
    except Exception as e:
        return False, str(e)
    finally:
        if resolved_config:
            try:
                os.unlink(resolved_config)
            except OSError:
                pass

# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, _: Auth):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/upload")
async def upload(
    _: Auth,
    workflow: Annotated[str, Form()],
    file: Annotated[UploadFile | None, File()] = None,
    text: Annotated[str | None, Form()] = None,
):
    ensure_dirs()

    if workflow == "text":
        if not text:
            return JSONResponse({"ok": False, "message": "No text provided."}, status_code=400)
        try:
            tz = ZoneInfo(TIMEZONE)
        except ZoneInfoNotFoundError:
            tz = ZoneInfo("UTC")
        timestamp = datetime.now(tz).replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S %Z")
        with SNIPPETS_FILE.open("a", encoding="utf-8") as f:
            f.write(text.strip() + "\n\n" + timestamp + "\n---\n\n")
        return JSONResponse({"ok": True, "message": "Text snippet appended successfully."})

    if not file:
        return JSONResponse({"ok": False, "message": "No file provided."}, status_code=400)

    filename = file.filename or "upload"

    if workflow == "music":
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir) / filename
            with tmp_path.open("wb") as f:
                shutil.copyfileobj(file.file, f)

            if not zipfile.is_zipfile(tmp_path):
                return JSONResponse({"ok": False, "message": "File is not a zip archive."}, status_code=400)

            extract_dir = Path(tmpdir) / "extracted"
            extract_dir.mkdir()
            with zipfile.ZipFile(tmp_path) as zf:
                zf.extractall(extract_dir)

            ok, msg = import_music_with_beets(extract_dir)
            if not ok:
                return JSONResponse({"ok": False, "message": msg})

            chown_music_dir()

            scan_ok, scan_msg = navidrome_rescan()
            final_msg = "Music imported successfully."
            if scan_ok:
                final_msg = "Music imported successfully. Navidrome rescan triggered."
            return JSONResponse({
                "ok": True,
                "message": final_msg,
            })

    elif workflow == "books":
        try:
            dest = BOOKS_DIR / filename
            file_content = await file.read()
            with dest.open("wb") as f:
                f.write(file_content)
            return JSONResponse({"ok": True, "message": "Book uploaded successfully."})
        except Exception as e:
            return JSONResponse({"ok": False, "message": f"Error saving book: {e}"}, status_code=500)

    elif workflow == "inbox":
        try:
            dest = INBOX_DIR / filename
            file_content = await file.read()
            with dest.open("wb") as f:
                f.write(file_content)
            return JSONResponse({"ok": True, "message": "File uploaded successfully."})
        except Exception as e:
            return JSONResponse({"ok": False, "message": f"Error saving to inbox: {e}"}, status_code=500)

    else:
        return JSONResponse({"ok": False, "message": f"Unknown workflow: {workflow}"}, status_code=400)

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/favicon.svg")
async def favicon():
    return FileResponse("/app/favicon.svg", media_type="image/svg+xml")
