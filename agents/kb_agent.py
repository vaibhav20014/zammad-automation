"""
KB specialist - checks the knowledge base for a matching article and
drafts a reply. Delegates the actual "which article, what does it say"
reasoning to the nested agent in ai/answer_generator.py.
"""

from crewai import Agent
from tools import kb_tools
from config import settings

ROLE = "Knowledge base specialist"
GOAL = "Find a matching KB article for the ticket and draft an accurate, confidence-rated reply"
BACKSTORY = (
    "You answer tickets using the company knowledge base - including "
    "action-shaped requests like password resets, not just questions. "
    "Never guess an answer from a title alone; always read the full "
    "article content before replying. If nothing in the KB is relevant, "
    "say so rather than fabricating an answer."
)


def build_kb_agent() -> Agent:
    return Agent(
        role=ROLE,
        goal=GOAL,
        backstory=BACKSTORY,
        tools=kb_tools.get_tools(),
        llm=settings.model,
        verbose=False,
    )