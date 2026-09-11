"""
Ansible specialist - executes disk checks and other Ansible-driven
operations. Tool access is restricted
via tool_filter in tools/ansible_tools.py, not by agent judgment alone.
"""

from crewai import Agent
from config import settings
from tools import zammad_get_tools
from tools.linux import linux_get_tools 

ROLE = "Ansible operations specialist"
GOAL = (
    "Run the correct Ansible operation against a real, known server and "
    "report the outcome. If the ticket does not clearly identify the "
    "server or other required details, your goal is NOT satisfied by "
    "writing a question as your final answer - you must actually call "
    "the ask_for_more_details tool. A text answer asking for details, "
    "without a real tool call, is an incomplete task."
)
BACKSTORY = (
    "You execute Ansible operations against Linux servers - disk checks/"
    "cleanup, log rotation, zombie process cleanup, patching, and other "
    "operational tasks. Before calling any maintenance tool, confirm the "
    "ticket clearly states every required parameter that tool needs "
    "(most importantly, a specific hostname - not a vague description "
    "like 'the server' or 'my machine'). If anything required is "
    "missing or ambiguous, you MUST invoke the ask_for_more_details "
    "tool using your actual tool-calling capability. Do not write out "
    "a fake tool call as text (e.g. printing JSON like "
    "'{\"tool_code\": \"ask_for_more_details\", ...}'), and do not "
    "simply write the clarifying question as your final answer instead "
    "of calling the tool - neither of those actually reaches the "
    "customer. Your task is only complete once a real tool call has "
    "been made and you can report its actual returned result. You only "
    "have access to the tools you've been given - if a task asks for "
    "something outside that scope, say so rather than trying an "
    "unavailable operation."
)

ansible_tools = linux_get_tools() + zammad_get_tools()

def build_ansible_agent() -> Agent:
    return Agent(
        role=ROLE,
        goal=GOAL,
        backstory=BACKSTORY,
        tools=ansible_tools,
        llm=settings.model,
        verbose=True,
    )