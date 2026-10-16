"""Isolated HTTP header parser, NOT proof of a trusted proxy or ingress.

Future callers must validate the Render trust boundary operationally BEFORE
using this output for administrative admission. No routes or middleware here.
"""
from collections.abc import Iterable
import ipaddress


class AdminOriginResolutionError(ValueError):
    def __init__(self):
        super().__init__("Administrative origin could not be resolved.")


def resolve_cf_connecting_ip(raw_headers: Iterable[tuple[bytes, bytes]]) -> str:
    """Parse original ASGI header pairs, preserving duplicates and casing.

    Pass request.scope['headers'], not a dict that collapses duplicate fields.
    Returns canonical IP text, without asserting authenticity or public routing.
    Never falls back to another header or request.client.
    """
    try:
        if isinstance(raw_headers, (dict, str, bytes)):
            raise ValueError
        value = None
        for pair in raw_headers:
            if not isinstance(pair, (tuple, list)) or len(pair) != 2:
                raise ValueError
            name, candidate = pair
            if not isinstance(name, bytes) or not isinstance(candidate, bytes):
                raise ValueError
            if name.lower() == b"cf-connecting-ip":
                if value is not None:
                    raise ValueError  # Even identical duplicate values are ambiguous.
                value = candidate
        if value is None or len(value) > 128:
            raise ValueError
        text = value.strip(b" \t").decode("ascii")
        if not text or "%" in text:
            raise ValueError
        address = ipaddress.ip_address(text)
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
            address = address.ipv4_mapped
        return str(address)
    except Exception:
        # Do not include source input, parser exceptions or malformed bytes.
        raise AdminOriginResolutionError() from None
