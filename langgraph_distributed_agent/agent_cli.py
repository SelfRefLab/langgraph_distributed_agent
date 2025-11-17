import asyncio
import os
import uuid
import dotenv
from colorama import Fore, init
from langgraph_distributed_agent.agent_client import AgentClient

dotenv.load_dotenv()
init(autoreset=True)

class AgentCLI:
    def __init__(self, target_agent: str, redis_url: str):
        self.client = AgentClient(target_agent=target_agent, redis_url=redis_url)
        self.context_id = str(uuid.uuid4())
        self.running = True

    async def ask_question(self):
        """Prompt the user for a question and send it to the agent."""
        question = input(Fore.YELLOW + "Input your Question: ")
        if question.lower() == 'exit':
            self.running = False
            return
        await self.client.send_message(question, self.context_id)

    async def handle_interrupt(self):
        """Handle an interrupt event by asking the user for confirmation."""
        last_event = await self.client.get_last_event(self.context_id)
        if last_event is None or last_event.data.type!='interrupt':
            return False
        
        inp = input(
            Fore.RED + f"Agent {last_event.data.callee_agent} requests tool execution. Accept? (y/n): "
        ).strip().lower()
        if inp == 'y':
            return await self.client.accept_tool_invocation(self.context_id)
        else:
            return await self.client.reject_tool_invocation(self.context_id)

    async def stream_events(self):
        """Continuously stream events for the current context."""
        async for event in self.client.progress_events(self.context_id):
            AgentClient.print_progress_event(event,display_human_message=False)
            
    async def run(self):
        """Main CLI loop."""
        try:
            while self.running:
                has_interrupt = await self.handle_interrupt()
                if not has_interrupt:
                    await self.ask_question()
                
                if not self.running:
                    break
                
                await self.stream_events()
        finally:
            await self.client.disconnect()