# LangGraph Distributed Agent

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![MIT License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Redis](https://img.shields.io/badge/redis-required-red.svg)](https://redis.io/)

[中文文档](README_CN.md) | English

A distributed agent framework built on top of LangGraph that enables multiple AI agents to work together seamlessly using Redis as a message broker. This SDK provides a robust foundation for building scalable, multi-agent AI systems with real-time communication and state persistence.

## 🌟 Core Capabilities

### 🔒 Human-in-the-Loop Safety Controls
**Sensitive tool execution requires human approval** - Built-in safety mechanisms ensure that critical operations, sensitive data access, and potentially impactful actions are reviewed and approved by humans before execution. Real-time monitoring and intervention capabilities provide complete control over agent behavior.

### 🌐 True Distributed Architecture  
**Horizontally scalable multi-agent systems** - Multiple agents run independently across different processes or machines, communicating through Redis streams. Each agent can be deployed, scaled, and managed separately while maintaining seamless coordination.

### 🏗️ Hierarchical Agent Organization
**Intelligent workflow coordination** - Agents can be organized in hierarchical structures where coordinator agents delegate tasks to specialized sub-agents. This enables complex workflow orchestration with clear responsibility chains and efficient task distribution.

https://github.com/user-attachments/assets/6ef83c79-cb42-4cab-8359-27dfb74cdc65

## 🚀 Additional Features

- **MCP Server Integration**: Support for Model Context Protocol servers to extend agent capabilities
- **Persistent State Management**: MySQL/SQLite checkpoint storage for conversation history
- **Scalable Design**: Horizontal scaling with Redis streams and consumer groups
- **Easy Integration**: Simple client interface for interacting with the agent system

## 🏗️ Architecture

The system consists of several key components:

- **Agent Workers**: Individual agents that process tasks and communicate via Redis streams
- **Agent Client**: Interface for sending messages and receiving responses from agents
- **Agent Runner**: High-level wrapper for creating and managing agents
- **Redis Streams**: Message broker for inter-agent communication
- **Checkpoint Storage**: Persistent state management using MySQL or SQLite


## 📦 Installation

```bash
pip install langgraph_distributed_agent
```

### Dependencies

The package requires Python 3.10+ and the following key dependencies:
- `langgraph` - Core graph-based agent framework
- `redis` - Redis client for message streaming
- `langchain` - LLM integration
- `pydantic` - Data validation and settings management

## 🚀 Quick Start

### 1. Set up Environment

Create a `.env` file with your configuration:

```env
REDIS_URL=redis://:password@localhost:6379/0
CHECKPOINT_DB_URL=agent_checkpoints.db

OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4
OPENAI_API_KEY=sk-your-api-key
```

### 2. Create Your First Agent

```python
from langchain_core.tools import tool
from langgraph.runtime import get_runtime
import asyncio
from langgraph_distributed_agent.agent_runner import AgentRunner
from langgraph_distributed_agent.utils import human_approval_required
import os
from typing import Annotated
from langchain_core.tools import tool, InjectedToolCallId
from langchain_core.runnables import RunnableConfig

import dotenv
dotenv.load_dotenv()

@tool
def get_city_weather(city: str) -> str:
    """
    Get the weather for a specific city.

    Parameters:
        city (str): Name of the city, e.g., "London".

    Returns:
        str: Weather description for the given city.
    """
    print("current context", get_runtime().context)
    return f"It's always sunny in {city}!"

@tool
@human_approval_required
def get_city_gdp(city: str,
                 config: RunnableConfig,
                 injected_tool_call_id: Annotated[str, InjectedToolCallId]) -> str:
    """Get city gdp"""
    print(get_runtime())
    return f"The gdp of {city} is 500 billion yuan!"


async def main():
    runner = AgentRunner(
        agent_name="demo_agent",
        system_prompt="You are a helpful assistant.",
        redis_url=os.environ.get("REDIS_URL", ""),
        mysql_url=os.environ.get("CHECKPOINT_DB_URL", ""),
        openai_base_url=os.environ.get(
            "OPENAI_BASE_URL", ""),
        openai_model=os.environ.get("OPENAI_MODEL", ""),
        openai_api_key=os.environ.get("OPENAI_API_KEY", "")
    )
    runner.add_tool(get_city_weather)
    runner.add_tool(get_city_gdp)
    await runner.start()

if __name__ == '__main__':
    asyncio.run(main())
```

### 3. Create a Client to Interact

**or test with ui** https://github.com/SelfRefLab/agents-ui

```python
import asyncio
from langgraph_distributed_agent.agent_client import AgentClient
import uuid
import os
import dotenv

dotenv.load_dotenv()

async def main():
    client = AgentClient(target_agent="demo_agent",
                         redis_url=os.environ.get("REDIS_URL", ""))
    context_id = str(uuid.uuid4())
    while True:
        question = input("Input your Question:")
        await client.send_message(question, context_id)
        await client.listen_for_responses(context_id)

if __name__ == '__main__':
    asyncio.run(main())
```

## 📖 Examples

The `examples/agent_demo/` directory contains a complete working example with:

- **Main Agent** (`main_agent.py`): Coordinator agent that delegates tasks
- **Weather Agent** (`weather_agent.py`): Specialized weather information agent
- **Economics Agent** (`economics_agent.py`): Specialized economic analysis agent
- **MCP Server** (`demo_mcp_server.py`): Example MCP server integration
- **CLI Client** (`cli.py`): Interactive command-line interface

### Running the Example

1. Start the MCP server:
```bash
python -m examples.agent_demo.demo_mcp_server
```

2. Start the agents:
```bash
python -m examples.agent_demo.main_agent
python -m examples.agent_demo.weather_agent
python -m examples.agent_demo.economics_agent
```

3. Run the CLI client:
```bash
python -m examples.agent_demo.cli
```

## 📚 API Reference

### AgentRunner

Main class for creating and managing agents.

```python
class AgentRunner:
    def __init__(self, agent_name: str, system_prompt: str, ...)
    async def add_mcp_server(self, server_url: str)
    def add_subagent(self, agent_name: str, description: str)
    async def start(self)
```

### AgentClient

Client interface for interacting with agents.

```python
class AgentClient:
    def __init__(self, target_agent: str, redis_url: str)
    async def add_tool(self, tool)
    async def send_message(self, content: str, context_id: str)
    async def listen_for_responses(self, context_id: str)
```

### DistributedAgentWorker

Low-level worker for processing agent events.

```python
class DistributedAgentWorker:
    def __init__(self, agent: CompiledStateGraph, redis_url: str)
    async def start(self)
```

## 🛠️ Development

### Setting up Development Environment

1. Clone the repository:
```bash
git clone https://github.com/SelfRefLab/langgraph_distributed_agent.git
cd langgraph_distributed_agent
```

2. Install dependencies:
```bash
pip install -e .
```

3. Set up Redis:
```bash
# Using Docker
docker run -d -p 6379:6379 redis:latest

# Or install locally
# Follow Redis installation guide for your OS
```

4. Copy and configure environment:
```bash
cp .env.example .env
# Edit .env with your configuration
```

### Project Structure

```
langgraph_distributed_agent/
├── langgraph_distributed_agent/    # Main package
│   ├── agent_client.py            # Client interface
│   ├── agent_runner.py            # High-level agent runner
│   ├── distributed_agent_worker.py # Core worker implementation
│   ├── redis_lock.py              # Redis-based locking
│   └── utils.py                   # Utility functions
├── examples/                      # Example implementations
│   └── agent_demo/               # Complete demo system
```

## 🤝 Contributing

We welcome contributions! Please feel free to submit a Pull Request. For major changes, please open an issue first to discuss what you would like to change.

### Guidelines

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Built on top of [LangGraph](https://github.com/langchain-ai/langgraph)
- Inspired by distributed systems patterns
- Developed by the Huya AIOps team

## 📞 Support

If you have any questions or need help, please:

1. Check the [examples](examples/) directory
2. Open an issue on GitHub
3. Contact the maintainers

---

**Authors**: panjianning, lanxuanli  
**Organization**: Huya AIOps Team  
