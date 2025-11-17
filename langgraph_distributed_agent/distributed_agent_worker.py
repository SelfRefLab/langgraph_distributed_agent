from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
import uuid
from langgraph.prebuilt.chat_agent_executor import AgentState
import json
import asyncio
import redis.asyncio as redis
from redis.exceptions import ResponseError
from langgraph.graph.state import CompiledStateGraph
from typing import Dict, Any, Optional
from pydantic import BaseModel
from collections import defaultdict
from pydantic import Field
from enum import Enum
from typing import Literal, AsyncIterator
from langgraph_distributed_agent.redis_lock import redis_lock

WAITING_RESPONSE = "waiting response..."
TOOL_REJECT_MESSAGE = "User declined to execute this action"


class ExtendedAgentState(AgentState):
    """Extended state for an Agent including caller, invocation ID, and context."""
    caller_agent: str
    invocation_id: str
    context: dict[str, str]


class EventType(str, Enum):
    """Event types for distributed agent communication."""
    AGENT_INVOCATION = "agent_invocation"
    AGENT_COMMAND = "agent_command"
    AGENT_RESPONSE = "agent_response"
    PROGRESS_UPDATE = "agent_progress"
    TASK_FINISH = "agent_task_finish"


class BaseEvent(BaseModel):
    """Base event class carrying metadata (context_id, event_type) and event-specific data."""
    context_id: str = Field(...,
                            description="Global context ID (shared across agents)")
    event_type: EventType = Field(...,
                                  description="Type of the event (used for deserialization)")
    data: Any = Field(...,
                      description="Event-specific payload set by subclasses")


class AgentInvocationData(BaseModel):
    """Data sent when triggering agent execution (caller → callee)."""
    task: str = Field(...,
                      description="Prompt text for triggering agent execution")
    caller_agent: str = Field(...,
                              description="Name of the agent initiating the call")
    invocation_id: str = Field(...,
                               description="Unique ID for this invocation (e.g., UUID)")
    context: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="Optional context information"
    )


class AgentInvocationEvent(BaseEvent):
    """Event for triggering agent execution (caller to callee)."""
    event_type: EventType = EventType.AGENT_INVOCATION
    data: AgentInvocationData


class AgentCommandData(BaseModel):
    """Command data sent to the agent (resume execution, tool results, etc.)."""
    type: Literal["resume"] = Field(..., description="Command type")
    tool_call_id: str = Field(...,
                              description="Tool call ID for resuming execution")
    payload: Any = Field(...,
                         description="Command payload (e.g., tool result)")


class AgentCommandEvent(BaseEvent):
    """Command event sent to the agent."""
    event_type: EventType = EventType.AGENT_COMMAND
    data: AgentCommandData


class AgentResponseData(BaseModel):
    """Response data after agent execution (callee → caller)."""
    invocation_id: str = Field(..., description="Associated invocation ID")
    content: str = Field(...,
                         description="Final textual result from the agent")


class AgentResponseEvent(BaseEvent):
    """Response event after agent execution."""
    event_type: EventType = EventType.AGENT_RESPONSE
    data: AgentResponseData


class ContextProgressData(BaseModel):
    """Progress update data for a given context."""
    type: Literal["message", "interrupt"] = Field(
        ..., description="Progress type: message or interrupt")
    caller_agent: str = Field(...,
                              description="Agent receiving progress updates")
    callee_agent: str = Field(...,
                              description="Agent sending progress updates")
    invocation_id: str = Field(..., description="Related invocation ID")
    message: Any = Field(...,
                         description="Progress message content or interrupt reason")
    is_finish: bool = Field(...,
                            description="Flag indicating whether this is the final update")


class ContextProgressEvent(BaseEvent):
    """Progress update event containing ContextProgressData."""
    event_type: EventType = EventType.PROGRESS_UPDATE
    data: ContextProgressData


