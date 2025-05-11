from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, List, Any, Optional
import os
from pydantic import BaseModel

from app.docker_control import (
    get_containers, start_container, stop_container, restart_container, get_container_logs
)
from app.system_stats import get_system_stats, get_container_stats

app = FastAPI(title="Docker Dashboard API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # frontend dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/ping")
def ping():
    return {"message": "pong"}

# Container management endpoints
@app.get("/containers", response_model=List[Dict[str, Any]])
def list_containers():
    return get_containers()

@app.post("/containers/{container_id}/start", response_model=Dict[str, str])
def start_container_endpoint(container_id: str):
    result = start_container(container_id)
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])
    return result

@app.post("/containers/{container_id}/stop", response_model=Dict[str, str])
def stop_container_endpoint(container_id: str):
    result = stop_container(container_id)
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])
    return result

@app.post("/containers/{container_id}/restart", response_model=Dict[str, str])
def restart_container_endpoint(container_id: str):
    result = restart_container(container_id)
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])
    return result

@app.get("/containers/{container_id}/logs", response_model=Dict[str, Any])
def get_logs_endpoint(container_id: str, tail: Optional[int] = 50):
    result = get_container_logs(container_id, tail)
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])
    return result

# System stats endpoints
@app.get("/stats/system", response_model=Dict[str, Any])
def system_stats_endpoint():
    return get_system_stats()

@app.get("/stats/containers/{container_id}", response_model=Dict[str, Any])
def container_stats_endpoint(container_id: str):
    result = get_container_stats(container_id)
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])
    return result

