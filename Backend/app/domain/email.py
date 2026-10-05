"""Pure, versioned email normalization shared by purchase and portal identity."""
from email_validator import EmailNotValidError, validate_email

from app.domain.policies import EMAIL_NORMALIZATION_VERSION


def normalize_email(address: str, *, version: int = EMAIL_NORMALIZATION_VERSION) -> str:
    """Validate without DNS and compare case-insensitively; retain dots and aliases."""
    if version != EMAIL_NORMALIZATION_VERSION:
        raise ValueError("Versão de normalização de e-mail não suportada.")
    if not isinstance(address, str):
        raise ValueError("Endereço de e-mail inválido.")
    try:
        result = validate_email(address.strip().lower(), check_deliverability=False)
    except EmailNotValidError:
        raise ValueError("Endereço de e-mail inválido.") from None
    return result.normalized.lower()
