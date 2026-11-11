"""Read-only dashboard API, authenticated/profile-scoped by the Hermes host.

No export endpoint: the dashboard cannot bypass the native export approval gate.
"""
import importlib.util
from pathlib import Path

from fastapi import APIRouter, HTTPException
from plugins.plugin_storage import plugin_data_dir

# Load only our own adjacent reviewable source; no sys.path or core-module mutation.
spec = importlib.util.spec_from_file_location("rowverdict_dashboard_core", Path(__file__).resolve().parents[1] / "core.py")
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)
router = APIRouter()


def app_engine():
    # Resolve for each request, never cache an active profile's storage directory.
    return core.Engine(plugin_data_dir("rowverdict"))


@router.get("/runs")
def runs():
    try:
        return {"runs": app_engine().history(40), "read_only": True, "version": core.VERSION}
    except (OSError, ValueError):
        raise HTTPException(status_code=400, detail="Could not read local RowVerdict state") from None


@router.get("/runs/{plan_id}")
def run(plan_id: str):
    try:
        return app_engine().get(plan_id)
    except core.Refusal:
        raise HTTPException(status_code=404, detail="Plan not found") from None
