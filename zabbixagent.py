import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

ZABBIX_URL = os.getenv("ZABBIX_URL")
ZABBIX_USER = os.getenv("ZABBIX_USER")
ZABBIX_PASSWORD = os.getenv("ZABBIX_PASSWORD")

ZAMMAD_URL = os.getenv("ZAMMAD_URL")
ZAMMAD_TOKEN = os.getenv("ZAMMAD_TOKEN")

ZAMMAD_HEADERS = {
    "Authorization": f"Token token={ZAMMAD_TOKEN}",
    "Content-Type": "application/json",
}

PROCESSED_EVENTS_FILE = "/home/ubuntu/zammad-automation/processed_zabbix_events.json"


def zabbix_login():
    payload = {
        "jsonrpc": "2.0",
        "method": "user.login",
        "params": {"username": ZABBIX_USER, "password": ZABBIX_PASSWORD},
        "id": 1,
    }
    response = requests.post(ZABBIX_URL, json=payload)
    return response.json().get("result")


def get_disk_problems(auth_token):
    """Fetch active Zabbix problems related to disk space."""
    payload = {
        "jsonrpc": "2.0",
        "method": "problem.get",
        "params": {
            "output": "extend",
            "recent": False,
            "search": {"name": "disk"},
        },
        "auth": auth_token,
        "id": 2,
    }
    response = requests.post(ZABBIX_URL, json=payload)
    return response.json().get("result", [])


def get_hostname_for_trigger(auth_token, trigger_id):
    """problem.get doesn't return host info directly in this Zabbix version,
    so look it up separately via the trigger's objectid."""
    payload = {
        "jsonrpc": "2.0",
        "method": "trigger.get",
        "params": {
            "output": "extend",
            "triggerids": trigger_id,
            "selectHosts": ["host"],
        },
        "auth": auth_token,
        "id": 3,
    }
    response = requests.post(ZABBIX_URL, json=payload)
    result = response.json().get("result", [])
    if result and result[0].get("hosts"):
        return result[0]["hosts"][0]["host"]
    return "unknown-host"


def load_processed_events():
    if os.path.exists(PROCESSED_EVENTS_FILE):
        with open(PROCESSED_EVENTS_FILE, "r") as f:
            return set(json.load(f))
    return set()


def save_processed_events(events):
    with open(PROCESSED_EVENTS_FILE, "w") as f:
        json.dump(list(events), f)


def create_zammad_ticket(hostname, problem_name):
    url = f"{ZAMMAD_URL}/api/v1/tickets"
    payload = {
        "title": f"Disk space warning on {hostname}",
        "group": "L1-Support",
        "customer_id": "guess:zabbix@yourdomain.com",
        "article": {
            "subject": f"Disk space warning on {hostname}",
            "body": f"Zabbix alert: {problem_name} on host {hostname}.",
            "type": "note",
            "internal": True,
        },
    }
    response = requests.post(url, headers=ZAMMAD_HEADERS, json=payload)
    if response.status_code == 200:
        print(f"Created ticket for {hostname}: {problem_name}")
    else:
        print(f"Failed to create ticket for {hostname}: {response.status_code}")
        print(response.text)


if __name__ == "__main__":
    if not all([ZABBIX_URL, ZABBIX_USER, ZABBIX_PASSWORD, ZAMMAD_URL, ZAMMAD_TOKEN]):
        print("Missing one or more required .env variables.")
    else:
        auth_token = zabbix_login()
        if not auth_token:
            print("Zabbix login failed.")
        else:
            problems = get_disk_problems(auth_token)
            processed = load_processed_events()

            new_count = 0
            for p in problems:
                event_id = p["eventid"]
                if event_id in processed:
                    continue
                hostname = get_hostname_for_trigger(auth_token, p["objectid"])
                problem_name = p.get("name", "Disk issue")
                create_zammad_ticket(hostname, problem_name)
                processed.add(event_id)
                new_count += 1

            save_processed_events(processed)
            print(f"Processed {new_count} new Zabbix problem(s).")