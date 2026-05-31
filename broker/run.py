"""Run the broker with the wsproto WebSocket implementation.

uvicorn's default `websockets` implementation rejects the browser's kernel
WebSocket handshake with HTTP 400 (it chokes on Chrome's
`permessage-deflate; client_max_window_bits` extension offer) BEFORE the request
reaches the app — so kernels never connect and cells never run. `wsproto`
negotiates the browser handshake correctly. Always start the broker via this
script (or pass `--ws wsproto` to uvicorn) so the WS proxy works in browsers.

    python run.py            # 127.0.0.1:8000
    PORT=9000 HOST=0.0.0.0 python run.py   # expose on the LAN (any device)
"""
import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
        ws="wsproto",
    )
