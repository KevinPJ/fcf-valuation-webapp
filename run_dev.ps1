$ErrorActionPreference = "Stop"

$port = if ($env:PORT) { $env:PORT } else { "8000" }
uvicorn backend.main:app --reload --host 127.0.0.1 --port $port
