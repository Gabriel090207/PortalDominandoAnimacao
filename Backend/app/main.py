from fastapi import FastAPI
from app.api.health import router as health_router

app = FastAPI(
    title="Dominando Animação API",
    description="Backend oficial da plataforma Dominando Animação.",
    version="1.0.0",
)

@app.get("/")
def home():
    return {
        "status": "online",
        "message": "Backend Dominando Animação funcionando 🚀"
    }

app.include_router(health_router)