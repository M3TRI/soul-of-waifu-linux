import logging

import httpx

from app.configuration import configuration

logger = logging.getLogger("Local Endpoint")

BUILTIN_PORT = 48596
DEFAULT_EXTERNAL_BASE_URL = "http://127.0.0.1:8080/v1"
FALLBACK_MODEL = "local-model"

# Model ids discovered via GET /models, keyed by base_url, so providers created
# per request do not hit the endpoint every time.
_discovered_models = {}


def normalize_base_url(url: str) -> str:
    url = (url or "").strip().rstrip('/')
    if not url:
        return DEFAULT_EXTERNAL_BASE_URL
    if not url.endswith('/v1'):
        url = f"{url}/v1"
    return url


class LocalEndpointConfig:
    """
    Resolves where the "Local LLM" conversation method sends its requests.

    builtin  - llama-server started by LocalServerManager on 127.0.0.1:48596.
    external - any already running OpenAI-compatible server; nothing is launched.
    """

    def __init__(self):
        settings = configuration.ConfigurationSettings()
        api = configuration.ConfigurationAPI()

        self.external = bool(settings.get_main_setting("local_llm_external"))
        if self.external:
            self.base_url = normalize_base_url(settings.get_main_setting("local_llm_base_url"))
            self.api_key = (api.get_token("LOCAL_LLM_API_TOKEN") or "").strip() or "no-key-required"
            self.configured_model = (settings.get_main_setting("local_llm_model") or "").strip()
        else:
            self.base_url = f"http://127.0.0.1:{BUILTIN_PORT}/v1"
            self.api_key = "no-key-required"
            self.configured_model = ""

    def auth_headers(self) -> dict:
        if self.api_key and self.api_key != "no-key-required":
            return {"Authorization": f"Bearer {self.api_key}"}
        return {}

    async def fetch_models_async(self, timeout: float = 5.0) -> list:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(f"{self.base_url}/models", headers=self.auth_headers())
            response.raise_for_status()
            data = response.json()
            return [m.get("id") for m in data.get("data", []) if m.get("id")]

    async def resolve_model(self) -> str:
        """
        Model id to put in requests. Builtin llama-server ignores it; an external
        server usually needs a real id, so fall back to the first one it lists.
        """
        if not self.external:
            return FALLBACK_MODEL
        if self.configured_model:
            return self.configured_model
        if self.base_url in _discovered_models:
            return _discovered_models[self.base_url]
        try:
            models = await self.fetch_models_async()
            if models:
                _discovered_models[self.base_url] = models[0]
                logger.info(f"Auto-selected model '{models[0]}' from {self.base_url}")
                return models[0]
        except Exception as e:
            logger.warning(f"Could not list models at {self.base_url}: {e}")
        return FALLBACK_MODEL

