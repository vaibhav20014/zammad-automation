from mcp import StdioServerParameters
from crewai_tools import MCPServerAdapter

params = StdioServerParameters(command="ansible-mcp-server", args=[], env={})
with MCPServerAdapter(params) as tools:
    print([tool.name for tool in tools])