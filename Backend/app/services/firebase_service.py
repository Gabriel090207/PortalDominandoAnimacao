"""Centralized Firebase initialization and reusable Firestore access."""

import json
import os
from pathlib import Path
from threading import RLock

import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_lock = RLock()


def get_firebase_app() -> firebase_admin.App:
    """Reuse the default app, initializing it from configured credentials once."""
    with _lock:
        try:
            return firebase_admin.get_app()
        except ValueError:
            pass

        load_dotenv(_BACKEND_ROOT / ".env")
        configured_json = os.getenv("FIREBASE_CREDENTIALS_JSON", "").strip()
        configured_path = os.getenv("FIREBASE_CREDENTIALS_PATH", "").strip()

        # Explicit JSON configuration wins; invalid JSON must not fall back to a file.
        if configured_json:
            try:
                credential_data = json.loads(configured_json)
                if not isinstance(credential_data, dict):
                    raise ValueError
                credential = credentials.Certificate(credential_data)
            except Exception:
                raise RuntimeError("FIREBASE_CREDENTIALS_JSON contém uma credencial inválida.") from None
        elif configured_path:
            credential_path = Path(configured_path).expanduser()
            if not credential_path.is_absolute():
                credential_path = _BACKEND_ROOT / credential_path
            if not credential_path.is_file():
                raise RuntimeError("Arquivo de credencial Firebase não encontrado.")
            try:
                credential = credentials.Certificate(str(credential_path))
            except Exception:
                raise RuntimeError("Credencial Firebase em arquivo inválida ou inacessível.") from None
        else:
            raise RuntimeError("Configure FIREBASE_CREDENTIALS_JSON ou FIREBASE_CREDENTIALS_PATH.")

        try:
            return firebase_admin.initialize_app(credential)
        except Exception:
            raise RuntimeError("Não foi possível inicializar Firebase com a credencial configurada.") from None


def get_firestore_client():
    """Return the client cached by the SDK for the initialized application."""
    with _lock:
        try:
            return firestore.client(app=get_firebase_app())
        except RuntimeError:
            raise
        except Exception:
            raise RuntimeError("Não foi possível criar o cliente Cloud Firestore.") from None
