"""FastAPI server wrapping the IPython kernel."""

from typing import Any
from fastapi import FastAPI
from pydantic import BaseModel
from sandbox.repl import Kernel

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
