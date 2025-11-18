from langchain_core.tools import tool
from langgraph.runtime import get_runtime
import asyncio
from langgraph_distributed_agent.agent_runner import AgentRunner
import os
import dotenv
dotenv.load_dotenv()

@tool
async def get_city_weather(city: str, day: str) -> str:
    """
    Get the weather for a specific city and date.

    Parameters:
        city (str): Name of the city, e.g., "London".
        day (str): Date in "%Y-%m-%d" format

    Returns:
        str: Weather description for the given city and date.
    """
    print("current context", get_runtime().context)
    return f"On {day}, it's always sunny in {city}!"

async def main():
    runner = AgentRunner(
        agent_name="weather_agent",
        system_prompt="You are a economist.",
        redis_url=os.environ.get("REDIS_URL", ""),
        mysql_url=os.environ.get("CHECKPOINT_DB_URL", ""),
        openai_base_url=os.environ.get(
            "OPENAI_BASE_URL", ""),
        openai_model=os.environ.get("OPENAI_MODEL", ""),
        openai_api_key=os.environ.get("OPENAI_API_KEY", "")
    )
    runner.add_tool(get_city_weather)
    await runner.add_mcp_server("http://localhost:8000/demo/mcp")  # mcp server
    await runner.start()

if __name__ == '__main__':
    asyncio.run(main())
