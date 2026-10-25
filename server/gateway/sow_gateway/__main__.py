import logging
import os

import uvicorn

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
cert, key = os.environ.get("SOW_TLS_CERT"), os.environ.get("SOW_TLS_KEY")
tls = {"ssl_certfile": cert, "ssl_keyfile": key} if cert and key else {}
uvicorn.run("sow_gateway.app:app", host="0.0.0.0", port=8765, log_level="info", **tls)
