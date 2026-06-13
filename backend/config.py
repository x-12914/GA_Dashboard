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

    # Store discovery for the Prospect Finder (optional). Pick a provider:
    #   auto   = use whichever key is set (serper > jina > google)
    #   serper = Serper.dev (recommended: simplest, generous free tier)
    #   jina   = Jina AI search (s.jina.ai)
    #   google = Google Programmable Search (needs API key + CSE id)
    SEARCH_PROVIDER: str = os.getenv("SEARCH_PROVIDER", "auto").lower()
    SERPER_API_KEY: str = os.getenv("SERPER_API_KEY", "")      # https://serper.dev
    JINA_API_KEY: str = os.getenv("JINA_API_KEY", "")          # https://jina.ai
    GOOGLE_CSE_API_KEY: str = os.getenv("GOOGLE_CSE_API_KEY", "")
    GOOGLE_CSE_ID: str = os.getenv("GOOGLE_CSE_ID", "")

    @property
    def cse_key(self) -> str:
        # Fall back to the PageSpeed key (same Google account) if not set.
        return self.GOOGLE_CSE_API_KEY or self.PAGESPEED_API_KEY

    @property
    def google_search_ready(self) -> bool:
        return bool(self.cse_key and self.GOOGLE_CSE_ID)

    @property
    def search_provider(self) -> str:
        """Resolve which search backend to actually use ('none' if unconfigured)."""
        ready = {
            "serper": bool(self.SERPER_API_KEY),
            "jina": bool(self.JINA_API_KEY),
            "google": self.google_search_ready,
        }
        if self.SEARCH_PROVIDER in ready:
            return self.SEARCH_PROVIDER if ready[self.SEARCH_PROVIDER] else "none"
        for name in ("serper", "jina", "google"):  # auto order
            if ready[name]:
                return name
        return "none"

    @property
    def discovery_ready(self) -> bool:
        return self.search_provider != "none"

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
