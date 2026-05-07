from __future__ import annotations

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql://aimd:aimd@localhost:5432/aimd_sentinel",
    )
    openfda_api_key: str | None = os.getenv("OPENFDA_API_KEY") or None
    fda_ai_list_url: str = os.getenv(
        "FDA_AI_LIST_URL",
        "https://www.fda.gov/medical-devices/software-medical-device-samd/artificial-intelligence-enabled-medical-devices",
    )


settings = Settings()
