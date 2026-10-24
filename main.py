from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from config import RESOURCES_DIR
from routes import (
    pages,
    repos,
    builds,
    installs,
    scripts,
    history_routes,
    stop,
)

app = FastAPI(title="DockerHub Lite")

app.mount("/static", StaticFiles(directory=RESOURCES_DIR / "static"), name="static")

app.include_router(pages.router)
app.include_router(repos.router)
app.include_router(builds.router)
app.include_router(installs.router)
app.include_router(scripts.router)
app.include_router(history_routes.router)
app.include_router(stop.router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)