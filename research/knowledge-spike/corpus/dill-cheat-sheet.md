# dill Cheat Sheet

## Installation
```bash
pip install dill
```

## Core API (pickle-compatible)
```python
import dill

# Serialize to file
with open("snapshot.pkl", "wb") as f:
    dill.dump(obj, f)

# Deserialize from file
with open("snapshot.pkl", "rb") as f:
    obj = dill.load(f)

# Serialize to bytes
data = dill.dumps(obj)
obj = dill.loads(data)
```

## Session Persistence (key for this project)
```python
# Save entire interpreter session to file
dill.dump_module("session.pkl")

# Restore session from file
dill.load_module("session.pkl")

# Save specific module's state
import my_module
dill.dump_module("state.pkl", module=my_module)

# Load as dict (for selective restore)
state = dill.load_module_asdict("session.pkl")
```

## Detecting Non-Serializable Objects
```python
from dill import detect

# Find items that can't be pickled
bad = detect.baditems(obj)

# Get specific errors
errors = detect.errors(obj)

# Trace pickling (debug)
with detect.trace():
    dill.dumps(obj)
```

## What dill handles that pickle doesn't
- Lambda expressions
- Nested/closure functions
- Interactively-defined classes and functions
- Generator objects (partial support)
- Partial functions (functools.partial)

## Common patterns for snapshot endpoints
```python
import dill
import io

# Save kernel globals to bytes (for HTTP endpoint)
def save_state(namespace: dict) -> bytes:
    # Filter out non-serializable items
    safe = {}
    for k, v in namespace.items():
        if k.startswith("_"):
            continue
        try:
            dill.dumps(v)
            safe[k] = v
        except Exception:
            pass  # skip non-serializable
    return dill.dumps(safe)

# Restore from bytes
def restore_state(data: bytes) -> dict:
    return dill.loads(data)
```

## Pitfalls
- Open file handles, sockets, and DB connections are NOT serializable
- Large numpy arrays serialize fine but can produce huge snapshots
- dill.dump_module captures __main__ by default — not what you want in a FastAPI server
- For kernel namespace: serialize the dict of globals, not the module itself
- Always wrap dill.load in try/except for corrupt file handling
