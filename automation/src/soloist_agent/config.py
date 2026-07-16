from __future__ import annotations

import os
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path


def load_dotenv(path: Path) -> None:
    """Tiny .env loader so secrets do not require another dependency."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


def _decimal(name: str, default: str) -> Decimal:
    return Decimal(os.getenv(name, default))


def _csv(name: str) -> list[str]:
    return [item.strip() for item in os.getenv(name, "").split(",") if item.strip()]


DEFAULT_KEYWORDS = [
    "Rick Owens",
    "Balenciaga",
    "Enfants Riches Déprimés",
    "Undercover",
    "If Six Was Nine",
    "L.G.B.",
    "Number (N)ine",
    "Hysteric Glamour",
    "Chrome Hearts",
    "14th Addiction",
    "Jaded London",
    "Martine Rose",
    "Maison Margiela",
    "Ann Demeulemeester",
    "PALY HOLLYWOOD",
    "Grailz Project",
    "Raf Simons",
    "Saint Laurent",
    "Acne Studios",
    "Vivienne Westwood",
    "Boris Bidjan Saberi",
    "Carl Christian Poell",
    "Maison Mihara Yasuhiro",
    "Thug Club",
    "Vetements",
]


@dataclass(slots=True)
class Settings:
    project_dir: Path
    data_dir: Path
    database_path: Path
    telegram_bot_token: str = ""
    telegram_admin_id: int = 0
    telegram_source_channel: str = "destiny_place"
    telegram_source_channels: list[str] = field(
        default_factory=lambda: ["destiny_place"]
    )
    scan_interval_minutes: int = 1
    max_new_drafts_per_scan: int = 6
    source_page_limit: int = 30
    request_timeout_seconds: int = 30

    yuan_rate: Decimal = Decimal("13")
    procurement_multiplier: Decimal = Decimal("1.15")
    competitor_cheaper_rub: int = 500
    competitor_low_price_threshold_rub: int = 3000
    competitor_low_discount_min_rub: int = 200
    competitor_low_discount_max_rub: int = 300
    discount_min_percent: int = 25
    discount_max_percent: int = 70

    openai_api_key: str = ""
    openai_model: str = "gpt-5.6-luna"
    openai_base_url: str = "https://api.openai.com/v1"
    use_ai: bool = True

    taobao_app_key: str = ""
    taobao_app_secret: str = ""
    taobao_adzone_id: str = ""
    taobao_session: str = ""
    taobao_api_url: str = "https://eco.taobao.com/router/rest"
    taobao_browser_enabled: bool = False
    taobao_browser_profile: Path = Path("data/taobao-profile")
    taobao_browser_headless: bool = False
    taobao_browser_timeout_seconds: int = 45
    taobao_login_timeout_minutes: int = 10
    taobao_keywords_per_scan: int = 2
    taobao_search_delay_seconds: int = 9
    taobao_detail_candidates_per_scan: int = 8
    taobao_min_clean_images: int = 3

    pdd_client_id: str = ""
    pdd_client_secret: str = ""
    pdd_pid: str = ""
    pdd_api_url: str = "https://gw-api.pinduoduo.com/api/router"

    keywords: list[str] = field(default_factory=lambda: DEFAULT_KEYWORDS.copy())

    @property
    def ai_enabled(self) -> bool:
        return self.use_ai and bool(self.openai_api_key)

    @property
    def taobao_enabled(self) -> bool:
        return self.taobao_browser_enabled or self.taobao_api_enabled

    @property
    def taobao_api_enabled(self) -> bool:
        return all((self.taobao_app_key, self.taobao_app_secret, self.taobao_adzone_id))

    @property
    def pdd_enabled(self) -> bool:
        return all((self.pdd_client_id, self.pdd_client_secret, self.pdd_pid))

    @classmethod
    def from_env(cls, env_file: Path | None = None) -> "Settings":
        project_dir = Path(__file__).resolve().parents[2]
        load_dotenv(env_file or project_dir / ".env")
        data_dir = Path(os.getenv("DATA_DIR", "data")).expanduser()
        if not data_dir.is_absolute():
            data_dir = project_dir / data_dir
        data_dir = data_dir.resolve()
        data_dir.mkdir(parents=True, exist_ok=True)

        taobao_browser_profile_raw = os.getenv("TAOBAO_BROWSER_PROFILE", "").strip()
        if taobao_browser_profile_raw:
            taobao_browser_profile = Path(taobao_browser_profile_raw).expanduser()
            if not taobao_browser_profile.is_absolute():
                taobao_browser_profile = project_dir / taobao_browser_profile
        else:
            taobao_browser_profile = data_dir / "taobao-profile"
        taobao_browser_profile = taobao_browser_profile.resolve()

        keywords = _csv("SEARCH_KEYWORDS") or DEFAULT_KEYWORDS.copy()
        keywords_file = Path(os.getenv("SEARCH_KEYWORDS_FILE", "config/keywords.txt")).expanduser()
        if not keywords_file.is_absolute():
            keywords_file = project_dir / keywords_file
        if keywords_file.exists():
            file_keywords = [
                line.strip()
                for line in keywords_file.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            ]
            if file_keywords:
                keywords = file_keywords

        source_channels = _csv("TELEGRAM_SOURCE_CHANNELS")
        if not source_channels:
            source_channels = [os.getenv("TELEGRAM_SOURCE_CHANNEL", "destiny_place")]
        source_channels = list(
            dict.fromkeys(
                channel.strip().lstrip("@").strip("/")
                for channel in source_channels
                if channel.strip()
            )
        )

        return cls(
            project_dir=project_dir,
            data_dir=data_dir,
            database_path=data_dir / "soloist_agent.sqlite3",
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
            telegram_admin_id=_int("TELEGRAM_ADMIN_ID", 0),
            telegram_source_channel=source_channels[0],
            telegram_source_channels=source_channels,
            scan_interval_minutes=_int("SCAN_INTERVAL_MINUTES", 1),
            max_new_drafts_per_scan=_int("MAX_NEW_DRAFTS_PER_SCAN", 6),
            source_page_limit=_int("SOURCE_PAGE_LIMIT", 30),
            request_timeout_seconds=_int("REQUEST_TIMEOUT_SECONDS", 30),
            yuan_rate=_decimal("YUAN_RATE", "13"),
            procurement_multiplier=_decimal("PROCUREMENT_MULTIPLIER", "1.15"),
            competitor_cheaper_rub=_int("COMPETITOR_CHEAPER_RUB", 500),
            competitor_low_price_threshold_rub=_int("COMPETITOR_LOW_PRICE_THRESHOLD_RUB", 3000),
            competitor_low_discount_min_rub=_int("COMPETITOR_LOW_DISCOUNT_MIN_RUB", 200),
            competitor_low_discount_max_rub=_int("COMPETITOR_LOW_DISCOUNT_MAX_RUB", 300),
            discount_min_percent=_int("DISCOUNT_MIN_PERCENT", 25),
            discount_max_percent=_int("DISCOUNT_MAX_PERCENT", 70),
            openai_api_key=os.getenv("OPENAI_API_KEY", "").strip(),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5.6-luna").strip(),
            openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
            use_ai=_bool("USE_AI", True),
            taobao_app_key=os.getenv("TAOBAO_APP_KEY", "").strip(),
            taobao_app_secret=os.getenv("TAOBAO_APP_SECRET", "").strip(),
            taobao_adzone_id=os.getenv("TAOBAO_ADZONE_ID", "").strip(),
            taobao_session=os.getenv("TAOBAO_SESSION", "").strip(),
            taobao_api_url=os.getenv("TAOBAO_API_URL", "https://eco.taobao.com/router/rest").strip(),
            taobao_browser_enabled=_bool("TAOBAO_BROWSER_ENABLED", False),
            taobao_browser_profile=taobao_browser_profile,
            taobao_browser_headless=_bool("TAOBAO_BROWSER_HEADLESS", False),
            taobao_browser_timeout_seconds=_int("TAOBAO_BROWSER_TIMEOUT_SECONDS", 45),
            taobao_login_timeout_minutes=_int("TAOBAO_LOGIN_TIMEOUT_MINUTES", 10),
            taobao_keywords_per_scan=_int("TAOBAO_KEYWORDS_PER_SCAN", 2),
            taobao_search_delay_seconds=_int("TAOBAO_SEARCH_DELAY_SECONDS", 9),
            taobao_detail_candidates_per_scan=_int("TAOBAO_DETAIL_CANDIDATES_PER_SCAN", 8),
            taobao_min_clean_images=_int("TAOBAO_MIN_CLEAN_IMAGES", 3),
            pdd_client_id=os.getenv("PDD_CLIENT_ID", "").strip(),
            pdd_client_secret=os.getenv("PDD_CLIENT_SECRET", "").strip(),
            pdd_pid=os.getenv("PDD_PID", "").strip(),
            pdd_api_url=os.getenv("PDD_API_URL", "https://gw-api.pinduoduo.com/api/router").strip(),
            keywords=keywords,
        )
