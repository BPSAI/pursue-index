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

    # Storage
    data_root: Path = Field(default=Path("./data"))

    # Database
    db_url: str = Field(default="postgresql+psycopg://pursue:pursue@localhost:5432/pursue")

    # Scrape
    source_url: HttpUrl = Field(default="https://www.war.gov/UFO/")
    scrape_headless: bool = True
    scrape_timeout_ms: int = 30_000
    scrape_user_agent: str = "pursue-index/0.1 (+https://bpsaisoftware.com)"

    # Download
    download_concurrency: int = 4
    download_retries: int = 5

    # OCR
    ocr_engine: Literal["tesseract", "azure", "auto"] = "auto"
    ocr_dpi: int = 300
    tesseract_bin: str = "/usr/bin/tesseract"

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8080

    # Logging
    log_level: str = "INFO"
    log_format: Literal["console", "json"] = "console"

    # ---- Derived paths ----
    @property
    def manifests_dir(self) -> Path:
        return self.data_root / "manifests"

    @property
    def pdf_dir(self) -> Path:
        return self.data_root / "pdfs"

    @property
    def ocr_dir(self) -> Path:
        return self.data_root / "ocr"

    @property
    def inspect_dir(self) -> Path:
        return self.data_root / "inspect"

    @property
    def logs_dir(self) -> Path:
        return self.data_root / "logs"

    def ensure_dirs(self) -> None:
        for d in (
            self.manifests_dir,
            self.pdf_dir,
            self.ocr_dir,
            self.inspect_dir,
            self.logs_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)


# Azure DI lives in its own settings block so the import doesn't fail when extras aren't installed.
class AzureDISettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    endpoint: str = Field(default="", validation_alias="AZURE_DI_ENDPOINT")
    key: str = Field(default="", validation_alias="AZURE_DI_KEY")

    @property
    def configured(self) -> bool:
        return bool(self.endpoint and self.key)


settings = Settings()
azure_di_settings = AzureDISettings()
