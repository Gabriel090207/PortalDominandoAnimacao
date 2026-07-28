from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.telegram import router as telegram_router


app = FastAPI(
    title="Dominando Animação API"
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "https://portaldominandoanimacao.netlify.app"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def home():
    return {
        "status":"online"
    }


app.include_router(telegram_router)