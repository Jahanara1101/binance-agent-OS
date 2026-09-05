from binance_mm.cli import parser


def test_default_environment_is_live():
    args = parser().parse_args([])
    assert args.environment == "live"
