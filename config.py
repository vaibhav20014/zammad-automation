"""
Loads and validates all environment variables in one place.

Every other module imports the `settings` object instead of calling
os.getenv() directly. This means:
  - one spot to see every required config value
  - fails fast with a clear error if something's missing
  - easy to add new vars (e.g. KB_API_KEY later) without hunting through files
"""

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    # Zammad
    zammad_url: str
    zammad_token: str

    # Zabbix
    zabbix_url: str
    zabbix_user: str
    zabbix_password: str

    # Ansible
    inventory_path: str
    playbook_dir: str
    playbook_name: str

    # Behavior / constants
    processed_tag: str
    l2_group_name: str
    l1_group_name: str
    processed_events_file: str


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def load_settings() -> Settings:
    return Settings(
        zammad_url=_require("ZAMMAD_URL"),
        zammad_token=_require("ZAMMAD_TOKEN"),
        zabbix_url=os.getenv("ZABBIX_URL", ""),
        zabbix_user=os.getenv("ZABBIX_USER", ""),
        zabbix_password=os.getenv("ZABBIX_PASSWORD", ""),
        inventory_path=os.getenv(
            "INVENTORY_PATH", "/home/ubuntu/zammad-playbooks/inventory.ini"
        ),
        playbook_dir=os.getenv("PLAYBOOK_DIR", "/home/ubuntu/zammad-playbooks"),
        playbook_name=os.getenv("PLAYBOOK_NAME", "check_and_clean_disk.yml"),
        processed_tag=os.getenv("PROCESSED_TAG", "automation-processed"),
        l2_group_name=os.getenv("L2_GROUP_NAME", "L2-Support"),
        l1_group_name=os.getenv("L1_GROUP_NAME", "L1-Support"),
        processed_events_file=os.getenv(
            "PROCESSED_EVENTS_FILE",
            "/home/ubuntu/zammad-automation/processed_zabbix_events.json",
        ),
    )


# Import this from anywhere: `from config import settings`
settings = load_settings()
