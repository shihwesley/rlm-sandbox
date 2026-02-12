"""FastAPI server wrapping the IPython kernel."""

import base64
import logging
from typing import Any

import dill
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from sandbox.repl import Kernel

log = logging.getLogger(__name__)

app = FastAPI()
kernel = Kernel()


# -- Models --

class ExecRequest(BaseModel):
    code: str
    timeout: int | None = 30


class ExecResponse(BaseModel):
    output: str
    stderr: str
    vars: list[str]


class VarInfo(BaseModel):
    name: str
    type: str
    summary: str


class VarValue(BaseModel):
    value: Any = None
    error: str | None = None


# -- Routes --

@app.post("/exec", response_model=ExecResponse)
def exec_code(req: ExecRequest):
    result = kernel.execute(req.code, timeout=req.timeout or 30)
    return ExecResponse(**result)


@app.get("/vars", response_model=list[VarInfo])
def list_vars():
    return [VarInfo(**v) for v in kernel.get_vars()]


@app.get("/var/{name}", response_model=VarValue)
def get_var(name: str):
    result = kernel.get_var(name)
    return VarValue(**result)


@app.get("/health")
def health():
    return {"status": "ok"}


# -- Snapshot endpoints --

@app.post("/snapshot/save")
def snapshot_save():
    """Serialize user namespace via dill, return base64-encoded bytes."""
    ns = kernel.shell.user_ns
    hidden = kernel.shell.user_ns_hidden
    serializable = {}
    skipped = []

    for k, v in ns.items():
        if k.startswith("_") or k in hidden:
            continue
        try:
            dill.dumps(v)
            serializable[k] = v
        except Exception:
            skipped.append(k)
            log.warning("Skipped non-serializable var: %s (%s)", k, type(v).__name__)

    data = dill.dumps(serializable)
    encoded = base64.b64encode(data).decode("ascii")
    return {"snapshot": encoded, "saved": list(serializable.keys()), "skipped": skipped}


@app.post("/snapshot/restore")
def snapshot_restore(payload: dict):
    """Restore user namespace from base64-encoded dill bytes."""
    encoded = payload.get("snapshot")
    if not encoded:
        return JSONResponse(status_code=400, content={"error": "missing snapshot field"})

    try:
        data = base64.b64decode(encoded)
        namespace: dict = dill.loads(data)
    except Exception as e:
        log.warning("Failed to deserialize snapshot: %s", e)
        return JSONResponse(
            status_code=400,
            content={"error": f"corrupt snapshot: {e}", "restored": []},
        )

    restored = []
    for k, v in namespace.items():
        kernel.shell.user_ns[k] = v
        restored.append(k)

    return {"restored": restored}
