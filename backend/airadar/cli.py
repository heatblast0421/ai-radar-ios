"""Command line entry point.

    python -m airadar.cli run                 # run whatever is due, then export the JSON API
    python -m airadar.cli run --force all     # fetch every source now
    python -m airadar.cli export              # rebuild JSON from the database only
    python -m airadar.cli serve               # preview the JSON API locally on http://127.0.0.1:8787
    python -m airadar.cli status              # print source health
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from . import config as cfgmod
from . import db as dbmod
from .export import Exporter


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="airadar")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--force", default="", help="comma-separated job groups to run now, or 'all'")
    r.add_argument("--skip-fetch", action="store_true")
    r.add_argument("--skip-llm", action="store_true")
    sub.add_parser("export")
    sub.add_parser("status")
    sub.add_parser("migrate")
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=8787)
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = cfgmod.load()

    if args.cmd == "run":
        from .pipeline import run
        force = {g.strip() for g in args.force.split(",") if g.strip()} or None
        summary = run(config, force=force, skip_fetch=args.skip_fetch, skip_llm=args.skip_llm)
        print(json.dumps(summary, indent=1))
        failed = [s for s in summary["sources"] if not s.get("ok")]
        print(f"\nDone in {summary['seconds']}s; {len(summary['sources'])} sources run, {len(failed)} failed.", file=sys.stderr)
        return 0  # individual source failures are reported in meta.json, not fatal
    if args.cmd == "export":
        conn = dbmod.connect(config.db_path)
        print(json.dumps(Exporter(conn, config, config.site_dir).build(), indent=1))
        return 0
    if args.cmd == "migrate":
        conn = dbmod.connect(config.db_path)
        print("schema up to date:", [r[0] for r in conn.execute("SELECT name FROM schema_migrations")])
        return 0
    if args.cmd == "status":
        conn = dbmod.connect(config.db_path)
        for row in conn.execute("SELECT id, last_success_at, consecutive_failures, last_error FROM sources ORDER BY id"):
            print(f"{row[0]:24} ok={row[1] or '-':22} fails={row[2]} {(row[3] or '')[:80]}")
        return 0
    if args.cmd == "serve":
        import functools
        import http.server
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=config.site_dir)
        print(f"Serving {config.site_dir} at http://127.0.0.1:{args.port}/api/v1/health.json")
        http.server.ThreadingHTTPServer(("127.0.0.1", args.port), handler).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
