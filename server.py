"""FastAPI server: upload a STEP file, get DFM analysis + viewable mesh."""

from __future__ import annotations

import os
import tempfile

import numpy as np
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from dfm.analyzer import analyze_step_file

app = FastAPI(title="CNC Manufacturability Ranker")

WEB_DIR = os.path.join(os.path.dirname(__file__), "web")


@app.post("/api/analyze")
async def analyze(file: UploadFile):
    name = (file.filename or "part.step").lower()
    if not name.endswith((".step", ".stp")):
        raise HTTPException(400, "Please upload a .step or .stp file")

    data = await file.read()
    if len(data) > 100 * 1024 * 1024:
        raise HTTPException(400, "File too large (100 MB limit)")

    with tempfile.NamedTemporaryFile(suffix=".step", delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        result, mesh = analyze_step_file(tmp_path)
    except ValueError as e:
        raise HTTPException(422, str(e))
    finally:
        os.unlink(tmp_path)

    payload = result.to_dict()
    payload["mesh"] = {
        "vertices": np.round(mesh.vertices, 4).flatten().tolist(),
        "triangles": mesh.triangles.flatten().tolist(),
        "tri_face_index": mesh.tri_face_index.tolist(),
    }
    payload["filename"] = file.filename
    return JSONResponse(payload)


@app.get("/")
async def index():
    return FileResponse(os.path.join(WEB_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

DEMO_DIR = os.path.join(os.path.dirname(__file__), "test_parts")
if os.path.isdir(DEMO_DIR):
    app.mount("/demo", StaticFiles(directory=DEMO_DIR), name="demo")
