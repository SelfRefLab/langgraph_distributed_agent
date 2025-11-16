import redis.asyncio as redis
import uuid
import json
from langgraph_distributed_agent.distributed_agent_worker import AgentInvocationEvent, \
    AgentCommandEvent, AgentInvocationData, AgentCommandData,ContextProgressEvent
from colorama import Fore, Style, init

init(autoreset=True)  


class AgentClient:
    def __init__(self, target_agent: str, redis_url: str):
        self.target_agent = target_agent
        self.redis_url = redis_url
        self.r = redis.from_url(self.redis_url, decode_responses=True)

    async def send_message(self, content: str, context_id: str):
        invocation_id = "invocation_" + str(uuid.uuid4())
        event = AgentInvocationEvent(context_id=context_id, data=AgentInvocationData(
            task=content,
            caller_agent="human",
            invocation_id=invocation_id,
            context=dict(user_name="zhangsan")))
        await self.r.xadd(f"agent_event:{self.target_agent}", {"data": event.model_dump_json()})

    async def listen_for_responses(self, context_id: str):
        channel_name = f"agent_task:{context_id}"
        consumer_group = f"consumer_group_{context_id}"

        try:
            await self.r.xgroup_create(channel_name, consumer_group, id="0", mkstream=True)
        except Exception:
            pass

        while True:
            messages = await self.r.xreadgroup(
                groupname=consumer_group,
                consumername=str(uuid.uuid4()),
                streams={channel_name: ">"},
                count=10,  #
                block=1000  # ms
            )

            if not messages:
                continue
            
            is_finish = False
            for message_records in messages[0][1:]:
                for message_id, message_record in message_records:
                    message_detail = json.loads(message_record['data'])
                    # print(f"[Message Received] {message_detail}")
                    event_type = message_detail.get('event_type')
                    if event_type == 'agent_progress':
                        event = ContextProgressEvent.model_validate(message_detail)
                        if event.data.type == "message":
                            message = event.data.message
                            if message['type'] != 'human':
                                print(Fore.CYAN + f"{event.data.callee_agent}:")
                                if message.get('content'):
                                    print(Fore.GREEN + message['content'])
                                if message.get('tool_calls'):
                                    print(Fore.BLUE + "调用工具" + json.dumps(
                                        message['tool_calls'],ensure_ascii=False,indent=2))
                                
                                if event.data.callee_agent == self.target_agent and event.data.is_finish:
                                    is_finish = True
                                    break
                                    
                        elif event.data.type == "interrupt":
                            message = event.data.message
                            await self.handle_interrupt(event.data.callee_agent,
                                                        message['context_id'], 
                                                        message['tool_call_id'])
            if is_finish:
                break
                            
    async def handle_interrupt(self, agent_name: str, context_id: str, tool_call_id: str):
        inp = input(Fore.RED + "Do you agree with the tool call? (y/n): ").strip().lower()
        if inp == 'y':
            payload = {"type": "accept"}
        else:
            payload = {"type": "reject"}

        command = AgentCommandEvent(context_id=context_id,
                                    data=AgentCommandData(
                                        type="resume", 
                                        tool_call_id=tool_call_id, 
                                        payload=payload))
        await self.r.xadd(f"agent_event:{agent_name}", {"data": command.model_dump_json()})

