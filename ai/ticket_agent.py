"""
AI-Powered Ticket Agent & Router (decision center).

The model may search/fetch KB, run a catalog Ansible playbook, or plan/apply
a catalog Terraform module, then must finish with submit_final_response.

Python enforces safety rails before anything is written to Zammad:
  - Ansible only against inventory hosts and catalog playbook ids
  - Terraform only against catalog module ids
  - kb_answer only if articles were fetched this run
  - ansible_resolved / terraform_resolved only if the run confirmed success
  - everything else is L1/L2/L3 escalation with a holding reply
"""

import logging
import os

from google import genai
from google.genai import types

from catalogs import loader
from clients import ansible_client, terraform_client
from config import settings
from kb import knowledge_base_client
from services import escalation_service

logger = logging.getLogger(__name__)

_agent_cfg = loader.agent_config()
MODEL = settings.kb_answer_model or os.getenv("KB_ANSWER_MODEL", "gemini-2.5-flash")
MAX_TOOL_ITERATIONS = int(_agent_cfg.get("max_tool_iterations", 8))

HOLDING_REPLY = _agent_cfg.get(
    "holding_reply",
    "Thank you for contacting us. We are currently looking into this "
    "and will follow up with you shortly.",
)

L1_INTERNAL_NOTE = "Assigned to L1 for manual review. Customer was informed that we are working on it."
L2_INTERNAL_NOTE = "Assigned to L2 (engineering). Customer was informed that we are working on it."
L3_INTERNAL_NOTE = "Assigned to L3 (vendor/expert). Customer was informed that we are working on it."

_INTERNAL_BY_ACTION = {
    "escalate_l1": L1_INTERNAL_NOTE,
    "escalate_l2": L2_INTERNAL_NOTE,
    "escalate_l3": L3_INTERNAL_NOTE,
}

_client = genai.Client(api_key=settings.gemini_api_key or os.getenv("GEMINI_API_KEY"))

_SYSTEM_PROMPT = """You are the incident-automation decision center for Zammad.

Investigate with tools, then finish with exactly one submit_final_response.

Decision policy:
- How-to / password / account: if a KB title looks relevant, call
  get_answer_content. Use kb_answer only when a fetched article actually
  solves the request.
- Config / small OS tasks (disk cleanup, app config, patching): call
  run_ansible_job with a catalog playbook_id and an inventory hostname.
  Use ansible_resolved only if the playbook confirms success.
- Infra creation / provisioning (AWS VM, stacks, networks): call
  run_terraform_job with a catalog module_id. For an AWS VM request
  such as "2 vCPU and 4 GB RAM", use module_id aws_vm with vcpu and
  memory_gb from the ticket. Never pick a size that is not in the catalog.
  Use terraform_resolved only if apply succeeded. If you only have a plan,
  use terraform_needs_approval.
- If automation cannot solve it: escalate_l1 (simple/manual review),
  escalate_l2 (engineering), or escalate_l3 (vendor/expert/security).
  Public reply for escalation can be short; the system sends a holding reply.
- Never invent facts, hostnames, playbook ids, or module ids.
- When finished, call submit_final_response exactly once."""

