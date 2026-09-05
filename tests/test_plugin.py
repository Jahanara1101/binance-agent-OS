import importlib.util
from pathlib import Path


class FakeContext:
    def __init__(self):
        self.commands = []
        self.calls = []

    def register_cli_command(self, name, help_text, setup, handler, description=""):
        self.commands.append((name, help_text, setup, handler, description))

    def call_mcp(self, server, tool, arguments, timeout=30):
        self.calls.append((server, tool, arguments, timeout))
        return {"result": {}}


def load_plugin():
    path = Path(__file__).parents[1] / "hermes-plugin" / "__init__.py"
    spec = importlib.util.spec_from_file_location("binance_agent_os_plugin", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_plugin_registers_binance_agent_os_cli_command():
    plugin = load_plugin()
    ctx = FakeContext()
    plugin.register(ctx)
    assert [command[0] for command in ctx.commands] == ["binance-agent-os"]


def test_plugin_status_identifies_oauth_mcp_execution(capsys):
    plugin = load_plugin()
    ctx = FakeContext()
    plugin.register(ctx)
    handler = ctx.commands[0][3]
    args = type("Args", (), {"action": "status", "symbol": None})()
    assert handler(args) == 0
    output = capsys.readouterr().out
    assert "Binance Agent OS OAuth MCP" in output
    assert "no API key/secret" in output
