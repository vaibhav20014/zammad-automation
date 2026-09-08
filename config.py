"""
Loads and validates all environment variables in one place.

Every other module imports the `settings` object instead of calling
os.getenv() directly.
"""

import os
from pathlib import Path
from dataclasses import dataclass
from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(_PROJECT_ROOT / ".env")


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    project_root: str

    # Zammad
    zammad_url: str
    zammad_token: str

    # Zabbix
    zabbix_url: str
    zabbix_user: str
    zabbix_password: str
    zabbix_customer_id: str

    # Ansible
    inventory_path: str
    playbook_dir: str
    playbook_name: str

    # Terraform
    terraform_dir: str
    terraform_bin: str
    terraform_auto_apply: bool
    aws_region: str

    # Git SCM (playbook / terraform catalogs)
    git_sync_enabled: bool
    ansible_git_remote: str
    ansible_git_branch: str
    terraform_git_remote: str
    terraform_git_branch: str

    # AI
    gemini_api_key: str
    kb_answer_model: str
    embedding_model: str

    # Behavior / constants
    processed_tag: str
    agent_handled_tag: str
    l1_group_name: str
    l2_group_name: str
    l3_group_name: str
    processed_events_file: str
    decision_log_file: str
    vector_index_file: str
    catalog_dir: str


def load_settings() -> Settings:
    catalog_dir = os.getenv("CATALOG_DIR", str(_PROJECT_ROOT / "catalogs"))
    state_dir = os.getenv("STATE_DIR", str(_PROJECT_ROOT / "state"))
    return Settings(
        project_root=str(_PROJECT_ROOT),
        zammad_url=_require("ZAMMAD_URL"),
        zammad_token=_require("ZAMMAD_TOKEN"),
        zabbix_url=os.getenv("ZABBIX_URL", ""),
        zabbix_user=os.getenv("ZABBIX_USER", ""),
        zabbix_password=os.getenv("ZABBIX_PASSWORD", ""),
        zabbix_customer_id=os.getenv(
            "ZABBIX_CUSTOMER_ID", "guess:zabbix@yourdomain.com"
        ),
        inventory_path=os.getenv(
            "INVENTORY_PATH", "/home/ubuntu/zammad-playbooks/inventory.ini"
        ),
        playbook_dir=os.getenv("PLAYBOOK_DIR", "/home/ubuntu/zammad-playbooks"),
        playbook_name=os.getenv("PLAYBOOK_NAME", "check_and_clean_disk.yml"),
        terraform_dir=os.getenv(
            "TERRAFORM_DIR", str(_PROJECT_ROOT / "terraform")
        ),
        terraform_bin=os.getenv("TERRAFORM_BIN", "terraform"),
        terraform_auto_apply=_bool("TERRAFORM_AUTO_APPLY", False),
        aws_region=os.getenv("AWS_REGION", "ap-south-1"),
        git_sync_enabled=_bool("GIT_SYNC_ENABLED", False),
        ansible_git_remote=os.getenv("ANSIBLE_GIT_REMOTE", ""),
        ansible_git_branch=os.getenv("ANSIBLE_GIT_BRANCH", "main"),
        terraform_git_remote=os.getenv("TERRAFORM_GIT_REMOTE", ""),
        terraform_git_branch=os.getenv("TERRAFORM_GIT_BRANCH", "main"),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        kb_answer_model=os.getenv("KB_ANSWER_MODEL", "gemini-2.5-flash"),
        embedding_model=os.getenv("EMBEDDING_MODEL", "gemini-embedding-001"),
        processed_tag=os.getenv("PROCESSED_TAG", "automation-processed"),
        agent_handled_tag=os.getenv("AGENT_HANDLED_TAG", "agent-handled"),
        l1_group_name=os.getenv("L1_GROUP_NAME", "L1-Support"),
        l2_group_name=os.getenv("L2_GROUP_NAME", "L2-Support"),
        l3_group_name=os.getenv("L3_GROUP_NAME", "L3-Support"),
        processed_events_file=os.getenv(
            "PROCESSED_EVENTS_FILE",
            "/home/ubuntu/zammad-automation/processed_zabbix_events.json",
        ),
        decision_log_file=os.getenv(
            "DECISION_LOG_FILE",
            str(Path(state_dir) / "decision_log.jsonl"),
        ),
        vector_index_file=os.getenv(
            "VECTOR_INDEX_FILE",
            str(Path(state_dir) / "kb_vectors.json"),
        ),
        catalog_dir=catalog_dir,
    )


settings = load_settings()
