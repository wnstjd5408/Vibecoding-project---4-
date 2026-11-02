"""Operator-only experiment endpoints, disabled outside staging Preview."""
import json
import os
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response
from starlette.concurrency import run_in_threadpool

from app.auth import require_operator
from app.errors import ApiError
from evals import staging
from evals.live_auth import oidc_transport
from evals.schema import DatasetError
from evals.shared_ledger import SharedLedger


def require_staging():
    if (os.getenv("VERCEL_ENV") != "preview" or os.getenv("VERCEL_GIT_COMMIT_REF") != "staging"
            or not os.getenv("EVAL_APPROVAL_ID") or os.getenv("AI_AUTH_MODE", "oidc") != "oidc"):
        raise ApiError("not_found")


router = APIRouter(prefix="/api/internal/evals", include_in_schema=False,
                   dependencies=[Depends(require_staging), Depends(require_operator)])


@router.get("/console", response_class=HTMLResponse)
def console():
    return HTMLResponse((Path(staging.__file__).parent / "console.html").read_text(encoding="utf-8"),
        headers={"Content-Security-Policy": "default-src 'none'; script-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'",
                 "X-Content-Type-Options": "nosniff"})


@router.get("/console.js")
def console_script():
    return Response((Path(staging.__file__).parent / "console.js").read_text(encoding="utf-8"),
                    media_type="text/javascript", headers={"X-Content-Type-Options": "nosniff"})


async def bundle_from(request):
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > 2_000_000:
            raise ApiError("payload_too_large")
    try:
        return staging.prepare_bundle(json.loads(data))
    except (ValueError, TypeError, RecursionError):
        raise ApiError("validation_failed") from None


def dispatch(bundle, action, slot=None):
    ledger = None
    transport = None
    try:
        ledger = SharedLedger.from_env()
        state, approval = staging.checked_state(bundle, ledger)
        if action == "status":
            return state
        pending = staging.next_slot(state, approval)
        if action == "run" and (slot != pending or slot not in staging.SLOTS):
            raise DatasetError("live: slot_not_pending")
        # STS credential exchange only; preflight never invokes Converse or reserves a slot.
        transport = oidc_transport()
        if action == "preflight":
            return {"ready": pending is not None, "next_slot": pending,
                    "provider_calls": state["provider_calls"], "model_access": "unverified"}
        return staging.execute_slot(bundle, ledger, slot, transport)
    except (DatasetError, ValueError, TypeError, KeyError, ArithmeticError):
        # Do not expose source material, credentials or remote exception messages.
        raise ApiError("service_unavailable", stage="ai") from None
    finally:
        if transport is not None:
            transport.client.close()
        if ledger is not None:
            ledger.client.close()


@router.post("/preflight")
async def preflight(request: Request):
    return await run_in_threadpool(dispatch, await bundle_from(request), "preflight")


@router.post("/status")
async def status(request: Request):
    return await run_in_threadpool(dispatch, await bundle_from(request), "status")


@router.post("/run/{slot}")
async def run_slot(slot: str, request: Request):
    return await run_in_threadpool(dispatch, await bundle_from(request), "run", slot)
