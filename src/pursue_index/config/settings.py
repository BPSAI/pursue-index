"""Centralized configuration. All values are env-driven; defaults are dev-friendly."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import Field, HttpUrl, field_validator
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
    # 2026-05-22: Release 02 landed overnight and the poll missed it: upstream
    # did NOT continue the release001 → release002 naming pattern we guessed
    # at on 2026-05-12. Instead they consolidated back to a single mutating
    # canonical CSV at /Portals/1/Interactive/2026/UFO/uap-data.csv (the JS
    # on war.gov/UFO/ now reads from this URL; release001.csv is still
    # served but frozen at Release-01-only content, so our hash-stable
    # comparison reported "unchanged" all night). The new URL holds every
    # release: 158 rows from 5/8/26 (Release 01) + 64 rows from 5/22/26
    # (Release 02). Going forward, additional tranches will surface as
    # row-deltas on this single URL — exactly what the diff/poll machinery
    # was originally built for.
    csv_url: HttpUrl = Field(default="https://www.war.gov/Portals/1/Interactive/2026/UFO/uap-data.csv")
    scrape_user_agent: str = ""  # empty → use the realistic Chrome UA in csv_fetcher

    # ---- Ingest ----
    # Unattended auto-approval of metadata-only PDF re-saves (R7C.12/R7C.14).
    # OFF by default until the differential fuzz harness for the byte
    # classifier lands: a metadata-only verdict is still recorded in the
    # tranche diff and the audit row, but the rename stays quarantined for
    # the operator (``ingest approve --approve-rename <new>=<old>``).
    ingest_auto_approve_metadata_resaves: bool = False

    # ---- Download ----
    download_concurrency: int = 4
    download_retries: int = 5
    # Whether to fetch DVIDS-hosted videos. Defaults to PDFs and images only.
    download_videos: bool = False

    # ---- OCR ----
    # ``llm-dots`` is the OPERATED engine: Claude Sonnet 4.6 vision per page,
    # PLUS local dots.mocr (the ``dots`` engine) as the content-filter (HTTP
    # 400) backstop — a mixed doc keeps Sonnet everywhere except a filter-
    # blocked page, which the isolated dots.mocr venv re-OCRs.
    # ``llm`` = Sonnet without the dots backstop (acceptable, but plain ``llm``
    # 400s on content-filter pages, so it is NOT the operated primary).
    # ``dots`` runs the local dots.mocr backstop standalone.
    # ``tesseract``, ``surya`` and ``auto`` are RETIRED — do not operate them.
    ocr_engine: Literal["tesseract", "surya", "llm", "dots", "llm-dots", "auto"] = "llm-dots"
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

    # ---- Path resolution ----
    @field_validator("data_root", mode="after")
    @classmethod
    def resolve_data_root(cls, v: Path) -> Path:
        """Resolve a relative data_root against the checkout this process is
        running in, so `pursue clean run` works identically from any
        subdirectory AND from a second worktree or fixture repo. See
        :func:`pursue_index.paths.repo_root`.
        """
        if v.is_absolute():
            return v
        from pursue_index.paths import repo_root
        return repo_root() / v

    # ---- Derived paths ----
    @property
    def repo_root(self) -> Path:
        """The checkout this process is reading and writing `data/`
        against. See :func:`pursue_index.paths.repo_root`."""
        from pursue_index.paths import repo_root as _resolve_repo_root
        return _resolve_repo_root()

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

    @property
    def r2_mirror_dir(self) -> Path:
        """NAS-local mirror of the R2 ``archive/`` prefix. The curate clean-qc
        judge renders page images from ``r2_mirror_dir/archive/<sha>.<ext>``."""
        return self.data_root / "r2-mirror"

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


class _LazySettings:
    """Builds ``Settings`` on first use, so importing the package never
    resolves the repo root; an untrusted root then surfaces as a one-line
    error from the command that needs it."""

    def _real(self) -> Settings:
        real: Settings | None = self.__dict__.get("_settings")
        if real is None:
            real = Settings()
            self.__dict__["_settings"] = real
        return real

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real(), name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(self._real(), name, value)

    def __delattr__(self, name: str) -> None:
        delattr(self._real(), name)


settings: Settings = _LazySettings()  # type: ignore[assignment]
