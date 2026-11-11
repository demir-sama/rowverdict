"""Authenticated, profile-scoped review workflows. Deliberately NO export route.

Planning/replay only persist review state. No clean/quarantine/report artifact is
published by POST routes. Download reports from approved exports or marked previews.
"""
import base64
import hashlib
import importlib.util
import os
import sys
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

# An isolated package namespace supports relative imports without altering sys.path
# or replacing a global module named core. Hermes exposes only the public APIs used
# by this adjacent package. Resolve active profile settings anew on every request.
_root = Path(__file__).resolve().parents[1]
# Distinct source roots/versions must not reuse another profile's cached core.
_source = b"\0".join((_root / name).read_bytes() for name in ("__init__.py", "core.py", "formats.py", "drafting.py", "audit.py"))
_package_name = "_rowverdict_dashboard_" + hashlib.sha256(str(_root).encode() + b"\0" + _source).hexdigest()[:24]
spec = importlib.util.spec_from_file_location(_package_name, _root / "__init__.py", submodule_search_locations=[str(_root)])
package = importlib.util.module_from_spec(spec)
sys.modules[_package_name] = package
spec.loader.exec_module(package)
core = package.core
router = APIRouter()


def app_engine():
    return package.engine()


def invoke(call):
    try:
        return call(app_engine())
    except core.Refusal as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except (OSError, ValueError, TypeError, KeyError):
        raise HTTPException(status_code=400, detail="Could not process local RowVerdict request; check input paths, settings and state") from None


class Body(BaseModel):
    model_config = {"extra": "forbid"}


class Inspect(Body):
    source: str = Field(max_length=4096)
    delimiter: str = ","
    sheet: str | None = Field(default=None, max_length=100)


class Draft(Inspect):
    sample_rows: int = Field(default=1000, ge=1, le=1000)


class Review(Body):
    contract: dict
    expected_source_sha256: str = Field(min_length=64, max_length=64)
    acknowledgement: str


class Plan(Body):
    source: str = Field(max_length=4096)
    contract: dict | None = None
    draft_id: str | None = None


class Replay(Body):
    patch: list | None = None
    patch_file: str | None = Field(default=None, max_length=4096)
    preview: bool = False


class Upload(Body):
    filename: str = Field(min_length=1, max_length=120)
    content_base64: str = Field(max_length=28_000_000)


@router.get("/runs")
def runs():
    return invoke(lambda app: {"runs": app.history(40), "export_via_host_only": True, "version": core.VERSION,
                               "uploads_enabled": str(app.data_dir / "uploads") in [str(p) for p in app.allowed_roots],
                               "max_upload_bytes": core.MAX_BYTES})


@router.get("/runs/{plan_id}")
def run(plan_id: str):
    return invoke(lambda app: app.get(plan_id))


@router.post("/runs/{plan_id}/check")
def check(plan_id: str):
    return invoke(lambda app: app.check(plan_id))


@router.post("/inspect")
def inspect(body: Inspect):
    return invoke(lambda app: app.inspect(body.source, body.delimiter, body.sheet))


@router.post("/drafts")
def draft(body: Draft):
    return invoke(lambda app: app.draft(body.source, body.delimiter, body.sheet, body.sample_rows))


@router.post("/drafts/{draft_id}/review")
def review(draft_id: str, body: Review):
    def operation(app):
        draft = app.get_draft(draft_id)
        if body.acknowledgement != "I reviewed this exact contract" or body.expected_source_sha256 != draft["source_sha256"]:
            raise core.Refusal("DRAFT_REVIEW: explicit operator acknowledgement and exact source hash required")
        return app.review_draft(draft_id, body.contract)
    return invoke(operation)


@router.post("/plans")
def plan(body: Plan):
    return invoke(lambda app: app.plan(body.source, body.contract, body.draft_id))


@router.post("/runs/{plan_id}/replays")
def replay(plan_id: str, body: Replay):
    # This creates a review plan only. Its artifacts STILL require native tool approval.
    return invoke(lambda app: app.replay(plan_id, body.patch, body.patch_file, body.preview))


@router.get("/runs/{plan_id}/quarantine")
def quarantine(plan_id: str, offset: int = 0, limit: int = 50, query: str = "", code: str = ""):
    return invoke(lambda app: app.quarantine(plan_id, offset, limit, query, code))


@router.get("/runs/{plan_id}/report")
def report(plan_id: str):
    return invoke(lambda app: {"filename": "rowverdict-" + plan_id + "-audit.html", "html": app.report(plan_id)})


@router.post("/inputs")
def upload(body: Upload):
    def operation(app):
        folder = app.data_dir / "uploads"
        if folder not in app.allowed_roots:
            raise core.Refusal("UPLOADS: disabled; operator must explicitly enable allow_dashboard_uploads")
        name = body.filename
        if Path(name).name != name or "\\" in name or any(ord(c) < 32 for c in name) or name.lower() in {"credentials.json", "auth.json"} or name.startswith(".") or Path(name).suffix.lower() not in (".csv", ".xlsx", ".json", ".jsonl", ".ndjson"):
            raise core.Refusal("UPLOADS: invalid or unsupported input filename")
        try:
            data = base64.b64decode(body.content_base64, validate=True)
        except ValueError:
            raise core.Refusal("UPLOADS: invalid base64 payload") from None
        if len(data) > core.MAX_BYTES:
            raise core.Refusal("LIMIT: upload exceeds 20 MiB")
        core.private_dir(folder)
        if sum(1 for _ in folder.iterdir()) >= 100:
            raise core.Refusal("UPLOADS: 100-file limit; operator must archive inputs before adding more")
        path = folder / (uuid.uuid4().hex + "-" + name)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        return {"source": str(path), "bytes": len(data), "source_sha256": core.digest(data), "local_only": True}
    return invoke(operation)
