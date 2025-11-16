import asyncio
from langgraph_distributed_agent.agent_client import AgentClient
import uuid
import os
import dotenv

dotenv.load_dotenv()

async def main():
    client = AgentClient(target_agent="main_agent",
                         redis_url=os.environ.get("REDIS_URL", ""))
    context_id = str(uuid.uuid4())
    while True:
        question = input("Input your Question:")
        await client.send_message(question, context_id)
        await client.listen_for_responses(context_id)


if __name__ == '__main__':
    asyncio.run(main())