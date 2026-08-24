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


def get_ticket_id_by_number(ticket_number):
    """Zammad's UI shows ticket 'number' (e.g. 77009), but the API needs the internal 'id'."""
    url = f"{ZAMMAD_URL}/api/v1/tickets/search?query=number:{ticket_number}"
    response = requests.get(url, headers=HEADERS)
    if response.status_code == 200:
        results = response.json()
        if results:
            return results[0]["id"]
    print(f"Could not find ticket with number {ticket_number}")
    return None


def update_ticket(ticket_id, note, close=False):
    """Posts a note on the ticket, optionally closes it."""
    url = f"{ZAMMAD_URL}/api/v1/tickets/{ticket_id}"
    payload = {
        "article": {
            "body": note,
            "internal": True,
        }
    }
    if close:
        payload["state_id"] = 4  # 4 = closed

    response = requests.put(url, headers=HEADERS, json=payload)
    if response.status_code == 200:
        print(f"Ticket #{ticket_id} updated successfully.")
    else:
        print(f"Failed to update ticket #{ticket_id}: {response.status_code}")
        print(response.text)


def handle_disk_ticket(ticket_number):
    """Runs the disk check and reports the result back to the given ticket."""
    ticket_id = get_ticket_id_by_number(ticket_number)
    if not ticket_id:
        return

    output = run_disk_check()
    if not output:
        update_ticket(ticket_id, "Automation error: could not run disk check.", close=False)
        return

    for play in output.get("plays", []):
        for task in play.get("tasks", []):
            task_result = task.get("hosts", {}).get("target-server-1", {})
            if "msg" in task_result:
                msg = task_result["msg"]
                if "below threshold" in msg:
                    update_ticket(ticket_id, f"Automated check: {msg}", close=True)
                elif "Current disk usage" in msg:
                    print(msg)


if __name__ == "__main__":
    if not ZAMMAD_URL or not ZAMMAD_TOKEN:
        print("Missing ZAMMAD_URL or ZAMMAD_TOKEN in your .env file.")
    else:
        handle_disk_ticket(77009)