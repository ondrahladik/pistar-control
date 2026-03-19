import json
from typing import Any, Dict
from urllib import error, request

from core.config import ConfigStore


class ApiClientError(Exception):
    pass


class ApiClient:
    def __init__(self, config_store: ConfigStore) -> None:
        self._config_store = config_store

    def switch_network(self, network_name: str) -> Dict[str, Any]:
        payload = json.dumps({"network": network_name}).encode("utf-8")
        http_request = request.Request(
            url=f"http://127.0.0.1:{self._config_store.api_port}/api/network",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._config_store.api_token}",
            },
            method="POST",
        )

        try:
            with request.urlopen(http_request, timeout=10) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            message = _extract_error_message(body) or f"HTTP {exc.code}"
            raise ApiClientError(message) from exc
        except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ApiClientError(str(exc)) from exc


def _extract_error_message(body: str) -> str:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return body.strip()

    if isinstance(payload, dict):
        error_message = payload.get("error")
        if isinstance(error_message, str):
            return error_message
    return ""
