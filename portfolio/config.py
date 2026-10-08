"""Settings loaded from the .env file next to the project (or the environment)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Config:
    anthropic_api_key: str
    claude_model: str
    google_maps_api_key: str
    wp_url: str
    wp_user: str
    wp_app_password: str
    wpe_ssh_user: str
    wpe_ssh_host: str
    template_post_id: int
    dropbox_clients_dir: Path
    jobs_dir: Path

    @property
    def ssh_target(self) -> str:
        return f"{self.wpe_ssh_user}@{self.wpe_ssh_host}"

    def missing(self) -> list[str]:
        """Names of required settings that are empty."""
        required = {
            "ANTHROPIC_API_KEY": self.anthropic_api_key,
            "WP_URL": self.wp_url,
            "WP_USER": self.wp_user,
            "WP_APP_PASSWORD": self.wp_app_password,
            "WPE_SSH_USER": self.wpe_ssh_user,
            "WPE_SSH_HOST": self.wpe_ssh_host,
            "DROPBOX_CLIENTS_DIR": str(self.dropbox_clients_dir) if self.dropbox_clients_dir else "",
        }
        return [name for name, value in required.items() if not value]


def load_config() -> Config:
    load_dotenv(PROJECT_ROOT / ".env")
    jobs_dir = Path(os.getenv("JOBS_DIR", "jobs"))
    if not jobs_dir.is_absolute():
        jobs_dir = PROJECT_ROOT / jobs_dir
    return Config(
        anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        claude_model=os.getenv("CLAUDE_MODEL", "claude-opus-5-5"),
        google_maps_api_key=os.getenv("GOOGLE_MAPS_API_KEY", ""),
        wp_url=os.getenv("WP_URL", "https://uniteideas.com").rstrip("/"),
        wp_user=os.getenv("WP_USER", ""),
        wp_app_password=os.getenv("WP_APP_PASSWORD", ""),
        wpe_ssh_user=os.getenv("WPE_SSH_USER", ""),
        wpe_ssh_host=os.getenv("WPE_SSH_HOST", ""),
        template_post_id=int(os.getenv("TEMPLATE_POST_ID", "7178")),
        dropbox_clients_dir=Path(os.getenv("DROPBOX_CLIENTS_DIR", "")),
        jobs_dir=jobs_dir,
    )
