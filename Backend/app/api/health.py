from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health():
    return {
        "status": "online",
        "api": "Dominando Animação",
        "version": "1.0.0",
    }