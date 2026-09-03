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
    ansible_timeout_seconds: int

    # Behavior / constants
    processed_tag: str
    l2_group_name: str
    l1_group_name: str
    default_group_name: str
    default_customer_id: str
    processed_events_path: str

    # Logging
    log_dir: str

    # Gemini
    google_api_key: str
    model: str


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
        ansible_timeout_seconds=int(os.getenv("ANSIBLE_TIMEOUT_SECONDS", "120")),
        processed_tag=os.getenv("PROCESSED_TAG", "automation-processed"),
        l2_group_name=os.getenv("L2_GROUP_NAME", "L2-Support"),
        l1_group_name=os.getenv("L1_GROUP_NAME", "L1-Support"),
        default_group_name=os.getenv("DEFAULT_GROUP_NAME", "L1-Support"),
        default_customer_id=os.getenv("DEFAULT_CUSTOMER_ID", "1"),
        processed_events_path=os.getenv(
            "PROCESSED_EVENTS_PATH",
            "/home/ubuntu/zammad-automation/processed_zabbix_events.json",
        ),
        log_dir=os.getenv("LOG_DIR", os.path.join(os.getcwd(), "logs")),
        google_api_key=_require("GOOGLE_API_KEY"),
        model=os.getenv("KB_ANSWER_MODEL", "gemini-2.5-flash")
    )


# Import this from anywhere: `from config import settings`
settings = load_settings()