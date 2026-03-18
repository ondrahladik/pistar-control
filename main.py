from api.http import create_app
from core.config import get_api_port, load_config


def main() -> None:
    config_store = load_config()
    app = create_app(config_store)
    app.run(host="0.0.0.0", port=get_api_port())


if __name__ == "__main__":
    main()
