import flask.cli

from api.http import create_app
from core.app_logging import configure_logging, get_logger
from core.config import get_api_port, load_config
from core.log_parser import LogParserService
from core.state import get_state_snapshot, init_state, update_state
from core.switcher import MMDVMHOST_PATH
from core.telegram_bot import TelegramBotService

logger = get_logger("app.main")


def _disable_flask_startup_banner(*args, **kwargs) -> None:
    return None


def main() -> None:
    configure_logging()
    logger.info("Starting Pi-Star Control")
    flask.cli.show_server_banner = _disable_flask_startup_banner

    config_store = load_config()
    init_state(config_store.runtime_state_path)
    detected_network = config_store.detect_network_by_content(MMDVMHOST_PATH)
    if detected_network and get_state_snapshot().get("current_network") != detected_network:
        update_state(current_network=detected_network)
        logger.info("Detected active configuration on startup: %s", detected_network)

    telegram_service = TelegramBotService(config_store)
    telegram_service.start()

    log_parser = LogParserService(config_store)
    log_parser.start()

    app = create_app(config_store, telegram_service=telegram_service)
    port = get_api_port()
    logger.info("Serving Flask app 'api.http'")
    logger.info("Debug mode: off")
    logger.info("Web UI listening on 0.0.0.0:%s", port)
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