_TOOLS = types.Tool(function_declarations=[
    types.FunctionDeclaration(
        name="get_answer_content",
        description="Fetch the full title+body of a KB article by id.",
        parameters={
            "type": "object",
            "properties": {"answer_id": {"type": "integer"}},
            "required": ["answer_id"],
        },
    ),
    types.FunctionDeclaration(
        name="run_ansible_job",
        description=(
            "Run one catalog Ansible playbook. Host must be in inventory "
            "when the playbook requires a host."
        ),
        parameters={
            "type": "object",
            "properties": {
                "playbook_id": {
                    "type": "string",
                    "description": "Catalog id such as disk_cleanup, app_config, system_patch.",
                },
                "host": {
                    "type": "string",
                    "description": "Exact inventory hostname when required.",
                },
            },
            "required": ["playbook_id"],
        },
    ),
    types.FunctionDeclaration(
        name="run_terraform_job",
        description="Plan (and apply only if allowed) a catalog Terraform module.",
        parameters={
            "type": "object",
            "properties": {
                "module_id": {
                    "type": "string",
                    "description": "Catalog id such as aws_vm, webapp_stack, analytics_stack, network_sg.",
                },
                "vcpu": {
                    "type": "integer",
                    "description": "Requested vCPU count for aws_vm (e.g. 2).",
                },
                "memory_gb": {
                    "type": "integer",
                    "description": "Requested RAM in GB for aws_vm (e.g. 4).",
                },
                "vm_name": {
                    "type": "string",
                    "description": "Optional name tag for the VM.",
                },
            },
            "required": ["module_id"],
        },

    ),
    types.FunctionDeclaration(
        name="submit_final_response",
        description="Finish the task with one routing action.",
        parameters={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "kb_answer",
                        "ansible_resolved",
                        "terraform_resolved",
                        "terraform_needs_approval",
                        "escalate_l1",
                        "escalate_l2",
                        "escalate_l3",
                    ],
                },
                "public_reply": {"type": "string"},
                "internal_note": {"type": "string"},
                "used_article_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                },
                "ansible_host": {"type": "string"},
                "ansible_playbook_id": {"type": "string"},
                "terraform_module_id": {"type": "string"},
                "confidence": {
                    "type": "string",
                    "enum": ["high", "medium", "low"],
                },
                "reasoning": {"type": "string"},
            },
            "required": [
                "action",
                "public_reply",
                "internal_note",
                "used_article_ids",
                "confidence",
                "reasoning",
            ],
        },
    ),
])


def _resolve_inventory_host(host: str, known_servers: set[str]) -> str | None:
    wanted = (host or "").strip().lower()
    if not wanted:
        return None
    for server in known_servers:
        if server.lower() == wanted:
            return server
    return None


def _text_blob(output: dict, host: str | None) -> str:
    chunks = [str(output.get("_stderr") or "")]
    for play in output.get("plays") or []:
        for task in play.get("tasks") or []:
            hosts = task.get("hosts") or {}
            if host and host in hosts:
                rows = [hosts[host]]
            else:
                rows = list(hosts.values())
            for task_result in rows:
                if not isinstance(task_result, dict):
                    continue
                chunks.append(str(task_result.get("msg", "")))
                chunks.append(str(task_result.get("stdout", "")))
    return "\n".join(chunks).lower()


def _summarize_ansible(output: dict, host: str | None, playbook: dict) -> dict:
    markers = [m.lower() for m in (playbook.get("success_markers") or [])]
    blob = _text_blob(output, host)
    resolved = bool(markers) and any(m in blob for m in markers)
    if output.get("_returncode") not in (None, 0):
        resolved = False
    tasks = []
    for play in output.get("plays") or []:
        for task in play.get("tasks") or []:
            tasks.append(task.get("task", {}).get("name", ""))
    return {
        "ok": True,
        "resolved": resolved,
        "host": host or "",
        "playbook_id": playbook.get("id"),
        "playbook": playbook.get("playbook"),
        "tasks": tasks[:20],
    }


def _fallback(reason: str, ticket_text: str = "") -> dict:
    level = escalation_service.infer_level(ticket_text)
    return {
        "action": f"escalate_{level}",
        "public_reply": HOLDING_REPLY,
        "internal_note": reason,
        "used_article_ids": [],
        "ansible_host": "",
        "ansible_playbook_id": "",
        "terraform_module_id": "",
        "terraform_instance_type": "",
        "confidence": "low",
        "reasoning": reason,
    }


def _base_safe(decision: dict) -> dict:
    used_ids = [int(i) for i in (decision.get("used_article_ids") or [])]
    return {
        "action": "escalate_l2",
        "public_reply": HOLDING_REPLY,
        "internal_note": (decision.get("internal_note") or decision.get("reasoning") or "").strip(),
        "used_article_ids": used_ids,
        "ansible_host": (decision.get("ansible_host") or "").strip(),
        "ansible_playbook_id": (decision.get("ansible_playbook_id") or "").strip(),
        "terraform_module_id": (decision.get("terraform_module_id") or "").strip(),
        "terraform_instance_type": (decision.get("terraform_instance_type") or "").strip(),
        "terraform_vm_name": (decision.get("terraform_vm_name") or "").strip(),
        "confidence": decision.get("confidence") or "low",
        "reasoning": (decision.get("reasoning") or "").strip(),
    }


