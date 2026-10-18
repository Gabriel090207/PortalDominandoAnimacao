"""Explicit options for the installed CORSMiddleware; does not install it."""
from app.config.admin_http_security import AdminRequestSecurityConfig, AdminRequestSecurityConfigurationError


def admin_cors_options(security_config: AdminRequestSecurityConfig) -> dict:
    """Use the SAME origin config for CORS and administrative Origin checks.

    Compose one outer CORSMiddleware around an app without existing CORS.
    Do not stack this on app.main's public policy. No globals/env/domain defaults.
    """
    try:
        if not isinstance(security_config, AdminRequestSecurityConfig):
            raise ValueError
        config = AdminRequestSecurityConfig(security_config.allowed_origins)
    except Exception:
        raise AdminRequestSecurityConfigurationError() from None
    return {
        'allow_origins': config.allowed_origins,
        'allow_credentials': True,
        'allow_methods': ('GET', 'POST'),
        'allow_headers': ('Content-Type', 'X-Admin-Request'),
        'expose_headers': ('Retry-After',),
    }
