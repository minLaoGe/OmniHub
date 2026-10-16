import os
from pathlib import Path
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
STATIC_DIR = BASE_DIR / "static"

SERVICES_FILE = DATA_DIR / "services.json"
MCP_SERVERS_FILE = DATA_DIR / "mcp_servers.json"
SETTINGS_FILE = DATA_DIR / "settings.json"

class AppConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 9527
    llm_api_base: str = "http://127.0.0.1:8088/v1"
    llm_model_name: str = "Qwen3.8-27B"
    llm_api_key: str = "not-needed"
    enable_auto_proxy: bool = True

def get_settings() -> AppConfig:
    import json
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return AppConfig(**json.load(f))
        except Exception:
            pass
    return AppConfig()

def save_settings(config: AppConfig):
    import json
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(config.dict(), f, ensure_ascii=False, indent=2)
