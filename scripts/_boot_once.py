import sys

sys.argv = ["astrbot", "run", "-p", sys.argv[1] if len(sys.argv) > 1 else "6185"]

from astrbot.cli.__main__ import cli  # noqa: E402

cli()
