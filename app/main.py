import os
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.config import UPLOAD_DIR, BASE_DIR
from app.database import init_db
from app.routers import auth_router, user_router, asset_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize database tables
    init_db()
    yield
    # Shutdown

app = FastAPI(
    title="Asset Register (资产登记系统)",
    description="支持 Passkey 认证的资产登记与图片管理系统",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware for local development & flexible reverse proxies
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Prevent aggressive CDN (Cloudflare) / mobile browser caching of static scripts & HTML
@app.middleware("http")
async def add_no_cache_headers(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.endswith(".html") or path.endswith(".js") or path.endswith(".css"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# Include API Routers
app.include_router(auth_router.router)
app.include_router(user_router.router)
app.include_router(asset_router.router)

# Mount uploads static directory
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")

# Mount app static assets (css, js, vendor)
STATIC_DIR = BASE_DIR / "app" / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

@app.get("/api/health")
def health_check():
    return {"status": "ok", "app": "Asset Register"}

# Root index route
@app.get("/")
def serve_index():
    index_file = STATIC_DIR / "index.html"
    return FileResponse(
        str(index_file),
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )

# Fallback for SPA routing
@app.exception_handler(404)
async def custom_404_handler(request: Request, exc):
    if not request.url.path.startswith("/api/") and not request.url.path.startswith("/uploads/"):
        return FileResponse(str(STATIC_DIR / "index.html"))
    return JSONResponse(status_code=404, content={"detail": "Not Found"})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)

