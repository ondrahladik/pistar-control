import json
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from flask import Flask, Response, jsonify, redirect, render_template, request, session, stream_with_context, url_for

from core.config import ConfigStore, get_api_token
from core.log_parser import LogParserService
from core.state import get_state_snapshot, get_state_version, wait_for_state_change_since
from core.switcher import switch_network


def create_app(
    config_store: ConfigStore,
    telegram_service: Optional[Any] = None,
    log_parser: Optional[LogParserService] = None,
) -> Flask:
    template_dir = Path(__file__).resolve().parents[1] / "templates"
    fav_dir = template_dir / "fav"
    app = Flask(
        __name__,
        template_folder=str(template_dir),
        static_folder=str(fav_dir),
        static_url_path="/fav",
    )
    app.secret_key = "pistar-control-ui-session"
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    @app.after_request
    def after_request(response):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        return response

    @app.route("/api/<path:path>", methods=["OPTIONS"])
    def options_handler(path):
        return "", 200

    def is_ui_authenticated() -> bool:
        return session.get("ui_token") == get_api_token() and bool(get_api_token())

    @app.before_request
    def protect_ui_routes() -> Any:
        if request.path.startswith("/api/"):
            return None

        if request.endpoint == "static":
            return None

        public_paths = {
            "/login",
            "/auth/login",
            "/auth/logout",
        }

        if request.path == "/login" and is_ui_authenticated():
            return redirect(url_for("index"))

        if request.path in public_paths:
            return None

        if not is_ui_authenticated():
            return redirect(url_for("login_page"))

        return None

    def require_auth(handler: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(handler)
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            auth_header = request.headers.get("Authorization", "")
            expected_header = f"Bearer {get_api_token()}"

            if auth_header != expected_header and not is_ui_authenticated():
                return jsonify({"error": "Unauthorized"}), 401

            return handler(*args, **kwargs)

        return wrapped

    @app.route("/login")
    def login_page() -> Any:
        return render_template("login.html", title="Přihlášení", active_page="login")

    @app.post("/auth/login")
    def login() -> Any:
        payload = request.get_json(silent=True) or {}
        token = payload.get("token", "")

        if token != get_api_token():
            return jsonify({"error": "Unauthorized"}), 401

        session["ui_token"] = token
        return jsonify({"success": True})

    @app.post("/auth/logout")
    def logout() -> Any:
        session.clear()

        if request.is_json:
            return jsonify({"success": True})

        return redirect(url_for("login_page"))

    @app.route("/")
    def index() -> Any:
        return render_template("home.html", title="Pi-Star Control", active_page="home")

    @app.route("/config")
    def config_page() -> Any:
        return render_template("index.html", title="Konfigurace", active_page="config")

    @app.post("/api/network")
    @require_auth
    def set_network() -> Any:
        payload = request.get_json(silent=True) or {}
        network_name = payload.get("network")

        if not isinstance(network_name, str) or not network_name.strip():
            return jsonify({"error": "Missing network name"}), 400

        if network_name not in config_store.list_networks():
            return jsonify({"error": "Unknown network"}), 404

        if not switch_network(network_name, config_store):
            return jsonify({"error": "Failed to switch network"}), 500

        if telegram_service is not None:
            telegram_service.request_dashboard_refresh()

        return jsonify({
            "success": True,
            "current_network": get_state_snapshot()["current_network"],
        })

    @app.get("/api/hosts/<string:name>")
    @require_auth
    def get_host(name: str) -> Any:
        if name not in config_store.list_networks():
            return jsonify({"error": "Unknown host"}), 404

        return jsonify({
            "host": {
                "id": name,
                "label": config_store.get_network_alias(name),
                "content": config_store.get_host_content(name),
            }
        })

    @app.post("/api/hosts/<string:name>")
    @require_auth
    def update_host(name: str) -> Any:
        if name not in config_store.list_networks():
            return jsonify({"error": "Unknown host"}), 404

        payload = request.get_json(silent=True) or {}
        content = payload.get("content")

        if not isinstance(content, str):
            return jsonify({"error": "Missing host content"}), 400

        config_store.update_host_content(name, content)
        return jsonify({
            "success": True,
            "host": {
                "id": name,
                "label": config_store.get_network_alias(name),
                "content": config_store.get_host_content(name),
            }
        })

    @app.get("/api/networks")
    @require_auth
    def get_networks() -> Any:
        aliases = config_store.get_network_aliases()
        return jsonify({
            "networks": [
                {
                    "id": network,
                    "label": aliases.get(network, network),
                }
                for network in config_store.list_networks()
            ]
        })

    @app.get("/api/status")
    @require_auth
    def get_status() -> Any:
        return jsonify(_build_status_payload(config_store, log_parser))

    @app.get("/api/recent-calls")
    @require_auth
    def get_recent_calls() -> Any:
        return jsonify({
            "recent_calls": (
                log_parser.get_recent_calls()
                if log_parser is not None
                else []
            )
        })

    @app.get("/api/status/stream")
    def stream_status() -> Any:
        if not is_ui_authenticated():
            return jsonify({"error": "Unauthorized"}), 401

        @stream_with_context
        def event_stream():
            last_seen_version = -1
            while True:
                current_version = get_state_version()
                if current_version != last_seen_version:
                    payload = _build_status_payload(config_store, log_parser)
                    yield f"event: status\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    last_seen_version = current_version
                last_seen_version = wait_for_state_change_since(last_seen_version, 15.0)
                yield ": keep-alive\n\n"

        return Response(
            event_stream(),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/api/config")
    @require_auth
    def get_config() -> Any:
        config_store.reload()
        return jsonify({"config": config_store.get_app_config()})

    @app.post("/api/config")
    @require_auth
    def update_config() -> Any:
        payload = request.get_json(silent=True) or {}
        config_data = payload.get("config")

        if not isinstance(config_data, dict) or not config_data:
            return jsonify({"error": "Missing config data"}), 400

        normalized_config: Dict[str, Dict[str, str]] = {}
        for section, values in config_data.items():
            if not isinstance(section, str) or not section.strip():
                return jsonify({"error": "Invalid section name"}), 400
            if not isinstance(values, dict):
                return jsonify({"error": f"Invalid section payload for {section}"}), 400

            normalized_values: Dict[str, str] = {}
            for key, value in values.items():
                if not isinstance(key, str) or not key.strip():
                    return jsonify({"error": "Invalid config key"}), 400
                if value is None:
                    normalized_values[key] = ""
                elif isinstance(value, (str, int, float, bool)):
                    normalized_values[key] = str(value)
                else:
                    return jsonify({"error": f"Invalid value type for {section}.{key}"}), 400

            normalized_config[section.strip()] = normalized_values

        config_store.update_app_config(normalized_config)
        session_token = session.get("ui_token")
        if session_token is not None:
            session["ui_token"] = config_store.api_token
        if telegram_service is not None:
            telegram_service.request_dashboard_refresh()
        return jsonify({
            "success": True,
            "config": config_store.get_app_config(),
        })

    return app


def _build_status_payload(
    config_store: ConfigStore,
    log_parser: Optional[LogParserService] = None,
) -> Dict[str, Any]:
    snapshot = get_state_snapshot()
    current_network = snapshot["current_network"]
    current_network_settings = (
        config_store.get_basic_host_settings(current_network)
        if current_network
        else {}
    )
    return {
        "current_network": current_network,
        "current_network_label": (
            config_store.get_network_alias(current_network)
            if current_network
            else None
        ),
        "current_network_display_id": _format_network_display_id(current_network),
        "current_network_settings": current_network_settings,
        "active_call": snapshot["active_call"],
        "recent_calls": (
            log_parser.get_recent_calls()
            if log_parser is not None
            else []
        ),
        "last_update_at": snapshot["last_update_at"],
    }


def _format_network_display_id(network_name: Any) -> Optional[str]:
    if not isinstance(network_name, str) or not network_name:
        return None
    if network_name == "host1":
        return "Host 1"
    if network_name == "host2":
        return "Host 2"
    return network_name