class DistributedAgentWorker:
    """
    A worker for distributed agents that processes events from a Redis stream.

    This class manages:
      - Listening for agent invocation, command, and response events.
      - Locking per context to ensure sequential processing.
      - Publishing progress updates back to Redis streams for UI/frontend consumption.
    """

    def __init__(self, agent: CompiledStateGraph, redis_url: str):
        if not hasattr(agent, 'name') or not agent.name:
            raise ValueError(
                "The provided agent must have a 'name' attribute.")

        self.agent = agent
        self.redis_url = redis_url
        self.redis_client: redis.Redis = None  # type: ignore
        self.agent_name = agent.name
        self.stream_key = f"agent_event:{self.agent_name}"
        self.consumer_group = f"consumer_group_{self.agent_name}"

        self.context_queues: dict[str,
                                  asyncio.Queue] = defaultdict(asyncio.Queue)
        self.context_workers: dict[str, asyncio.Task] = {}

    def agent_context_id(self, context_id: str):
        """Format a thread ID for this agent."""
        return f"{self.agent_name}#{context_id}"

    def context_key(self, context_id: str):
        """Format the Redis key for storing context-specific messages."""
        return f"agent_task:{context_id}"

    async def _connect(self):
        """Connect to Redis and create the consumer group."""
        print(f"Connecting to Redis at {self.redis_url}...")
        self.redis_client = redis.from_url(
            self.redis_url, decode_responses=True)
        try:
            await self.redis_client.xgroup_create(self.stream_key, self.consumer_group, id="0", mkstream=True)
            print(
                f"Consumer group '{self.consumer_group}' created for stream '{self.stream_key}'.")
        except ResponseError as e:
            if "Consumer Group name already exists" in str(e):
                print(
                    f"Consumer group '{self.consumer_group}' already exists.")
            else:
                raise e

    async def handle_agent_invocation(self, event: AgentInvocationEvent):
        """
        Handle an AGENT_INVOCATION event for this agent.
        If the agent is currently interrupted, returns a "busy" response to the caller.
        Otherwise starts streaming agent execution.
        """
        print(f"Handling agent_call for context_id: {event.context_id}")
        config = RunnableConfig(
            configurable={"thread_id": self.agent_context_id(event.context_id)})
        snapshot = await self.agent.aget_state(config)
        if snapshot.interrupts:
            print("Agent currently in interrupt state, rejecting new invocation.")
            agent_response_event = AgentResponseEvent(context_id=event.context_id,
                                                      data=AgentResponseData(
                                                          invocation_id=event.data.invocation_id,
                                                          content="The agent is currently handling another request for this context. Please retry later."
                                                      ))
            await self.redis_client.xadd(f"agent_event:{event.data.caller_agent}", fields={'data': agent_response_event.model_dump_json()})
            return

        task = event.data.task
        events = self.agent.astream(
            {
                "messages": [
                    {
                        "role": "user",
                        "content": task
                    }
                ],
                "context": event.data.context,
                "caller_agent": event.data.caller_agent,
                "invocation_id": event.data.invocation_id,
            },
            config,
            stream_mode="updates",
            context=event.data.context  # type: ignore
        )
        # Publish human message to progress stream so UI can display it
        if event.data.caller_agent == 'human':
            human_message = HumanMessage(content=task)
            context_progess_data = ContextProgressData(type="message",
                                                       caller_agent=event.data.caller_agent,
                                                       callee_agent=self.agent_name,
                                                       invocation_id=event.data.invocation_id,
                                                       message=human_message.model_dump(),
                                                       is_finish=False)
            context_progress_event = ContextProgressEvent(context_id=event.context_id,
                                                          data=context_progess_data)
            await self.redis_client.xadd(self.context_key(event.context_id),
                                         fields={'data': context_progress_event.model_dump_json()})

        await self._process_agent_stream(events, config,
                                         event.context_id,
                                         event.data.invocation_id,
                                         event.data.caller_agent,
                                         context=event.data.context)

    async def handle_agent_command(self, event: AgentCommandEvent):
        config = RunnableConfig(
            configurable={"thread_id": self.agent_context_id(event.context_id)})
        snapshot = await self.agent.aget_state(config)
        context = snapshot.values.get('context', '') or dict()
        invocation_id = snapshot.values.get('invocation_id', '')
        caller_agent = snapshot.values.get('caller_agent', '')
        events = self.agent.astream(
            Command(**{event.data.type: event.data.payload}),
            config,
            stream_mode="updates",
            context=context,  # type: ignore
        )
        await self._process_agent_stream(events, config, event.context_id, invocation_id, caller_agent,
                                         context=context)

    def _is_waiting_response(self, snapshot) -> bool:
        return any(
            isinstance(msg, ToolMessage) and msg.content == WAITING_RESPONSE
            for msg in snapshot.values.get('messages', [])
        )

    async def handle_agent_response(self, event: AgentResponseEvent):
        invocation_id = event.data.invocation_id
        config = RunnableConfig(
            configurable={"thread_id": self.agent_context_id(event.context_id)})
        snapshot = await self.agent.aget_state(config)
        caller_agent = snapshot.values.get('caller_agent', '')
        context = snapshot.values.get('context', '') or dict()
        for message in snapshot.values.get('messages', []):
            if isinstance(message, ToolMessage) and message.tool_call_id == invocation_id and message.content == WAITING_RESPONSE:
                new_tool_message = message.model_copy()
                new_tool_message.content = event.data.content
                await self.agent.aupdate_state(config, values={"messages": [new_tool_message]})
                snapshot = await self.agent.aget_state(config)
                is_waiting_response = self._is_waiting_response(snapshot)
                if not snapshot.next and not is_waiting_response:
                    events = self.agent.astream(Command(goto="agent"), config,
                                                stream_mode="updates", context=context)  # type: ignore
                    await self._process_agent_stream(events, config, event.context_id,
                                                     invocation_id, caller_agent, context=context)

    async def _process_agent_stream(self,
                                    events: AsyncIterator,
                                    config: RunnableConfig,
                                    context_id: str,
                                    invocation_id: str,
                                    caller_agent: str,
                                    context: Optional[Dict[str, Any]] = None):
        if context is None:
            context = dict()

        async def emit_events(events):
            async for event in events:
                for k, v in event.items():
                    print(k)
                    if isinstance(v, dict):
                        messages = v.get('messages', [])
                        for i, message in enumerate(messages):
                            message.pretty_print()
                            is_finish = False
                            if i == len(messages) - 1 and isinstance(message, AIMessage):
                                snapshot = await self.agent.aget_state(config)
                                if not snapshot.next and not snapshot.interrupts and not self._is_waiting_response(snapshot) and not message.tool_calls:
                                    is_finish = True

                            context_progess_data = ContextProgressData(type="message",
                                                                       caller_agent=caller_agent,
                                                                       callee_agent=self.agent_name,
                                                                       invocation_id=invocation_id,
                                                                       message=message.model_dump(),
                                                                       is_finish=is_finish)
                            context_progress_event = ContextProgressEvent(context_id=context_id,
                                                                          data=context_progess_data)
                            await self.redis_client.xadd(self.context_key(context_id),
                                                         fields={'data': context_progress_event.model_dump_json()})
                            await self.redis_client.publish(self.context_key(context_id),
                                                            context_progress_event.model_dump_json())
                    else:
                        print(event)
                        if k == '__interrupt__':
                            if v:
                                for interruption in v:
                                    context_progess_data = ContextProgressData(type="interrupt",
                                                                               caller_agent=caller_agent,
                                                                               callee_agent=self.agent_name,
                                                                               invocation_id=invocation_id,
                                                                               message=interruption.value,
                                                                               is_finish=False)

                                    context_progress_event = ContextProgressEvent(context_id=context_id,
                                                                                  data=context_progess_data)
                                    await self.redis_client.xadd(self.context_key(context_id),
                                                                 fields={'data': context_progress_event.model_dump_json()})
                                    await self.redis_client.publish(self.context_key(context_id),
                                                                    context_progress_event.model_dump_json())

        await emit_events(events)

        snapshot = await self.agent.aget_state(config)

        while True:

            if snapshot.interrupts:
                break
            else:
                if self._is_waiting_response(snapshot):
                    print("waiting response from other agent...")
                    break
                else:
                    # stop exec when tool rejected.
                    messages = snapshot.values.get('messages', [])
                    if len(messages) > 0 and isinstance(messages[-1], ToolMessage):
                        if messages[-1].content == TOOL_REJECT_MESSAGE:
                            print("tool rejected.")
                            agent_response_event = AgentResponseEvent(context_id=context_id, 
                                                                    data=AgentResponseData(
                                                                    invocation_id=invocation_id,
                                                                    content=snapshot.values.get("messages")[-1].content # type: ignore
                                                                    ))
                            
                            context_progess_data = ContextProgressData(type="message",
                                                                caller_agent=caller_agent,
                                                                callee_agent=self.agent_name,
                                                                invocation_id=invocation_id,
                                                                message=AIMessage(content=f"Tool Rejected").model_dump(),
                                                                is_finish=True)
                            context_progress_event = ContextProgressEvent(context_id=context_id,
                                                                            data=context_progess_data)

                            await self.redis_client.xadd(self.context_key(context_id), 
                                                            fields={'data': context_progress_event.model_dump_json()})
                            await self.redis_client.publish(self.context_key(context_id), 
                                                            context_progress_event.model_dump_json())
                            
                            await self.redis_client.xadd(f"agent_event:{caller_agent}", fields={'data': agent_response_event.model_dump_json()})
                            break

                    if snapshot.next:
                        events = self.agent.astream(
                            None, config, stream_mode="updates", context=context)  # type: ignore
                        await emit_events(events)
                        snapshot = await self.agent.aget_state(config)

            if not snapshot.next:
                is_waiting_response = self._is_waiting_response(snapshot)
                if not is_waiting_response:
                    print(
                        f"Emit AgentResponseEvent caller_agent={caller_agent}")
                    agent_response_event = AgentResponseEvent(context_id=context_id,
                                                              data=AgentResponseData(
                                                                  invocation_id=invocation_id,
                                                                  content=snapshot.values.get(
                                                                      "messages")[-1].content  # type: ignore
                                                              ))
                    await self.redis_client.xadd(f"agent_event:{caller_agent}", fields={'data': agent_response_event.model_dump_json()})
                break

    async def _dispatch_event(self, data: Dict):
        event_type = data.get("event_type")

        if event_type == EventType.AGENT_INVOCATION:
            event = AgentInvocationEvent.model_validate(data)
            await self.handle_agent_invocation(event)
        elif event_type == EventType.AGENT_COMMAND:
            event = AgentCommandEvent.model_validate(data)
            await self.handle_agent_command(event)
        elif event_type == EventType.AGENT_RESPONSE:
            event = AgentResponseEvent.model_validate(data)
            await self.handle_agent_response(event)
        else:
            print(f"Unknown event type: {event_type}")

    async def _run_context_worker(self, context_id: str):
        queue = self.context_queues[context_id]
        while True:
            message_data = await queue.get()
            lock_key = f"lock:context:{context_id}"
            async with redis_lock(self.redis_client, lock_key):
                try:
                    await self._dispatch_event(message_data)
                except Exception as e:
                    print("failed to handle message:", e)
                    try:
                        event = AgentInvocationEvent.model_validate(
                            message_data)
                        caller_agent = event.data.caller_agent
                        invocation_id = event.data.invocation_id
                    except:
                        snapshot = self.agent.get_state(RunnableConfig(
                            configurable=dict(thread_id=context_id)))
                        invocation_id = snapshot.values.get(
                            'invocation_id', '')
                        caller_agent = snapshot.values.get('caller_agent', '')
                    context_progess_data = ContextProgressData(type="message",
                                                               caller_agent=caller_agent,
                                                               callee_agent=self.agent_name,
                                                               invocation_id=invocation_id,
                                                               message=f"Error occurred. {e}",
                                                               is_finish=False)
                    context_progress_event = ContextProgressEvent(context_id=context_id,
                                                                  data=context_progess_data)
                    await self.redis_client.xadd(self.context_key(context_id),
                                                 fields={'data': context_progress_event.model_dump_json()})
                    await self.redis_client.publish(self.context_key(context_id),
                                                    context_progress_event.model_dump_json())

            queue.task_done()

    async def _enqueue_message(self, message_data: dict):
        context_id = message_data["context_id"]
        queue = self.context_queues[context_id]
        await queue.put(message_data)
        if context_id not in self.context_workers:
            self.context_workers[context_id] = asyncio.create_task(
                self._run_context_worker(context_id)
            )

    async def start(self):
        await self._connect()
        while True:
            messages = await self.redis_client.xreadgroup(
                groupname=self.consumer_group,
                consumername=str(uuid.uuid4()),
                streams={self.stream_key: ">"},
                count=10,
                block=1000
            )

            if len(messages) == 0:
                continue

            for x in messages[0][1:]:
                for message_id, messgge_data in x:
                    message_data = json.loads(messgge_data['data'])
                    print(message_data)
                    await self._enqueue_message(message_data)
