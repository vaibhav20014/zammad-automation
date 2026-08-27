import os
import json
import requests
from datetime import datetime, timezone
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


def get_problems(auth_token):
    payload = {
        "jsonrpc": "2.0",
        "method": "problem.get",
        "params": {
            "output": "extend",
            "recent": False,
        },
        "auth": auth_token,
        "id": 2,
    }
    response = requests.post(ZABBIX_URL, json=payload)
    return response.json().get("result", [])


def get_hostname_for_trigger(auth_token, trigger_id):
    payload = {
        "jsonrpc": "2.0",
        "method": "trigger.get",
        "params": {
            "output": ["triggerid", "description"],
            "triggerids": trigger_id,
        },
        "auth": auth_token,
        "id": 3,
    }

    response = requests.post(ZABBIX_URL, json=payload)
    print("TRIGGER RESPONSE:", response.json())

    result = response.json().get("result", [])

    if result:
        return result[0].get("description", "unknown-host")

    return "unknown-host"


def load_processed_events():
    if os.path.exists(PROCESSED_EVENTS_FILE):
        with open(PROCESSED_EVENTS_FILE, "r") as f:
            return json.load(f)
    return {}


def save_processed_events(events):
    with open(PROCESSED_EVENTS_FILE, "w") as f:
        json.dump(events, f, indent=2)


def create_zammad_ticket(hostname, problem_name):
    title = f"Disk space warning on {hostname}"
    url = f"{ZAMMAD_URL}/api/v1/tickets"
    payload = {
        "title": title,
        "group": "L1-Support",
        "customer_id": "guess:zabbix@yourdomain.com",
        "article": {
            "subject": title,
            "body": f"Zabbix alert: {problem_name} on host {hostname}.",
            "type": "note",
            "internal": True,
        },
    }
    response = requests.post(url, headers=ZAMMAD_HEADERS, json=payload)
    if response.status_code in (200, 201):
        data = response.json()
        print(f"Created ticket #{data.get('number')} for {hostname}: {problem_name}")
        return data
    else:
        print(f"Failed to create ticket for {hostname}: {response.status_code}")
        print(response.text)
        return None


if __name__ == "__main__":
    if not all([ZABBIX_URL, ZABBIX_USER, ZABBIX_PASSWORD, ZAMMAD_URL, ZAMMAD_TOKEN]):
        print("Missing one or more required .env variables.")
    else:
        auth_token = zabbix_login()
        if not auth_token:
            print("Zabbix login failed.")
        else:
            problems = get_problems(auth_token)
            processed = load_processed_events()

            new_count = 0
            for p in problems:
                event_id = p["eventid"]
                if event_id in processed:
                    continue

                hostname = get_hostname_for_trigger(auth_token, p["objectid"])
                problem_name = p.get("name", "Disk issue")

                print(f"DEBUG: event_id={event_id} hostname='{hostname}' problem_name='{problem_name}'")

                ticket = create_zammad_ticket(hostname, problem_name)

                processed[event_id] = {
                    "hostname": hostname,
                    "problem_name": problem_name,
                    "ticket_number": ticket.get("number") if ticket else None,
                    "ticket_id": ticket.get("id") if ticket else None,
                    "processed_at": datetime.now(timezone.utc).isoformat(),
                    "ticket_created": ticket is not None,
                }
                new_count += 1

            save_processed_events(processed)
            print(f"Processed {new_count} new Zabbix problem(s).")