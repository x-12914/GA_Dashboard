"""Configuration loaded from environment / .env file."""
import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # When true (or when no GA4 credentials are present) the app serves
    # realistic mock analytics so you can see everything working instantly.
    USE_MOCK: bool = os.getenv("USE_MOCK", "true").lower() in ("1", "true", "yes")

    # GA4 ----------------------------------------------------------------
    # Your GA4 property id, e.g. "123456789" (the number, not "G-XXXX").
    GA4_PROPERTY_ID: str = os.getenv("GA4_PROPERTY_ID", "")
    # Path to the service-account JSON key file you download from Google Cloud.
    GOOGLE_APPLICATION_CREDENTIALS: str = os.getenv(
        "GOOGLE_APPLICATION_CREDENTIALS", ""
    )

    # LLM provider ------------------------------------------------------
    # "auto" picks OpenAI if its key is set, else Claude, else the built-in
    # rule-based analyzer. Force one with "openai", "claude", or "none".
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "auto").lower()

    # OpenAI
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    # Claude (switch to this later by setting the key / LLM_PROVIDER=claude)
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

    # Google PageSpeed Insights (optional) — enables real mobile speed scores
    # in the store auditor. Free key: https://developers.google.com/speed/docs/insights/v5/get-started
    PAGESPEED_API_KEY: str = os.getenv("PAGESPEED_API_KEY", "")

    # Google Programmable Search (optional) — enables auto-discovery of stores
    # by niche in the Prospect Finder. Needs an API key (can reuse the PageSpeed
    # one if Custom Search API is enabled on it) and a search-engine id (cx).
    # Set up: https://programmablesearchengine.google.com  (set to search the
    # whole web), then enable "Custom Search API" in Google Cloud.
    GOOGLE_CSE_API_KEY: str = os.getenv("GOOGLE_CSE_API_KEY", "")
    GOOGLE_CSE_ID: str = os.getenv("GOOGLE_CSE_ID", "")

    @property
    def cse_key(self) -> str:
        # Fall back to the PageSpeed key (same Google account) if not set.
        return self.GOOGLE_CSE_API_KEY or self.PAGESPEED_API_KEY

    @property
    def discovery_ready(self) -> bool:
        return bool(self.cse_key and self.GOOGLE_CSE_ID)

    @property
    def ga4_ready(self) -> bool:
        return bool(self.GA4_PROPERTY_ID and self.GOOGLE_APPLICATION_CREDENTIALS)

    @property
    def openai_ready(self) -> bool:
        return bool(self.OPENAI_API_KEY)

    @property
    def claude_ready(self) -> bool:
        return bool(self.ANTHROPIC_API_KEY)

    @property
    def provider(self) -> str:
        """Resolve which analyzer engine to actually use."""
        if self.LLM_PROVIDER == "openai":
            return "openai" if self.openai_ready else "heuristic"
        if self.LLM_PROVIDER == "claude":
            return "claude" if self.claude_ready else "heuristic"
        if self.LLM_PROVIDER == "none":
            return "heuristic"
        # auto
        if self.openai_ready:
            return "openai"
        if self.claude_ready:
            return "claude"
        return "heuristic"


settings = Settings()
