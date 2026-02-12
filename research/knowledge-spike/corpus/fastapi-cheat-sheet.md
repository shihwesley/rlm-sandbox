# FastAPI Cheat Sheet

## Setup
```python
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()
```

## Routes with Pydantic models
```python
class ExecRequest(BaseModel):
    code: str
    timeout: int | None = None

class ExecResponse(BaseModel):
    output: str
    stderr: str
    vars: list[str]

@app.post("/exec")
async def exec_code(req: ExecRequest) -> ExecResponse:
    ...

@app.get("/vars")
async def get_vars() -> list[dict]:
    ...

@app.get("/var/{name}")
async def get_var(name: str) -> dict:
    ...

@app.get("/health")
async def health():
    return {"status": "ok"}
```

## Run with uvicorn
```python
import uvicorn
uvicorn.run(app, host="0.0.0.0", port=8080)
```

## Key patterns
- Path params: `@app.get("/var/{name}")` -> `def get_var(name: str)`
- Request body: Pydantic model as param -> auto-parsed from JSON
- Response: return dict or model -> auto-serialized to JSON
- Async: use `async def` for I/O-bound routes
