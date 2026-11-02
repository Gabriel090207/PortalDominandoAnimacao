from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.health import router as health_router
from app.api.kirvano import router as kirvano_router
from app.services.purchase_welcome_trigger import purchase_welcome_lifespan



def create_app(*, welcome_installation=None):
    """Existing public app; optional explicit email installation, never env opt-in."""
    application = FastAPI(
        title="Dominando Animação API",
        description="Backend oficial da plataforma Dominando Animação.",
        version="1.0.0",
        lifespan=purchase_welcome_lifespan,
    )


    application.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "https://portaldominandoanimacao.netlify.app",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


    @application.get("/")
    def home():
        return {
            "status": "online"
        }


    application.include_router(health_router)
    application.include_router(kirvano_router)
    if welcome_installation is not None:
        from app.services.purchase_welcome_runtime import prepare_purchase_welcome_runtime
        prepare_purchase_welcome_runtime(application, welcome_installation)
    return application


app = create_app()
