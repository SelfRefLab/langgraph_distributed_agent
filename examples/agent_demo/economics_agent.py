from langgraph.runtime import get_runtime
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool, InjectedToolCallId
from typing import Annotated
import asyncio
from langgraph_distributed_agent.utils import human_approval_required
from langgraph_distributed_agent.agent_runner import AgentRunner
import os
import dotenv
dotenv.load_dotenv()

# config and injected_tool_call_id is injected by langgraph
@tool
@human_approval_required
def get_city_gdp(city: str,
                 config: RunnableConfig,
                 injected_tool_call_id: Annotated[str, InjectedToolCallId]) -> str:
    """Get city gdp"""
    print(get_runtime())
    return f"The gdp of {city} is 500 billion yuan!"


async def main():
    runner = AgentRunner(
        agent_name="economics_agent",
        system_prompt="You are a economist.",
        redis_url=os.environ.get("REDIS_URL", ""),
        mysql_url=os.environ.get("CHECKPOINT_DB_URL", ""),
        openai_base_url=os.environ.get(
            "OPENAI_BASE_URL", ""),
        openai_model=os.environ.get("OPENAI_MODEL", ""),
        openai_api_key=os.environ.get("OPENAI_API_KEY", "")
    )
    runner.add_tool(get_city_gdp)
    await runner.start()

if __name__ == '__main__':
    asyncio.run(main())
