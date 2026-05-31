"""Definitive kernel-WebSocket test through the broker proxy (no browser).

Logs in, opens a notebook, creates its session+kernel, opens the kernel WS via
the proxy (JSON protocol), sends execute_request for 6*7, waits for '42'.
"""
import asyncio
import json
import secrets
import time

import httpx
import websockets

BASE = "http://127.0.0.1:8010"


async def main():
    async with httpx.AsyncClient(base_url=BASE, timeout=90) as c:
        await c.post("/api/auth/login",
                     json={"email": "alice@example.com", "password": "secret123"})
        nbs = (await c.get("/api/notebooks")).json()
        nb = nbs[0]
        await c.post(f"/api/notebooks/{nb['id']}/open",
                     json={"theme": "Nexalytica Default Dark"})
        uuid = nb["id"]
        sess = (await c.post(f"/nb/{uuid}/api/sessions", json={
            "path": "work/Welcome.ipynb", "type": "notebook",
            "name": "work/Welcome.ipynb", "kernel": {"name": "python3"}})).json()
        print("session/kernel:", sess.get("kernel", {}).get("id"))
        kid = sess["kernel"]["id"]
        cookie = c.cookies.get("nx_session")

    sid = secrets.token_hex(8)
    ws_url = f"ws://127.0.0.1:8010/nb/{uuid}/api/kernels/{kid}/channels?session_id={sid}"
    async with websockets.connect(
            ws_url, additional_headers={"Cookie": f"nx_session={cookie}"},
            open_timeout=20) as ws:
        mid = secrets.token_hex(8)
        await ws.send(json.dumps({
            "header": {"msg_id": mid, "msg_type": "execute_request", "username": "u",
                       "session": sid, "version": "5.3", "date": "2026-01-01T00:00:00Z"},
            "parent_header": {}, "metadata": {}, "channel": "shell",
            "content": {"code": "6*7", "silent": False, "store_history": True,
                        "user_expressions": {}, "allow_stdin": False,
                        "stop_on_error": True}}))
        result = None
        deadline = time.time() + 25
        while time.time() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=5)
            except asyncio.TimeoutError:
                break
            if isinstance(raw, (bytes, bytearray)):
                continue
            m = json.loads(raw)
            if m.get("header", {}).get("msg_type") in ("execute_result", "stream"):
                result = m.get("content", {})
                break
        print("RESULT:", result)
        print("KERNEL WS WORKS:", bool(result) and "42" in json.dumps(result))


asyncio.run(main())
