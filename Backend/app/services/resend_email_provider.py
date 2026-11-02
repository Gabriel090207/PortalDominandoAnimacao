"""Resend adapter, explicit transport only. No default live connection or retry."""
import json
import httpx
from app.domain.welcome_dispatch import WelcomeRequest, WelcomeProviderResult, resend_idempotency_key
from app.config.purchase_welcome import PurchaseWelcomeConfig
from app.services.purchase_welcome_email import WelcomeEmailConfigurationError


class ResendEmailProvider:
    def __init__(self, config: PurchaseWelcomeConfig, *, transport: httpx.BaseTransport):
        if not isinstance(config, PurchaseWelcomeConfig) or not config.enabled or transport is None:
            raise WelcomeEmailConfigurationError()
        self._key = config.api_key
        self._client = httpx.Client(transport=transport, trust_env=False, follow_redirects=False,
                                    timeout=httpx.Timeout(10.0))

    def close(self):
        self._client.close()

    def send(self, message, *, sender, idempotency_key):
        # Validate all application input before making any HTTP request.
        try:
            if not isinstance(idempotency_key, str) or not idempotency_key.startswith('purchase-welcome/'):
                raise ValueError
            if resend_idempotency_key(idempotency_key.removeprefix('purchase-welcome/')) != idempotency_key:
                raise ValueError
            request = WelcomeRequest(sender=sender, recipient=message.recipient, subject=message.subject,
                html=message.html, text=message.text)
        except Exception:
            raise ValueError('Invalid welcome provider request.') from None
        try:
            with self._client.stream('POST', 'https://api.resend.com/emails',
                headers={'Authorization': 'Bearer ' + self._key.get_secret_value(),
                         'Idempotency-Key': idempotency_key}, json=request.payload()) as response:
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > 65536:
                        return WelcomeProviderResult(reason='invalid_response')
                status = response.status_code
            try:
                def unique(pairs):
                    obj = {}
                    for key, value in pairs:
                        if key in obj: raise ValueError
                        obj[key] = value
                    return obj
                def invalid_constant(value): raise ValueError
                body = json.loads(data, object_pairs_hook=unique, parse_constant=invalid_constant)
                if not isinstance(body, dict): raise ValueError
            except Exception:
                return WelcomeProviderResult(reason='invalid_response')
            if status == 200:
                try:
                    return WelcomeProviderResult(reason='accepted', provider_id=body.get('id'))
                except Exception:
                    return WelcomeProviderResult(reason='invalid_response')
            name = body.get('name')
            if status == 409:
                return WelcomeProviderResult(reason='concurrent_request' if name == 'concurrent_idempotent_requests'
                    else 'idempotency_conflict')
            if status in (401, 403):
                return WelcomeProviderResult(reason='authentication')
            if status == 429:
                return WelcomeProviderResult(reason='quota')
            if status in (400, 404, 405, 422):
                return WelcomeProviderResult(reason='rejected')
            return WelcomeProviderResult(reason='unknown_response')
        except httpx.TimeoutException:
            return WelcomeProviderResult(reason='timeout')
        except httpx.RequestError:
            return WelcomeProviderResult(reason='network')
        except Exception:
            return WelcomeProviderResult(reason='internal_failure')
