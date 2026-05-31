"""Reverse proxy for notebook containers (HTTP + kernel WebSocket).

The browser talks only to the broker at /nb/<uuid>/... ; the broker forwards to
the notebook container (which serves under the same base_url) and injects the
container's Jupyter token, so the token never appears in the browser.
"""
import asyncio

import httpx
import websockets
from starlette.responses import Response, StreamingResponse
from starlette.websockets import WebSocket

_HOP = {"connection", "keep-alive", "transfer-encoding", "upgrade",
        "proxy-authorization", "proxy-authenticate", "te", "trailer",
        "content-length", "content-encoding"}

# Dropped from the request before forwarding. The broker authenticates to the
# container with an injected token, so the browser's origin / XSRF headers are
# irrelevant and otherwise trip Jupyter's checks (404/403 on POST, rejected WS).
_DROP_REQ = _HOP | {"host", "origin", "referer", "x-xsrftoken"}

# Dropped from the RESPONSE. We stream the upstream's RAW (still-compressed)
# bytes through, so we KEEP content-encoding and let the browser decode; only
# drop framing headers that no longer apply to our chunked stream.
_DROP_RESP = {"transfer-encoding", "content-length", "connection",
              "keep-alive", "upgrade", "te", "trailer"}

# One pooled client for ALL asset requests. Creating a client per request (the
# old behaviour) paid connection setup ~50x per notebook boot; a shared pool
# with keep-alive recovers the directness the iframe version had.
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0, connect=10.0),
            limits=httpx.Limits(max_connections=200, max_keepalive_connections=100),
        )
    return _client


async def aclose():
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


async def proxy_http(request, uuid: str, path: str, port: int, token: str) -> Response:
    # Forward the RAW query string verbatim (Jupyter uses bare-value cache-bust
    # queries like ?1780212300958 that get mangled if re-encoded via params=).
    q = request.url.query
    target = f"http://127.0.0.1:{port}/nb/{uuid}/{path}" + (f"?{q}" if q else "")
    headers = {k: v for k, v in request.headers.items()
               if k.lower() not in _DROP_REQ}
    headers["Authorization"] = f"token {token}"
    body = await request.body()

    client = _get_client()
    up_req = client.build_request(request.method, target, content=body, headers=headers)
    up = await client.send(up_req, stream=True, follow_redirects=False)

    out_headers = [(k, v) for k, v in up.headers.multi_items()
                   if k.lower() not in _DROP_RESP]

    async def body_stream():
        try:
            async for chunk in up.aiter_raw():
                yield chunk
        finally:
            await up.aclose()

    return StreamingResponse(body_stream(), status_code=up.status_code,
                             headers=dict(out_headers))


async def proxy_ws(websocket: WebSocket, uuid: str, path: str, port: int, token: str):
    proto = websocket.headers.get("sec-websocket-protocol")
    requested = [p.strip() for p in proto.split(",")] if proto else None
    qs = websocket.url.query
    target = f"ws://127.0.0.1:{port}/nb/{uuid}/{path}" + (f"?{qs}" if qs else "")
    # A freshly-created kernel's channels WS is refused (403/connection error)
    # for the first few seconds while the kernel boots. Ride that out within a
    # SINGLE browser connection (~15s) instead of giving up early — closing here
    # makes the browser reconnect-storm ("Connection lost, reconnecting...").
    upstream = None
    for _ in range(30):
        try:
            upstream = await websockets.connect(
                target, subprotocols=requested,
                additional_headers={"Authorization": f"token {token}"},
                max_size=None, open_timeout=20, ping_interval=None)
            break
        except Exception:
            await asyncio.sleep(0.5)
    if upstream is None:
        await websocket.accept(subprotocol=requested[0] if requested else None)
        await websocket.close(code=1011)
        return

    # Echo the subprotocol upstream actually negotiated (None -> JSON mode, which
    # the browser handles); never claim a protocol the upstream isn't speaking.
    await websocket.accept(subprotocol=upstream.subprotocol)

    async def client_to_upstream():
        try:
            while True:
                msg = await websocket.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                if msg.get("text") is not None:
                    await upstream.send(msg["text"])
                elif msg.get("bytes") is not None:
                    await upstream.send(msg["bytes"])
        except Exception:
            pass
        finally:
            await upstream.close()

    async def upstream_to_client():
        try:
            async for m in upstream:
                if isinstance(m, (bytes, bytearray)):
                    await websocket.send_bytes(m)
                else:
                    await websocket.send_text(m)
        except Exception:
            pass
        finally:
            try:
                await websocket.close()
            except Exception:
                pass

    await asyncio.gather(client_to_upstream(), upstream_to_client())
