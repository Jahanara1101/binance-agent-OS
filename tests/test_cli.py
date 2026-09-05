from pathlib import Path

from binance_mm.cli import parser


def test_default_environment_is_agent_os():
    args = parser().parse_args([])
    assert args.environment == "agent-os"


def test_repository_has_no_direct_authenticated_execution_credentials():
    root = Path(__file__).parents[1] / "src" / "binance_mm"
    production = "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))
    assert "BINANCE_API_SECRET" not in production
    assert "hmac.new" not in production
    assert '"/fapi/v1/order"' not in production
