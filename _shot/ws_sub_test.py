"""Reproduce the browser's kernel WS (WITH the v1 subprotocol) through the proxy."""
import asyncio
import websockets
import httpx

BASE = "http://127.0.0.1:8010"
SUB = "v1.kernel.websocket.jupyter.org"


async def main():
    async with httpx.AsyncClient(base_url=BASE, timeout=90) as c:
        await c.post("/api/auth/login", json={"email": "alice@example.com", "password": "secret123"})
        nbs = (await c.get("/api/notebooks")).json()
        nb = nbs[0]
        await c.post(f"/api/notebooks/{nb['id']}/open", json={"theme": "Nexalytica Default Dark"})
        uuid = nb["id"]
        sess = (await c.post(f"/nb/{uuid}/api/sessions", json={
            "path": "work/Welcome.ipynb", "type": "notebook",
            "name": "work/Welcome.ipynb", "kernel": {"name": "python3"}})).json()
        kid = sess["kernel"]["id"]
        cookie = c.cookies.get("nx_session")

    url = f"ws://127.0.0.1:8010/nb/{uuid}/api/kernels/{kid}/channels?session_id=abc123"
    print("connecting WITH subprotocol", SUB)
    try:
        ws = await websockets.connect(url, additional_headers={"Cookie": f"nx_session={cookie}"},
                                      subprotocols=[SUB], open_timeout=20)
        print("CONNECTED, negotiated subprotocol:", ws.subprotocol)
        await ws.close()
    except Exception as e:
        print("FAILED WITH SUBPROTOCOL:", repr(e))

    print("connecting WITHOUT subprotocol")
    try:
        ws = await websockets.connect(url, additional_headers={"Cookie": f"nx_session={cookie}"}, open_timeout=20)
        print("CONNECTED (no subproto), subprotocol:", ws.subprotocol)
        await ws.close()
    except Exception as e:
        print("FAILED NO SUBPROTOCOL:", repr(e))


asyncio.run(main())
