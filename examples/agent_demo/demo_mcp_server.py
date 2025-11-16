
from fastmcp import FastMCP
import click
from mcp.types import ToolAnnotations
import builtins
import contextlib
import io

# Create MCP instance
mcp = FastMCP(name="Python Code Execution")

@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
def run_python_code_and_gather_stdout(code: str) -> str:
    """
    Execute a Python code snippet and return standard output.

    ## Example 1
    a = "hello world"
    print(a)

    Output:
    hello world

    ## Example 2
    You can execute Python code to get the current time whenever needed:

    import time
    current_timestamp = int(time.time())
    one_hour_ago_timestamp = int(time.time() - 3600)
    print(f"Current timestamp: {current_timestamp}")
    print(f"One hour ago timestamp: {one_hour_ago_timestamp}")
    """
    try:
        with contextlib.redirect_stdout(io.StringIO()) as f:
            namespace = dict()  # Create isolated namespace
            namespace['__builtins__'] = builtins  # Retain Python built-ins
            exec(code, namespace, namespace)     # Execute with globals=locals=namespace
            
        result = f.getvalue()
        if not result:
            result = "<Code executed successfully, but no output printed to stdout>"
    except Exception as e:
        result = f"Error during execution: {repr(e)}"

    return result


@click.command()
@click.option('--port', default=8000, help='Port number')
def run_server(port):
    """Run MCP server"""
    mcp.run(transport="http", host='0.0.0.0', port=port, path="/demo/mcp")

if __name__ == "__main__":
    run_server()