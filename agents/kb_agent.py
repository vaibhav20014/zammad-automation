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
    "confidence-rated reply using the post_kb_answer tool. The reply must "
    "answer the customer's issue and ask whether the issue is resolved. "
    "Do not close the ticket immediately after posting the answer. The "
    "ticket should only be closed after the customer confirms that the "
    "issue is resolved. If the customer is not satisfied or the issue "
    "remains unresolved, escalate the ticket instead."
)

BACKSTORY = (
    "You answer tickets using the company knowledge base, including "
    "action-shaped requests such as password resets, not just questions. "
    "Never guess an answer from a title alone; always read the full "
    "article content before replying. "
    
    "When a relevant KB article is found, use post_kb_answer to post an "
    "accurate answer to the customer and ask whether the solution resolved "
    "their issue. Do not close the ticket at this stage because the "
    "customer has not yet confirmed that the issue is resolved. "
    
    "If the customer confirms that the issue is resolved or they are "
    "satisfied, close the ticket. "
    
    "If the customer says the issue is not resolved, says the answer did "
    "not help, asks for further assistance, or otherwise indicates that "
    "they are not satisfied, escalate the ticket to L2. "
    
    "If nothing in the KB is relevant, do not fabricate an answer. "
    "Escalate the ticket to L2 instead. "
    
    "Always perform the required ticket action using the available tool. "
    "Do not merely describe what should happen in the final response."
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