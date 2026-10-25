import logging
import os

import uvicorn

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
uvicorn.run("sow_speech.app:app", host="0.0.0.0", port=int(os.environ.get("SOW_SPEECH_PORT", "8001")),
            log_level="info")
