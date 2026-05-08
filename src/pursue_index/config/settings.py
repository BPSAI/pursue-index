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
    ocr_engine: Literal["tesseract", "azure", "auto"] = "auto"
    ocr_dpi: int = 300
    tesseract_bin: str = "/usr/bin/tesseract"

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

    def ensure_dirs(self) -> None:
        for d in (
            self.manifests_dir,
            self.pdf_dir,
            self.image_dir,
            self.video_dir,
            self.ocr_dir,
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
