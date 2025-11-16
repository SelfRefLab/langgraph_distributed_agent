# LangGraph 分布式智能体

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![MIT License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Redis](https://img.shields.io/badge/redis-required-red.svg)](https://redis.io/)

中文文档 | [English](README.md)

基于 LangGraph 构建的分布式智能体框架，使用 Redis 作为消息代理，让多个 AI 智能体能够无缝协作。该 SDK 为构建可扩展的多智能体 AI 系统提供了强大的基础，支持实时通信和状态持久化。

## 🌟 核心能力

### 🔒 人机协作安全控制
**敏感工具执行需要人工审核** - 内置安全机制确保关键操作、敏感数据访问和潜在影响性操作在执行前经过人工审核和批准。实时监控和干预能力提供对智能体行为的完全控制。

### 🌐 真正的分布式架构
**水平可扩展的多智能体系统** - 多个智能体在不同进程或机器上独立运行，通过 Redis 流进行通信。每个智能体可以独立部署、扩展和管理，同时保持无缝协调。

### 🏗️ 层次化智能体组织
**智能工作流协调** - 智能体可以组织成层次结构，协调智能体将任务委派给专门的子智能体。这实现了复杂工作流编排，具有清晰的责任链和高效的任务分配。

https://github.com/user-attachments/assets/6ef83c79-cb42-4cab-8359-27dfb74cdc65

## 🚀 其他特性

- **MCP 服务器集成**：支持模型上下文协议服务器以扩展智能体功能
- **持久化状态管理**：使用 MySQL/SQLite 检查点存储对话历史
- **可扩展设计**：通过 Redis 流和消费者组实现水平扩展
- **易于集成**：简单的客户端接口与智能体系统交互

## 🏗️ 架构

系统由几个关键组件组成：

- **智能体工作器**：处理任务并通过 Redis 流通信的独立智能体
- **智能体客户端**：用于向智能体发送消息和接收响应的接口
- **智能体运行器**：用于创建和管理智能体的高级包装器
- **Redis 流**：智能体间通信的消息代理
- **检查点存储**：使用 MySQL 或 SQLite 的持久化状态管理


## 📦 安装

```bash
pip install langgraph_distributed_agent
```

### 依赖项

该包需要 Python 3.10+ 和以下关键依赖项：
- `langgraph` - 核心基于图的智能体框架
- `redis` - Redis 客户端用于消息流
- `langchain` - LLM 集成
- `pydantic` - 数据验证和设置管理

## 🚀 快速开始

### 1. 设置环境

创建一个 `.env` 文件并配置：

```env
REDIS_URL=redis://:password@localhost:6379/0
CHECKPOINT_DB_URL=agent_checkpoints.db

OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4
OPENAI_API_KEY=sk-your-api-key
```

### 2. 创建你的第一个智能体

```python
from langchain_core.tools import tool
from langgraph.runtime import get_runtime
import asyncio
from langgraph_distributed_agent.agent_runner import AgentRunner
import os
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

async def main():
    runner = AgentRunner(
        agent_name="weather_agent",
        system_prompt="You are a economist.",
        redis_url=os.environ.get("REDIS_URL", ""),
        mysql_url=os.environ.get("CHECKPOINT_DB_URL", ""),
        openai_base_url=os.environ.get(
            "OPENAI_BASE_URL", ""),
        openai_model=os.environ.get("OPENAI_MODEL", ""),
        openai_api_key=os.environ.get("OPENAI_API_KEY", "")
    )
    runner.add_tool(get_city_weather)
    await runner.start()

if __name__ == '__main__':
    asyncio.run(main())
```

### 3. 创建客户端进行交互

或者用UI界面进行交互：https://github.com/SelfRefLab/agents-ui

```python
import asyncio
from langgraph_distributed_agent.agent_client import AgentClient
import uuid
import os

async def main():
    client = AgentClient(
        target_agent="weather_agent",
        redis_url=os.environ.get("REDIS_URL")
    )
    
    context_id = str(uuid.uuid4())
    
    # 发送消息
    await client.send_message("今天天气怎么样？", context_id)
    
    # 监听响应
    await client.listen_for_responses(context_id)

if __name__ == '__main__':
    asyncio.run(main())
```

## 📖 示例

`examples/agent_demo/` 目录包含一个完整的工作示例：

- **主智能体** (`main_agent.py`)：协调智能体，负责任务分发
- **天气智能体** (`weather_agent.py`)：专门处理天气信息的智能体
- **经济智能体** (`economics_agent.py`)：专门进行经济分析的智能体
- **MCP 服务器** (`demo_mcp_server.py`)：MCP 服务器集成示例
- **CLI 客户端** (`cli.py`)：交互式命令行界面

### 运行示例

1. 启动 MCP 服务器：
```bash
python -m examples.agent_demo.demo_mcp_server
```

2. 启动智能体：
```bash
python -m examples.agent_demo.main_agent
python -m examples.agent_demo.weather_agent
python -m examples.agent_demo.economics_agent
```

3. 运行 CLI 客户端：
```bash
python -m examples.agent_demo.cli
```

## 📚 API 参考

### AgentRunner

用于创建和管理智能体的主要类。

```python
class AgentRunner:
    def __init__(self, agent_name: str, system_prompt: str, ...)
    async def add_tool(self, tool)
    async def add_mcp_server(self, server_url: str)
    def add_subagent(self, agent_name: str, description: str)
    async def start(self)
```

### AgentClient

与智能体交互的客户端接口。

```python
class AgentClient:
    def __init__(self, target_agent: str, redis_url: str)
    async def send_message(self, content: str, context_id: str)
    async def listen_for_responses(self, context_id: str)
```

### DistributedAgentWorker

处理智能体事件的底层工作器。

```python
class DistributedAgentWorker:
    def __init__(self, agent: CompiledStateGraph, redis_url: str)
    async def start(self)
```

## 🛠️ 开发

### 设置开发环境

1. 克隆仓库：
```bash
git clone https://github.com/SelfRefLab/langgraph_distributed_agent.git
cd langgraph_distributed_agent
```

2. 安装依赖：
```bash
pip install -e .
```

3. 设置 Redis：
```bash
# 使用 Docker
docker run -d -p 6379:6379 redis:latest

# 或本地安装
# 按照你的操作系统的 Redis 安装指南
```

4. 复制并配置环境：
```bash
cp .env.example .env
# 编辑 .env 文件进行配置
```

### 项目结构

```
langgraph_distributed_agent/
├── langgraph_distributed_agent/    # 主包
│   ├── agent_client.py            # 客户端接口
│   ├── agent_runner.py            # 高级智能体运行器
│   ├── distributed_agent_worker.py # 核心工作器实现
│   ├── redis_lock.py              # 基于 Redis 的锁
│   └── utils.py                   # 工具函数
├── examples/                      # 示例实现
│   └── agent_demo/               # 完整演示系统
```

## 🤝 贡献

我们欢迎贡献！请随时提交 Pull Request。对于重大更改，请先开启一个 issue 来讨论你想要更改的内容。

### 指南

1. Fork 仓库
2. 创建功能分支 (`git checkout -b feature/amazing-feature`)
3. 提交你的更改 (`git commit -m 'Add some amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 开启一个 Pull Request

## 📄 许可证

该项目采用 MIT 许可证 - 详情请参阅 [LICENSE](LICENSE) 文件。

## 🙏 致谢

- 基于 [LangGraph](https://github.com/langchain-ai/langgraph) 构建
- 受分布式系统模式启发
- 由虎牙AIOps团队开发

## 📞 支持

如果你有任何问题或需要帮助，请：

1. 查看 [examples](examples/) 目录
2. 在 GitHub 上开启一个 issue
3. 联系维护者

---

**作者**：panjianning, lanxuanli  
**组织**：虎牙 AIOps 团队  
