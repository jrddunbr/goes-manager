from object_platform_common.config import load_config
from object_platform_common.logging_utils import configure_logging

from .app import create_app


if __name__ == "__main__":
    config = load_config()
    configure_logging(config.service_name)
    app = create_app()
    app.run(host="0.0.0.0", port=config.health_port, debug=False, use_reloader=False)