def _enforce_rails(decision: dict, session: dict, ticket_text: str) -> dict:
    action = decision.get("action")
    fetched = set(session.get("fetched_article_ids") or [])
    ansible_runs = session.get("ansible_runs") or {}
    terraform_runs = session.get("terraform_runs") or {}
    public_reply = (decision.get("public_reply") or "").strip() or HOLDING_REPLY
    safe = _base_safe(decision)

    if action == "kb_answer":
        used_ids = safe["used_article_ids"]
        grounded = bool(used_ids) and all(i in fetched for i in used_ids)
        if grounded and safe["confidence"] == "high" and public_reply != HOLDING_REPLY:
            safe["action"] = "kb_answer"
            safe["public_reply"] = public_reply
            return safe
        safe["action"] = "escalate_l2"
        safe["internal_note"] = (
            "Automation: kb_answer rejected (missing fetched articles, "
            f"confidence={safe['confidence']}, or empty grounded reply). "
            f"Model reasoning: {safe['reasoning']}"
        )
        return safe

    if action == "ansible_resolved":
        key = safe["ansible_playbook_id"] or ""
        host = safe["ansible_host"]
        run = ansible_runs.get(f"{key}:{host}") or {}
        if not run.get("resolved"):
            resolved_runs = [r for r in ansible_runs.values() if r.get("resolved")]
            if len(resolved_runs) == 1:
                run = resolved_runs[0]
                safe["ansible_host"] = run.get("host") or host
                safe["ansible_playbook_id"] = run.get("playbook_id") or key
        if run.get("resolved"):
            safe["action"] = "ansible_resolved"
            return safe
        safe["action"] = "escalate_l2"
        safe["internal_note"] = (
            "Automation: ansible_resolved rejected "
            f"(playbook={key or 'none'}, host={host or 'none'}). "
            f"Model reasoning: {safe['reasoning']}"
        )
        return safe

    if action == "terraform_resolved":
        module_id = safe["terraform_module_id"]
        run = terraform_runs.get(module_id) or {}
        if not run.get("applied"):
            applied = [r for r in terraform_runs.values() if r.get("applied")]
            if len(applied) == 1:
                run = applied[0]
                safe["terraform_module_id"] = run.get("module_id") or module_id
        if run.get("applied"):
            safe["action"] = "terraform_resolved"
            safe["terraform_instance_type"] = run.get("instance_type") or safe["terraform_instance_type"]
            return safe
        if run.get("planned"):
            safe["action"] = "terraform_needs_approval"
            safe["terraform_instance_type"] = run.get("instance_type") or safe["terraform_instance_type"]
            plan_tail = (run.get("plan_stdout") or "")[-1500:]
            size = run.get("instance_type") or "catalog size"
            safe["internal_note"] = (
                f"Terraform plan ready for module '{run.get('module_id')}' "
                f"instance_type={size}. Apply is disabled. Plan tail:\n{plan_tail}"
            )
            return safe
        safe["action"] = "escalate_l2"
        safe["internal_note"] = (
            "Automation: terraform_resolved rejected "
            f"(module={module_id or 'none'}). Model reasoning: {safe['reasoning']}"
        )
        return safe

    if action == "terraform_needs_approval":
        module_id = safe["terraform_module_id"]
        run = terraform_runs.get(module_id) or {}
        if not run.get("planned"):
            planned = [r for r in terraform_runs.values() if r.get("planned")]
            if len(planned) == 1:
                run = planned[0]
                safe["terraform_module_id"] = run.get("module_id") or module_id
        if run.get("planned"):
            safe["action"] = "terraform_needs_approval"
            safe["terraform_instance_type"] = (
                run.get("instance_type") or safe.get("terraform_instance_type") or ""
            )
            safe["terraform_vm_name"] = run.get("vm_name") or safe.get("terraform_vm_name") or "" 
            if not safe["internal_note"] or "plan" not in safe["internal_note"].lower():
                size = safe["terraform_instance_type"] or "catalog size"
                plan_tail = (run.get("plan_stdout") or "")[-1500:]
                safe["internal_note"] = (
                    f"Terraform plan ready for module '{run.get('module_id')}' "
                    f"instance_type={size}. Apply is disabled. Plan tail:\n{plan_tail}"
                )
            return safe
        safe["action"] = "escalate_l2"
        safe["internal_note"] = (
            "Automation: terraform_needs_approval rejected (no successful plan). "
            f"Model reasoning: {safe['reasoning']}"
        )
        return safe

    if action in {"escalate_l1", "escalate_l2", "escalate_l3"}:
        safe["action"] = action
        safe["public_reply"] = HOLDING_REPLY
        if not safe["internal_note"]:
            safe["internal_note"] = _INTERNAL_BY_ACTION[action]
        return safe

    safe["action"] = escalation_service.normalize_action(action, ticket_text)
    safe["public_reply"] = HOLDING_REPLY
    if not safe["internal_note"]:
        safe["internal_note"] = (
            f"Automation: no KB/Ansible/Terraform resolution. {safe['reasoning']}"
        )
    return safe


