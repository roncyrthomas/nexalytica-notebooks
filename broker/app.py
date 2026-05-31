"""Nexalytica Notebooks — broker web app.

Serves the ChatGPT-style shell and a small JSON API that opens, lists,
reopens and closes Docker-backed notebook sessions via NotebookManager.

Run:  uvicorn app:app --host 127.0.0.1 --port 8000   (from this folder)
Open: http://localhost:8000
"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from manager import VALID_THEMES, NotebookManager

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
manager: NotebookManager | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global manager
    manager = NotebookManager()
    yield
    manager.shutdown()


app = FastAPI(title="Nexalytica Notebooks", lifespan=lifespan)


class CreateBody(BaseModel):
    name: str = "Untitled notebook"
    theme: str = "Nexalytica Default Dark"


class ThemeBody(BaseModel):
    theme: str = "Nexalytica Default Dark"


class RenameBody(BaseModel):
    name: str


def _validated_theme(theme: str) -> str:
    if theme not in VALID_THEMES:
        raise HTTPException(400, f"unknown theme: {theme}")
    return theme


@app.get("/api/notebooks")
def list_notebooks():
    return manager.list_notebooks()


@app.post("/api/notebooks")
def create_notebook(body: CreateBody):
    name = body.name.strip() or "Untitled notebook"
    return manager.create_notebook(name, _validated_theme(body.theme))


@app.post("/api/notebooks/{sid}/open")
def open_notebook(sid: str, body: ThemeBody):
    try:
        return manager.open_notebook(sid, _validated_theme(body.theme))
    except KeyError:
        raise HTTPException(404, "no such notebook")


@app.post("/api/notebooks/{sid}/close")
def close_notebook(sid: str):
    try:
        return manager.close_notebook(sid)
    except KeyError:
        raise HTTPException(404, "no such notebook")


@app.patch("/api/notebooks/{sid}")
def rename_notebook(sid: str, body: RenameBody):
    try:
        return manager.rename_notebook(sid, body.name)
    except KeyError:
        raise HTTPException(404, "no such notebook")


@app.post("/api/notebooks/{sid}/duplicate")
def duplicate_notebook(sid: str):
    try:
        return manager.duplicate_notebook(sid)
    except KeyError:
        raise HTTPException(404, "no such notebook")


@app.delete("/api/notebooks/{sid}")
def delete_notebook(sid: str):
    try:
        return manager.delete_notebook(sid)
    except KeyError:
        raise HTTPException(404, "no such notebook")


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
