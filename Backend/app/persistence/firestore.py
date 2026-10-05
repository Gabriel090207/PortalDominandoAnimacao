"""Lazy collection references for future repositories; no CRUD operations."""
from google.cloud.firestore_v1 import CollectionReference

from app.persistence.collections import CollectionName
from app.services.firebase_service import get_firestore_client


def get_collection_reference(name: CollectionName) -> CollectionReference:
    if not isinstance(name, CollectionName):
        raise ValueError("Coleção deve ser declarada em CollectionName.")
    return get_firestore_client().collection(name.value)
