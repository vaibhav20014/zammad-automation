import os
import subprocess
import json
import requests
from dotenv import load_dotenv

load_dotenv()

ZAMMAD_URL = os.getenv("ZAMMAD_URL")
ZAMMAD_TOKEN = os.getenv("ZAMMAD_TOKEN")

HEADERS = {
    "Authorization": f"Token token={ZAMMAD_TOKEN}",
    "Content-Type": "application/json",
}


def test_connection():
    url = f"{ZAMMAD_URL}/api/v1/tickets"
    response = requests.get(url, headers=HEADERS)
    if response.status_code == 200:
        tickets = response.json()
        print(f"Connected successfully. Found {len(tickets)} ticket(s).")
        for t in tickets:
            print(f"  #{t.get('number')} - {t.get('title')} (state_id: {t.get('state_id')})")
    else:
        print(f"Connection failed. Status code: {response.status_code}")
        print(response.text)


def run_disk_check(playbook_dir="/home/ubuntu/zammad-playbooks", inventory="inventory.ini", playbook="check_and_clean_disk.yml"):
    env = os.environ.copy()
    env["ANSIBLE_STDOUT_CALLBACK"] = "json"
    result = subprocess.run(
        ["ansible-playbook", "-i", inventory, playbook],
        cwd=playbook_dir, env=env, capture_output=True, text=True,
    )
    if result.returncode != 0:
        print("Ansible run failed:")
        print(result.stderr)
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        print("Could not parse Ansible JSON output.")
        print(result.stdout)
        return None


if __name__ == "__main__":
    if not ZAMMAD_URL or not ZAMMAD_TOKEN:
        print("Missing ZAMMAD_URL or ZAMMAD_TOKEN in your .env file.")
    else:
        test_connection()
        print("\n--- Running disk check via Ansible ---")
        output = run_disk_check()
        if output:
            for play in output.get("plays", []):
                for task in play.get("tasks", []):
                    task_result = task.get("hosts", {}).get("target-server-1", {})
                    if "msg" in task_result:
                        print(task_result["msg"])