def resolve_ticket(
    ticket_text: str,
    title: str,
    kb_titles: list[dict],
    known_servers: set[str],
) -> dict:
    session = {
        "fetched_article_ids": [],
        "ansible_runs": {},
        "terraform_runs": {},
    }

    titles_block = "\n".join(
        f"[id={h['id']}] {h['title']}" + (f" (score={h['score']})" if "score" in h else "")
        for h in kb_titles
    ) or "(none)"
    servers_block = "\n".join(sorted(known_servers)) or "(none)"
    playbooks_block = "\n".join(
        f"- {p.get('id')}: {p.get('name')} (file={p.get('playbook')}, "
        f"requires_host={p.get('requires_host', True)})"
        for p in loader.ansible_playbooks()
    ) or "(none)"
    modules_block = "\n".join(
        f"- {m.get('id')}: {m.get('name')} (path={m.get('path')}, "
        f"auto_apply={m.get('auto_apply', False)})"
        for m in loader.terraform_modules()
    ) or "(none)"

    contents = [
        types.Content(role="user", parts=[types.Part(text=(
            f"Ticket title:\n{title}\n\n"
            f"Customer / incident ticket:\n{ticket_text}\n\n"
            f"Retrieved KB article titles (vector search):\n{titles_block}\n\n"
            f"Known inventory servers (Ansible only these):\n{servers_block}\n\n"
            f"Ansible playbook catalog:\n{playbooks_block}\n\n"
            f"Terraform module catalog:\n{modules_block}"
        ))])
    ]

    for iteration in range(MAX_TOOL_ITERATIONS):
        try:
            response = _client.models.generate_content(
                model=MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=_SYSTEM_PROMPT,
                    tools=[_TOOLS],
                ),
            )
        except Exception:
            logger.exception("Gemini call failed during ticket orchestration")
            break

        candidate = response.candidates[0]
        contents.append(candidate.content)

        function_calls = [
            part.function_call for part in candidate.content.parts
            if part.function_call is not None
        ]
        if not function_calls:
            logger.warning("Model returned no tool call on iteration %d; stopping.", iteration)
            break

        submitted = None
        function_response_parts = []

        for call in function_calls:
            args = dict(call.args) if call.args else {}
            if call.name == "submit_final_response":
                submitted = args
                continue

            logger.info("Model called %s(%s)", call.name, args)
            result = _execute_tool_call(call.name, args, known_servers, session)
            function_response_parts.append(
                types.Part(function_response=types.FunctionResponse(
                    name=call.name, response=result
                ))
            )

        if submitted is not None:
            logger.info(
                "Ticket agent finished: action=%s confidence=%s articles=%s "
                "playbook=%s host=%s module=%s",
                submitted.get("action"),
                submitted.get("confidence"),
                submitted.get("used_article_ids"),
                submitted.get("ansible_playbook_id"),
                submitted.get("ansible_host"),
                submitted.get("terraform_module_id"),
            )
            return _enforce_rails(submitted, session, ticket_text)

        if function_response_parts:
            contents.append(types.Content(role="user", parts=function_response_parts))

    logger.warning("Ticket agent hit max iterations or failed without a final response.")
    return _fallback("Model did not produce a final decision within the allowed steps.", ticket_text)


