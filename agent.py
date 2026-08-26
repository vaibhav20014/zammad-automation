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

INVENTORY_PATH = "/home/ubuntu/zammad-playbooks/inventory.ini"
PLAYBOOK_DIR = "/home/ubuntu/zammad-playbooks"
PROCESSED_TAG = "automation-processed"


def load_known_servers(inventory_path=INVENTORY_PATH):
    servers = set()
    with open(inventory_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("[") or line.startswith("#"):
                continue
            server_name = line.split()[0]
            servers.add(server_name)
    return servers


def extract_server_name(ticket_title, ticket_body, known_servers):
    text = f"{ticket_title} {ticket_body}".lower()
    for server in known_servers:
        if server.lower() in text:
            return server
    return None


def find_open_disk_tickets():
    query = f'(title:*disk* OR title:*server*) AND state.name:(new OR open) AND NOT tags:{PROCESSED_TAG}'
    url = f"{ZAMMAD_URL}/api/v1/tickets/search?query={query}&limit=20"
    response = requests.get(url, headers=HEADERS)
    if response.status_code != 200:
        print(f"Ticket search failed: {response.status_code}")
        print(response.text)
        return []
    return response.json()


def run_disk_check(target_host, playbook_dir=PLAYBOOK_DIR, inventory="inventory.ini", playbook="check_and_clean_disk.yml"):
    env = os.environ.copy()
    env["ANSIBLE_STDOUT_CALLBACK"] = "json"
    result = subprocess.run(
        ["ansible-playbook", "-i", inventory, "--limit", target_host, playbook],
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


def update_ticket(ticket_id, note, close=False):
    url = f"{ZAMMAD_URL}/api/v1/tickets/{ticket_id}"
    payload = {"article": {"body": note, "internal": True}}
    if close:
        payload["state_id"] = 4
    response = requests.put(url, headers=HEADERS, json=payload)
    if response.status_code == 200:
        print(f"Ticket #{ticket_id} updated successfully.")
    else:
        print(f"Failed to update ticket #{ticket_id}: {response.status_code}")
        print(response.text)


def tag_ticket(ticket_id, tag):
    url = f"{ZAMMAD_URL}/api/v1/tags/add"
    payload = {"object": "Ticket", "o_id": ticket_id, "item": tag}
    response = requests.post(url, headers=HEADERS, json=payload)
    if response.status_code != 200:
        print(f"Failed to tag ticket #{ticket_id}: {response.status_code}")
        print(response.text)


def handle_disk_ticket(ticket_id, ticket_number, ticket_title, ticket_body, known_servers):
    server = extract_server_name(ticket_title, ticket_body, known_servers)

    if not server:
        update_ticket(
            ticket_id,
            "Automation: could not determine which server this ticket refers to. Escalating to L2 for manual triage.",
            close=False,
        )
        print(f"Ticket #{ticket_number}: no server identified, escalated to L2.")
        tag_ticket(ticket_id, PROCESSED_TAG)
        return

    output = run_disk_check(target_host=server)
    if not output:
        update_ticket(ticket_id, f"Automation error: could not run disk check on {server}. Escalating to L2.", close=False)
        print(f"Ticket #{ticket_number}: check failed, escalated to L2.")
        tag_ticket(ticket_id, PROCESSED_TAG)
        return

    for play in output.get("plays", []):
        for task in play.get("tasks", []):
            task_result = task.get("hosts", {}).get(server, {})
            if "msg" in task_result:
                msg = task_result["msg"]
                if "below threshold" in msg:
                    update_ticket(ticket_id, f"Automated check on {server}: {msg}", close=True)
                    print(f"Ticket #{ticket_number}: resolved, closed.")
                    tag_ticket(ticket_id, PROCESSED_TAG)
                    return

    update_ticket(
        ticket_id,
        f"Automation attempted cleanup on {server} but could not confirm resolution. Escalating to L2.",
        close=False,
    )
    print(f"Ticket #{ticket_number}: cleanup inconclusive, escalated to L2.")
    tag_ticket(ticket_id, PROCESSED_TAG)


if __name__ == "__main__":
    if not ZAMMAD_URL or not ZAMMAD_TOKEN:
        print("Missing ZAMMAD_URL or ZAMMAD_TOKEN in your .env file.")
    else:
        known_servers = load_known_servers()
        print(f"Known servers (from inventory): {known_servers}")

        tickets = find_open_disk_tickets()
        if not tickets:
            print("No open disk-related tickets found.")
        else:
            print(f"Found {len(tickets)} disk-related ticket(s).")
            for t in tickets:
                handle_disk_ticket(
                    t["id"], t["number"], t.get("title", ""), t.get("note", ""), known_servers
                )