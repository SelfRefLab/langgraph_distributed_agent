
import asyncio
from langgraph_distributed_agent.agent_runner import AgentRunner
import os
import dotenv
dotenv.load_dotenv()


async def main():
    runner = AgentRunner(
        agent_name="main_agent",
        system_prompt="""
You are a help assistant.
You can choose to answer the questions yourself or entrust them to more professional experts"
""",
        redis_url=os.environ.get("REDIS_URL", ""),
        mysql_url=os.environ.get("CHECKPOINT_DB_URL", ""),
        openai_base_url=os.environ.get(
            "OPENAI_BASE_URL", ""),
        openai_model=os.environ.get("OPENAI_MODEL", ""),
        openai_api_key=os.environ.get("OPENAI_API_KEY", "")
    )
    await runner.add_mcp_server("http://localhost:8000/demo/mcp")  # mcp server
    runner.add_subagent(agent_name="weather_agent",description="Good at answering weather questions") 
    runner.add_subagent(agent_name="economics_agent",description="Good at answering economic questions") 
    await runner.start()

if __name__ == '__main__':
    asyncio.run(main())


if __name__ == '__main__':
    asyncio.run(main())