def _execute_tool_call(
    name: str, args: dict, known_servers: set[str], session: dict
) -> dict:
    if name == "get_answer_content":
        answer_id = int(args["answer_id"])
        content = knowledge_base_client.get_answer_content(answer_id)
        if not content:
            return {"error": f"Could not fetch article id={answer_id}."}
        session["fetched_article_ids"].append(answer_id)
        return {
            "id": answer_id,
            "title": content.get("title", ""),
            "body": content.get("body", ""),
        }

    if name == "run_ansible_job":
        playbook = loader.playbook_by_id(str(args.get("playbook_id") or ""))
        if not playbook:
            return {
                "ok": False,
                "error": "Unknown playbook_id. Use an id from the Ansible catalog.",
                "requested": args.get("playbook_id"),
            }
        host = None
        if playbook.get("requires_host", True):
            host = _resolve_inventory_host(args.get("host", ""), known_servers)
            if not host:
                return {
                    "ok": False,
                    "error": "Host is not in inventory. Do not invent a hostname.",
                    "requested": args.get("host", ""),
                }
        output = ansible_client.run_playbook(playbook["playbook"], target_host=host)
        if not output:
            summary = {
                "ok": False,
                "resolved": False,
                "host": host or "",
                "playbook_id": playbook["id"],
                "error": "Playbook failed, timed out, missing, or returned no JSON.",
            }
            session["ansible_runs"][f"{playbook['id']}:{host or ''}"] = summary
            return summary
        summary = _summarize_ansible(output, host, playbook)
        session["ansible_runs"][f"{playbook['id']}:{host or ''}"] = summary
        return summary

    if name == "run_terraform_job":
        module = loader.module_by_id(str(args.get("module_id") or ""))
        if not module:
            return {
                "ok": False,
                "error": "Unknown module_id. Use an id from the Terraform catalog.",
                "requested": args.get("module_id"),
            }
        tf_vars = {"aws_region": settings.aws_region}
        if module.get("allowed_sizes"):
            vcpu = args.get("vcpu") if args.get("vcpu") is not None else 2
            memory_gb = args.get("memory_gb") if args.get("memory_gb") is not None else 4
            instance_type = terraform_client.resolve_instance_type(module, vcpu, memory_gb)
            if not instance_type:
                return {
                    "ok": False,
                    "applied": False,
                    "planned": False,
                    "error": (
                        "Requested size is not in the catalog. Allowed: "
                        + ", ".join(
                            f"{s.get('vcpu')} vCPU / {s.get('memory_gb')} GB "
                            f"({s.get('instance_type')})"
                            for s in module.get("allowed_sizes") or []
                        )
                    ),
                    "requested_vcpu": vcpu,
                    "requested_memory_gb": memory_gb,
                }
            tf_vars["instance_type"] = instance_type
            tf_vars["vm_name"] = (args.get("vm_name") or "zammad-requested-vm")[:64]
        result = terraform_client.run_module(
            module["path"],
            auto_apply=bool(module.get("auto_apply")),
            tf_vars=tf_vars,
        )
        result["module_id"] = module["id"]
        result["instance_type"] = tf_vars.get("instance_type", "")
        result["vm_name"] = tf_vars.get("vm_name", "")  
        session["terraform_runs"][module["id"]] = result
        return result

    return {"error": f"Unknown tool: {name}"}
