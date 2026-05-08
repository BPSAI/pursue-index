"""Centralized configuration. All values are env-driven; defaults are dev-friendly."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="PURSUE_",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- Storage ----
    # data_root holds large derived artifacts (PDFs, OCR output, raw CSV archives).
    # Point this at the NAS in production.
    data_root: Path = Field(default=Path("./data"))
    # manifests_dir is intentionally separate — manifests are small JSON files
    # that live in the repo and are version-controlled. They never go on the NAS.
    manifests_dir: Path = Field(default=Path("./data/manifests"))

    # ---- Database ----
    db_url: str = Field(default="postgresql+psycopg://pursue:pursue@localhost:5432/pursue")

    # ---- Scrape ----
    csv_url: HttpUrl = Field(default="https://www.war.gov/Portals/1/Interactive/2026/UFO/uap-csv.csv")
    scrape_user_agent: str = ""  # empty → use the realistic Chrome UA in csv_fetcher

    # ---- Download ----
    download_concurrency: int = 4
    download_retries: int = 5
    # Whether to fetch DVIDS-hosted videos. Defaults to PDFs and images only.
    download_videos: bool = False

    # ---- OCR ----
    # ``surya`` runs the GPU transformer-OCR adapter (requires the [gpu] extra).
    # ``auto`` runs the primary engine (surya if installed, else tesseract) and
    # re-OCRs pages with confidence < ``ocr_llm_threshold`` via the LLM fallback.
    ocr_engine: Literal["tesseract", "azure", "surya", "llm", "auto"] = "auto"
    ocr_dpi: int = 300
    tesseract_bin: str = "/usr/bin/tesseract"

    # LLM fallback (engine=auto or engine=llm). Provider configurable; the
    # Anthropic path is the v1 implementation, OpenAI is a stub (raises
    # NotImplementedError). Threshold is the per-page mean confidence below
    # which the primary engine's output is overwritten by the LLM's.
    ocr_llm_provider: Literal["anthropic", "openai"] = "anthropic"
    ocr_llm_model: str = "claude-sonnet-4-6"
    ocr_llm_threshold: float = 70.0

    # ---- Embed ----
    # ``voyage`` is the embed-stage default; ``openai`` is a stub seam for v2
    # A/B testing once the benchmark stage exists. Model name is baked into
    # the output dir so multiple embeddings coexist for retrieval comparison.
    embed_provider: Literal["voyage", "openai"] = "voyage"
    embed_model: str = "voyage-3"

    # ---- API ----
    api_host: str = "0.0.0.0"
    api_port: int = 8080

    # ---- Logging ----
    log_level: str = "INFO"
    log_format: Literal["console", "json"] = "console"

    # ---- Derived paths ----
    @property
    def pdf_dir(self) -> Path:
        return self.data_root / "pdfs"

    @property
    def image_dir(self) -> Path:
        return self.data_root / "images"

    @property
    def video_dir(self) -> Path:
        return self.data_root / "videos"

    @property
    def ocr_dir(self) -> Path:
        return self.data_root / "ocr"

    @property
    def csv_archive_dir(self) -> Path:
        """Where raw CSV snapshots are archived for historical diffing."""
        return self.data_root / "csv-archive"

    @property
    def logs_dir(self) -> Path:
        return self.data_root / "logs"

    @property
    def embeddings_dir(self) -> Path:
        """Root of per-model embedding outputs. Sibling of ``ocr_dir``."""
        return self.data_root / "embeddings"

    def ensure_dirs(self) -> None:
        for d in (
            self.manifests_dir,
            self.pdf_dir,
            self.image_dir,
            self.video_dir,
            self.ocr_dir,
            self.embeddings_dir,
            self.csv_archive_dir,
            self.logs_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)


class AzureDISettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    endpoint: str = Field(default="", validation_alias="AZURE_DI_ENDPOINT")
    key: str = Field(default="", validation_alias="AZURE_DI_KEY")

    @property
    def configured(self) -> bool:
        return bool(self.endpoint and self.key)


settings = Settings()
azure_di_settings = AzureDISettings()
