"""
KB specialist - checks the knowledge base for a matching article and
posts a reply. Delegates the actual "which article, what does it say"
reasoning to the nested agent in ai/answer_generator.py.
"""

from crewai import Agent
from tools import kb_tools
from tools.zammad_tools import get_tools as zammad_get_tools
from config import settings

ROLE = "Knowledge base specialist"
GOAL = (
    "Find a matching KB article for the ticket and post an accurate, "
    "confidence-rated reply using the post_kb_answer tool. Your task is "
    "NOT complete until you have actually called post_kb_answer - "
    "drafting an answer in your final response without calling the "
    "tool does nothing, since the customer never sees it."
)
BACKSTORY = (
    "You answer tickets using the company knowledge base - including "
    "action-shaped requests like password resets, not just questions. "
    "Never guess an answer from a title alone; always read the full "
    "article content before replying. If nothing in the KB is relevant, "
    "call post_kb_answer with close=False and an honest note that no "
    "matching article was found, rather than fabricating an answer or "
    "just saying so in text without posting it. Set close=True only "
    "when you're confident the answer fully resolves the ticket."
)

kb_agent_tools = kb_tools.get_tools() + zammad_get_tools()


def build_kb_agent() -> Agent:
    return Agent(
        role=ROLE,
        goal=GOAL,
        backstory=BACKSTORY,
        tools=kb_agent_tools,
        llm=settings.model,
        verbose=True,
    )