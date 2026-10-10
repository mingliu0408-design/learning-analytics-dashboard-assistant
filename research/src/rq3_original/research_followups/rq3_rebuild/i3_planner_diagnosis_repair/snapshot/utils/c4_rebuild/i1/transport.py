"""Lazy OpenAI transport. No environment/credential access on import or prepare."""

class TransportFailure(Exception):
    def __init__(self, category, detail=None, request_id=None):
        super().__init__(category)
        self.category, self.detail, self.request_id = category, detail, request_id


class OpenAITransport:
    kind = 'LIVE'

    def __init__(self, *, approved, timeout):
        if approved is not True:
            raise PermissionError('TRANSPORT_NOT_APPROVED')
        from openai import OpenAI
        # SDK defaults read credentials only here, after external approval and all hashes.
        self.client = OpenAI(max_retries=0, timeout=timeout, base_url='https://api.openai.com/v1')

    def send(self, payload):
        try:
            response = self.client.chat.completions.create(**payload)
            raw = response.model_dump(mode='json')
            raw['_request_id'] = getattr(response, '_request_id', None)
            return raw
        except Exception as exc:
            status = getattr(exc, 'status_code', None)
            body = getattr(exc, 'body', None)
            error = (body.get('error') or body) if isinstance(body, dict) else {}
            code = error.get('code') if isinstance(error, dict) else None
            name = type(exc).__name__
            category = ('AUTH' if status in (401,403) else
                'BILLING' if code in ('insufficient_quota','billing_hard_limit_reached') else
                'MODEL' if status == 404 else 'CONFIG' if status in (400,422) else
                'RATE_LIMIT' if status == 429 else 'UNKNOWN_COMPLETION' if
                name in ('APITimeoutError','APIConnectionError') or status is None or status >= 500 else 'PROVIDER_ERROR')
            # Preserve response error bodies, never request headers or credential-bearing reprs.
            raise TransportFailure(category, {'type': name, 'status_code': status, 'body': body},
                                   getattr(exc, 'request_id', None)) from None

    def close(self):
        self.client.close()
