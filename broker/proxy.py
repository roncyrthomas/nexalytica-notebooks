"""Reverse proxy for notebook containers (HTTP + kernel WebSocket).

The browser talks only to the broker at /nb/<uuid>/... ; the broker forwards to
the notebook container (which serves under the same base_url) and injects the
container's Jupyter token, so the token never appears in the browser.
"""
import asyncio

import httpx
import websockets
from starlette.responses import Response
from starlette.websockets import WebSocket

_HOP = {"connection", "keep-alive", "transfer-encoding", "upgrade",
        "proxy-authorization", "proxy-authenticate", "te", "trailer",
        "content-length", "content-encoding"}

# Dropped from the request before forwarding. Keep cookies (Jupyter's auth
# relies on them after the first token request); only drop hop-by-hop + host.
_DROP_REQ = _HOP | {"host"}


async def proxy_http(request, uuid: str, path: str, port: int, token: str) -> Response:
    # Forward the RAW query string verbatim (Jupyter uses bare-value cache-bust
    # queries like ?1780212300958 that get mangled if re-encoded via params=).
    q = request.url.query
    target = f"http://127.0.0.1:{port}/nb/{uuid}/{path}" + (f"?{q}" if q else "")
    headers = {k: v for k, v in request.headers.items()
               if k.lower() not in _DROP_REQ}
    headers["Authorization"] = f"token {token}"
    body = await request.body()
    async with httpx.AsyncClient(timeout=60.0) as client:
        up = await client.request(request.method, target, content=body,
                                  headers=headers, follow_redirects=False)
    out_headers = [(k, v) for k, v in up.headers.multi_items()
                   if k.lower() not in _HOP]
    return Response(content=up.content, status_code=up.status_code,
                    headers=dict(out_headers),
                    media_type=up.headers.get("content-type"))


async def proxy_ws(websocket: WebSocket, uuid: str, path: str, port: int, token: str):
    proto = websocket.headers.get("sec-websocket-protocol")
    requested = [p.strip() for p in proto.split(",")] if proto else None
    qs = websocket.url.query
    target = f"ws://127.0.0.1:{port}/nb/{uuid}/{path}" + (f"?{qs}" if qs else "")
    # Retry through the brief window where a just-created kernel isn't ready yet
    # (Jupyter answers the channels WS with 403 until the kernel has started).
    upstream = None
    for attempt in range(6):
        try:
            upstream = await websockets.connect(
                target, subprotocols=requested,
                additional_headers={"Authorization": f"token {token}"},
                max_size=None, open_timeout=20, ping_interval=None)
            break
        except Exception:
            await asyncio.sleep(0.4)
    if upstream is None:
        await websocket.accept(subprotocol=requested[0] if requested else None)
        await websocket.close(code=1011)
        return

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
