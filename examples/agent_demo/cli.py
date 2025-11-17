import asyncio
from langgraph_distributed_agent.agent_cli import AgentCLI
import os
import dotenv

dotenv.load_dotenv()

async def main():
    cli = AgentCLI(target_agent="main_agent",
                         redis_url=os.environ.get("REDIS_URL", ""))
    await cli.run()

if __name__ == '__main__':
    asyncio.run(main())