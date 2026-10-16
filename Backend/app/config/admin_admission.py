"""Lazy, read-only configuration; never loaded by public application startup."""
from dataclasses import dataclass, field
import os
from pathlib import Path
import re

from dotenv import dotenv_values
from pydantic import SecretStr

_VARIABLE = 'ADMIN_ADMISSION_HMAC_SECRET'
_DEFAULT_ENV_FILE = Path(__file__).resolve().parents[2] / '.env'


class AdminAdmissionConfigurationError(RuntimeError):
    def __init__(self):
        super().__init__('Invalid administrative admission configuration.')


@dataclass(frozen=True)
class AdminAdmissionConfig:
    secret: SecretStr = field(repr=False)
    key_version: int = 1

    def __post_init__(self):
        try:
            value = self.secret.get_secret_value()
            if not re.fullmatch(r'[0-9a-f]{64}', value) or type(self.key_version) is not int or self.key_version != 1:
                raise ValueError
        except Exception:
            raise AdminAdmissionConfigurationError() from None


def load_admin_admission_config(*, environ=None, env_file=_DEFAULT_ENV_FILE):
    """Call only when composing administrative admission, not at module import.

    Process presence wins even when empty. No interpolation, environment writes,
    fallback to commercial secrets, automatic generation or database access.
    The canonical hex TEXT remains the UTF-8 HMAC key, not decoded bytes.
    """
    try:
        environment = os.environ if environ is None else environ
        if _VARIABLE in environment:
            value = environment[_VARIABLE]
        else:
            values = dotenv_values(env_file, interpolate=False) if env_file is not None else {}
            value = values.get(_VARIABLE)
        if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value):
            raise ValueError
        return AdminAdmissionConfig(secret=SecretStr(value))
    except Exception:
        raise AdminAdmissionConfigurationError() from None
