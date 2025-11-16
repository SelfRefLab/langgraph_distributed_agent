from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from langgraph_distributed_agent.distributed_agent_worker import DistributedAgentWorker, ExtendedAgentState
from langgraph_distributed_agent.robust_aiomysql_saver import RobustAIOMySQLSaver as AIOMySQLSaver
import typing
from langgraph_distributed_agent.utils import mcp_tools_to_langchain_tool_with_hitl
from langchain_core.messages import SystemMessage
from langgraph_distributed_agent.utils import call_subagent
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
import aiosqlite

class AgentRunner:
    """
    AgentRunner is a helper class to initialize, configure, and run a distributed LangGraph agent with 
    MySQL-based state persistence and Redis-based message passing.
    """

    def __init__(
        self,
        agent_name: str,
        openai_api_key: str,
        openai_model: str,
        openai_base_url: str,
        redis_url: str,
        mysql_url: str,
        temperature: float = 0.6,
        system_prompt: str = "You are a helpful assistant."
    ):
        """
        Initialize the AgentRunner instance.

        Parameters:
            agent_name (str)       - The unique name of the agent.
            openai_api_key (str)   - API key for OpenAI.
            openai_model (str)     - LLM model name (e.g., gpt-4).
            openai_base_url (str)  - Optional base URL for the OpenAI API (for proxy/self-host).
            redis_url (str)        - Connection URL for Redis (used for inter-agent communication).
            mysql_url (str)        - Connection string for MySQL (used for state persistence).
            temperature (float)    - Model's randomness factor (default: 0.6).
            system_prompt (str)    - Base system instruction for the agent.
        """
        self.agent_name = agent_name
        self.openai_model = openai_model
        self.openai_base_url = openai_base_url
        self.openai_api_key = openai_api_key
        self.redis_url = redis_url
        self.mysql_url = mysql_url
        self.temperature = temperature
        self.prompt = system_prompt

        # List of tools the agent can use
        self.tools: typing.List[typing.Any] = []

        # Async context manager for memory persistence
        self._memory_cm = None
        self._memory = None

        # LangGraph agent instance
        self._agent = None

        # Worker for distributed execution
        self._worker = None

    async def create(self):
        """
        Create and configure the agent, connect persistence layer, and set up the worker.
        """
        # Connect to MySQL persistence layer
        if self.mysql_url.endswith('.sqlite') or self.mysql_url.endswith('.db'):
            conn = aiosqlite.connect(self.mysql_url, check_same_thread=False)
            self._memory = AsyncSqliteSaver(conn)
        else:
            self._memory_cm = AIOMySQLSaver.from_conn_string(self.mysql_url) #type ignore
            self._memory = await self._memory_cm.__aenter__()
            await self._memory.setup()

        # Initialize the ChatOpenAI LLM
        llm = ChatOpenAI(
            model=self.openai_model,
            base_url=self.openai_base_url,
            api_key=self.openai_api_key,  # type: ignore
            temperature=self.temperature
        )

        # Dynamic prompt injection based on runtime state
        def dynamic_prompt(state):
            """
            Generate a dynamic system prompt based on agent state,
            including user information if available.
            """
            user_name = (state.get("context") or dict()).get('user_name')
            messages = state.get('messages', [])
            sys_prompt = self.prompt

            if user_name:
                sys_prompt += f"""
## Current User Information

Current username: `{user_name}`
* If any tool requires a person's name, pass this name.
* You can address the user as `{user_name}`, e.g., “Hello, {user_name}”
"""
            return [SystemMessage(content=sys_prompt)] + messages

        # Create the LangGraph agent with tools and persistence
        self._agent = create_react_agent(
            model=llm,
            tools=self.tools,
            prompt=dynamic_prompt,
            name=self.agent_name,
            checkpointer=self._memory,
            state_schema=ExtendedAgentState,
            interrupt_after=["tools"]  # Allows pausing after tool execution
        )

        # Initialize the distributed worker
        self._worker = DistributedAgentWorker(
            agent=self._agent,
            redis_url=self.redis_url
        )

    def add_tool(self, tool):
        """
        Add a tool to the agent's toolset.

        Note: Tools should ideally be added before calling `create()`.
        """
        self.tools.append(tool)
        if self._worker:
            print("Warning: Tools should be added before the agent starts")

    async def add_mcp_server(self, mcp_url: str):
        """
        Load tools from an MCP (Model Control Protocol) server
        and add them to the agent.
        """
        tools = await mcp_tools_to_langchain_tool_with_hitl(mcp_url)
        for t in tools:
            self.add_tool(t)

    def add_subagent(self, agent_name: str, description: str):
        """
        Add a sub-agent (another agent in the distributed system) 
        as a callable tool for this agent.

        Parameters:
            agent_name (str) - Target sub-agent's name.
            description (str) - Brief description for the tool.
        """
        self.add_tool(call_subagent(
            redis_url=self.redis_url,
            caller_agent=self.agent_name,
            callee_agent=agent_name,
            description=description
        ))

    async def start(self):
        """
        Start the distributed worker for this agent.
        If the agent is not yet created, create it first.
        """
        if not self._worker:
            await self.create()
        await self._worker.start()  # type: ignore

    async def close(self):
        """
        Gracefully close the persistence layer connection.
        """
        if self._memory_cm:
            await self._memory_cm.__aexit__(None, None, None)