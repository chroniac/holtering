import sys

import uvicorn

from . import config
from .analysis import build
from .api import create_app


def main(argv: list[str] | None = None) -> int:
    cfg = config.load(argv)
    print(f"holtering: {cfg.scp} (start {cfg.start})", flush=True)
    st = build(cfg)
    print(f"holtering: analysis ready ({st.analysis['computed_s']} s compute, "
          f"{len(st.analysis['episodes'])} episodes) -> http://{cfg.host}:{cfg.port}", flush=True)
    uvicorn.run(create_app(st), host=cfg.host, port=cfg.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
