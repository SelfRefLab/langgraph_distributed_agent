import redis.asyncio as redis
import uuid
import json
from typing import List,Optional
from langgraph_distributed_agent.distributed_agent_worker import (
    AgentInvocationEvent,
    AgentCommandEvent,
    AgentInvocationData,
    AgentCommandData,
    ContextProgressEvent
)
from colorama import Fore, init

init(autoreset=True)

class AgentClient:
    def __init__(self, target_agent: str, redis_url: str) -> None:
        self.target_agent = target_agent
        self.redis = redis.from_url(redis_url, decode_responses=True)

    async def send_message(self, content: str, context_id: str, context_dict: Optional[dict]=None) -> None:
        invocation_id = f"invocation_{uuid.uuid4()}"
        event = AgentInvocationEvent(
            context_id=context_id,
            data=AgentInvocationData(
                task=content,
                caller_agent="human",
                invocation_id=invocation_id,
                context=context_dict or dict()
            )
        )
        await self.redis.xadd(f"agent_event:{self.target_agent}", {"data": event.model_dump_json()})

    async def _handle_tool_invocation(self, context_id: str, command: str) -> bool:
        last_event = await self.get_last_event(context_id)
        if not last_event or last_event.data.type != "interrupt":
            return False
        agent_name = last_event.data.callee_agent
        cmd = AgentCommandEvent(
            context_id=context_id,
            data=AgentCommandData(
                type="resume",
                tool_call_id=last_event.data.message['tool_call_id'],
                payload={"type": command}
            )
        )
        await self.redis.xadd(f"agent_event:{agent_name}", {"data": cmd.model_dump_json()})
        return True
        
    async def accept_tool_invocation(self, context_id: str):
        return await self._handle_tool_invocation(context_id,"accept")

    async def reject_tool_invocation(self, context_id: str):
        return await self._handle_tool_invocation(context_id,"reject")

    async def progress_events(self, context_id: str):

        stream_key = f"agent_task:{context_id}"
        group_name = f"consumer_group_{context_id}"
        try:
            await self.redis.xgroup_create(stream_key, group_name, id="0", mkstream=True)
        except Exception as e:
            if "BUSYGROUP" not in str(e):
                raise
                
        while True:
            messages = await self.redis.xreadgroup(
                groupname=group_name,
                consumername=str(uuid.uuid4()),
                streams={f"agent_task:{context_id}": ">"},
                count=10,
                block=1000
            )
            if not messages:
                continue
            for _, stream_messages in messages:
                for _, fields in stream_messages:
                    data = json.loads(fields["data"])
                    if data.get("event_type") == "agent_progress":
                        event = ContextProgressEvent.model_validate(data)
                        yield event
                        if (event.data.callee_agent == self.target_agent and event.data.is_finish) or event.data.type == "interrupt":
                            return
                        
    @staticmethod
    def print_progress_event(event: ContextProgressEvent, display_human_message: bool=True):
        
        if event.data.type == "message":
            msg = event.data.message
            if msg['type'] == 'human':
                if display_human_message:
                    print(Fore.CYAN + "Human:")
                    print(msg['content'])
            elif msg['type'] != 'human':
                print(Fore.CYAN + f"{event.data.callee_agent}:")
                if msg.get('content'):
                    print(Fore.GREEN + msg['content'])
                if msg.get('tool_calls'):
                    print(Fore.BLUE + "Tool call: " + str(msg['tool_calls']))
        elif event.data.type == 'interrupt':
            print(Fore.RED + "Received tool request; pausing for user confirmation.")
                        
                        
    async def get_last_event(self, context_id: str) -> Optional[ContextProgressEvent]:
        stream_key = f"agent_task:{context_id}"
        messages = await self.redis.xrevrange(stream_key, count=1)

        if not messages:
            return None 

        message_id, fields = messages[0]
        try:
            data = json.loads(fields["data"])
            last_event = ContextProgressEvent.model_validate(data)
            return last_event
        except Exception as e:
            print(f"Failed to parse last message {message_id}: {e}")
            return None

    async def get_chat_history(self, context_id: str) -> List[dict]:
        stream_key = f"agent_task:{context_id}"
        messages = await self.redis.xrange(stream_key, "-", "+")
        history = []
        for message_id, fields in messages:
            try:
                data = json.loads(fields["data"])
                history.append({
                    "id": message_id,
                    "timestamp": self.parse_redis_timestamp(message_id),
                    "data": ContextProgressEvent.model_validate(data)
                })
            except Exception as e:
                print(f"Failed to parse message {message_id}: {e}")
        return history

    @staticmethod
    def parse_redis_timestamp(message_id: str) -> int:
        try:
            return int(message_id.split("-")[0])
        except:
            return 0

    async def disconnect(self) -> None:
        await self.redis.close()