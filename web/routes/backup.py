"""Routes for the backup/restore stage."""

from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from web import config
from web.services import backup_service, service_control

router = APIRouter()
templates = Jinja2Templates(directory=str(config.ROOT / "web" / "templates"))


def _redirect(target: str, *, message: str | None = None, error: str | None = None) -> RedirectResponse:
    params: dict[str, str] = {}
    if message:
        params["message"] = message
    if error:
        params["error"] = error
    qs = f"?{urlencode(params)}" if params else ""
    return RedirectResponse(url=f"{target}{qs}", status_code=303)


@router.get("/", response_class=HTMLResponse)
def home(request: Request, message: str | None = None, error: str | None = None):
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "active": "home",
            "message": message,
            "error": error,
            "game_db_exists": config.GAME_DB_PATH.exists(),
            "game_db_path": config.GAME_DB_PATH,
            "lunar_tear_running": backup_service.detect_lunar_tear_running(),
            "service_control_available": service_control.available(),
            "service_unit": service_control.UNIT_NAME,
            "app_version": config.APP_VERSION,
        },
    )


@router.get("/backups", response_class=HTMLResponse)
def list_backups(request: Request, message: str | None = None, error: str | None = None):
    return templates.TemplateResponse(
        request,
        "backup.html",
        {
            "active": "backups",
            "message": message,
            "error": error,
            "backups": backup_service.list_backups(),
            "retention": config.BACKUP_RETENTION,
            "game_db_exists": config.GAME_DB_PATH.exists(),
            "game_db_path": config.GAME_DB_PATH,
            "lunar_tear_running": backup_service.detect_lunar_tear_running(),
            "service_control_available": service_control.available(),
            "service_control_reason": (
                None if service_control.available()
                else service_control.unavailable_reason()
            ),
            "service_unit": service_control.UNIT_NAME,
        },
    )


@router.post("/backups/create")
def create_backup_action():
    try:
        info = backup_service.create_backup(reason="manual")
    except FileNotFoundError as e:
        return _redirect("/backups", error=str(e))
    except Exception as e:
        return _redirect("/backups", error=f"Backup failed: {e}")
    return _redirect("/backups", message=f"Created {info.filename} ({info.size_human}).")


@router.post("/backups/restore")
def restore_backup_action(
    filename: str = Form(...),
    confirm: str = Form(...),
    manage_server: str = Form(default=""),
):
    """Restore a backup, optionally stopping and restarting lunar-tear.

    `manage_server` arrives as the checkbox value ("on") or empty. When
    set, the service is stopped, the swap performed, and the service
    started again — the manual sequence, automated.
    """
    if confirm.strip() != "RESTORE":
        return _redirect(
            "/backups",
            error="Confirmation phrase did not match. Type RESTORE in uppercase to confirm.",
        )

    wants_service_control = bool(manage_server.strip())
    if wants_service_control and not service_control.available():
        return _redirect("/backups", error=service_control.unavailable_reason())

    try:
        result = backup_service.restore_backup(
            filename, manage_server=wants_service_control
        )
    except backup_service.RestoreBlocked as e:
        return _redirect("/backups", error=str(e))
    except service_control.ServiceError as e:
        # The server may or may not be running now; say so rather than
        # implying a clean outcome.
        return _redirect(
            "/backups",
            error=f"Server control failed: {e} Check the service state before continuing.",
        )
    except FileNotFoundError as e:
        return _redirect("/backups", error=str(e))
    except Exception as e:
        return _redirect("/backups", error=f"Restore failed: {e}")

    parts = [f"Restored from {result.source.filename}."]
    if result.steps:
        parts.append(" ".join(f"{s}." for s in result.steps))
    if result.server_restarted:
        parts.append("Game server is back up.")
    return _redirect("/backups", message=" ".join(parts))
