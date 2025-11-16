from typing import Annotated, Callable
import asyncio
import redis.asyncio as redis
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolCallId
from langchain_core.tools import BaseTool, tool as create_tool
import inspect
from langgraph.types import interrupt
from .distributed_agent_worker import TOOL_REJECT_MESSAGE, WAITING_RESPONSE, AgentInvocationData, AgentInvocationEvent
from functools import wraps
from langgraph.runtime import get_runtime
from fastmcp import Client
from langchain_mcp_adapters.client import MultiServerMCPClient # type: ignore
from pydantic import BaseModel, Field, create_model


def call_subagent(
    redis_url: str,
    caller_agent: str,
    callee_agent: str,
    description: str
) -> Callable:
    """
    Factory function that produces a LangChain @tool for sending a task to the specified agent
    via Redis streams.

    Args:
        redis_url (str): Redis connection URL.
        caller_agent (str): The agent initiating the call.
        callee_agent (str): The target agent's name (used to form the Redis channel).
        description (str): Tool's description, used in LLM prompts.

    Returns:
        Callable: A LangChain tool function that sends tasks to the specified agent.
    """
    @create_tool(f"call_{callee_agent}",description=description)
    def _call_agent(
        task: str,
        config: RunnableConfig,
        injected_tool_call_id: Annotated[str, InjectedToolCallId]
    ) -> str:
        """Send a task to the target agent via Redis stream."""
        context_id = config['metadata']['thread_id'].split('#')[-1]  # type: ignore
        r = redis.from_url(redis_url, decode_responses=True)

        context = get_runtime().context or dict()

        event = AgentInvocationEvent(
            context_id=context_id,
            data=AgentInvocationData(
                task=task,
                caller_agent=caller_agent,
                invocation_id=injected_tool_call_id,
                context=context   
            )
        )
        async def pub():
            await r.xadd(
                f"agent_event:{callee_agent}",
                fields={"data": event.model_dump_json()}
            )

        asyncio.run(pub())

        return WAITING_RESPONSE

    return _call_agent

def human_approval_required(func):
    """
    Decorator that prompts for human approval before executing the wrapped tool function.

    Args:
        func (Callable): The original tool function.

    Returns:
        Callable: Wrapped tool function requiring human approval unless explicitly bypassed.
    """
    @wraps(func)  
    def wrapper(*args, **kwargs):
        sig = inspect.signature(func)
        bound_args = sig.bind(*args, **kwargs)
        bound_args.apply_defaults()
        
        # Extract tool arguments ignoring LangChain-injected params
        tool_args = {
            k: v for k, v in bound_args.arguments.items()
            if k not in ['config', 'injected_tool_call_id']
        }
        
        config = kwargs.get('config')
        injected_tool_call_id = kwargs.get('injected_tool_call_id')
                
        if config and injected_tool_call_id:
            context_id = config['metadata']['thread_id'].split('#')[-1]
            human_resp = interrupt({
                "action_request": {
                    "action": func.__name__,
                    "args": tool_args
                },
                "tool_call_id": injected_tool_call_id,
                "context_id": context_id
            })
            
            if human_resp['type'] == 'accept':
                return func(*args, **kwargs)
            else:
                return TOOL_REJECT_MESSAGE
        return func(*args, **kwargs)
    
    return wrapper




def pydantic_model_from_schema(schema: dict) -> type[BaseModel]:
    required = set(schema.get('required', []))
    fields = {}
    type_mapping = {
        'string': str,
        'integer': int,
        'number': float,
        'boolean': bool,
        'array': list,
        'object': dict
    }
    for name, prop in schema.get('properties', {}).items():
        py_type = type_mapping.get(prop.get('type'), str)
        field_info = Field(
            default=... if name in required else None,
            title=prop.get('title'),
            description=prop.get('description')
        )
        fields[name] = (py_type, field_info)
    fields['injected_tool_call_id'] = (Annotated[str, InjectedToolCallId], Field(
            default=...,
        ))
    return create_model(schema.get('title') or 'DynamicModel', **fields)


async def mcp_tools_to_langchain_tool_with_hitl(mcp_url: str) -> list[BaseTool]:
    """
    Convert MCP tools to LangChain tools, optionally wrapping them with human approval logic.

    Args:
        mcp_url (str): MCP server URL.

    Returns:
        list[BaseTool]: List of LangChain tools with HITL enforced where necessary.
    """
    client = Client(mcp_url)
    async with client:
        # Basic server interaction
        await client.ping()
        # List available operations
        mcp_tools = await client.list_tools()
    
    need_approvals = dict()
    for mcp_tool in mcp_tools:
        need_approval = True
        if mcp_tool.annotations and mcp_tool.annotations.readOnlyHint and not mcp_tool.annotations.destructiveHint:
            need_approval = False
        need_approvals[mcp_tool.name] = need_approval
        
    client = MultiServerMCPClient(
        {
            "foo": {
                "url": mcp_url,
                "transport": "streamable_http",
            }
        }
    )

    tools = await client.get_tools()
    
    tools_with_hitl = []
    for tool in tools:
        need_approval = need_approvals.get(tool.name,True)
        if not need_approval:
            tools_with_hitl.append(tool)
        else:
            # closure
            def make_tool_func(tool):
                args_schema = pydantic_model_from_schema(tool.args_schema)
                @create_tool(tool.name, description=tool.description,args_schema=args_schema)
                async def func(config: RunnableConfig, injected_tool_call_id: Annotated[str, InjectedToolCallId], *args, **kwargs):
                    context_id = config['metadata']['thread_id'].split('#')[-1] # type: ignore
                    human_resp = interrupt({
                        "action_request": {
                            "action": str(tool.name),
                            "args": kwargs
                        },
                        "tool_call_id": injected_tool_call_id,
                        "context_id": context_id
                    })
                    if human_resp['type'] == 'accept':
                        result =  await tool.coroutine(*args, **kwargs)
                        # print(result)
                        return result[0]
                    else:
                        return TOOL_REJECT_MESSAGE
                return func
            func = make_tool_func(tool)
            # print(func.args_schema.model_json_schema())
            tools_with_hitl.append(func)
                                    
    return tools_with_hitl
        