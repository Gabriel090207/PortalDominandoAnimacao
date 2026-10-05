from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.kirvano import router as kirvano_router



app = FastAPI(
    title="Dominando Animação API",
    description="Backend oficial da plataforma Dominando Animação.",
    version="1.0.0",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "https://portaldominandoanimacao.netlify.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def home():
    return {
        "status": "online"
    }


app.include_router(health_router)
app.include_router(kirvano_router)
