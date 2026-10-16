"""Explicit HTTPS origin allowlist; no environment loading or activation."""
from dataclasses import dataclass
import ipaddress
import re
from urllib.parse import urlsplit


class AdminRequestSecurityConfigurationError(RuntimeError):
    def __init__(self):
        super().__init__('Invalid administrative request security configuration.')


def validate_origin(value):
    """Require one ASCII serialized HTTPS origin; never normalize for matching."""
    try:
        if not isinstance(value, str) or not value or len(value) > 2048 or not value.isascii():
            raise ValueError
        if any(ord(c) <= 32 or ord(c) >= 127 for c in value) or '%' in value or '\\' in value:
            raise ValueError
        parsed = urlsplit(value)
        if (parsed.scheme != 'https' or not value.startswith('https://') or
            not parsed.hostname or parsed.username is not None or parsed.password is not None or
            parsed.path or parsed.query or parsed.fragment or '?' in value or '#' in value):
            raise ValueError
        host = parsed.hostname
        if ':' in host:
            ipaddress.IPv6Address(host)
            host_text = '['+host+']'
        else:
            if not all(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label)
                       for label in host.split('.')) or len(host) > 253:
                raise ValueError
            host_text = host
        port = parsed.port
        if port is not None and not 1 <= port <= 65535:
            raise ValueError
        canonical = 'https://'+host_text+(f':{port}' if port is not None else '')
        if canonical != value:
            raise ValueError
        return value
    except Exception:
        raise ValueError('Invalid administrative origin.') from None


@dataclass(frozen=True)
class AdminRequestSecurityConfig:
    allowed_origins: tuple[str, ...]

    def __post_init__(self):
        try:
            if type(self.allowed_origins) is not tuple or not self.allowed_origins:
                raise ValueError
            validated = tuple(validate_origin(value) for value in self.allowed_origins)
            if len(set(validated)) != len(validated):
                raise ValueError
        except Exception:
            raise AdminRequestSecurityConfigurationError() from None
