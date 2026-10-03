from __future__ import annotations

import uuid

from django.http import HttpRequest, HttpResponse


class RequestIdMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        request.request_id = request_id
        response = self.get_response(request)
        response["X-Request-Id"] = request_id
        return response
