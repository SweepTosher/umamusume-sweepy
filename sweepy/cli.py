from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import sys
import threading
import webbrowser
from typing import Sequence

import sweepy.config as sweepy_config
from sweepy.brain_client import BrainClient, verify_contract
from sweepy.config import RuntimeConfig, apply_turn_delay, normalize_cm_style
from sweepy.macro_runner import MacroCareerRunner
from sweepy.stripper import resolve_cm_options_for_account, unwrap_data
from sweepy.webui import SweepyWebServer


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sweepy")
    parser.add_argument("--port", type=int, default=1616)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--api-url", type=str, default=None)
    parser.add_argument("--headless-once", action="store_true")
    parser.add_argument("--runtime-dir", type=str, default=None)
    parser.add_argument("--cm", type=str, default=None, help="Target CM preset/course for headless CM career")
    parser.add_argument("--cm-role", type=str, default=None, help="CM role (solo, ace, support, ace1_raw, ace2, debuffer, blocker)")
    parser.add_argument("--cm-style", type=str, default="0", help="Target running style 0..5 or auto/front/pace/late/end/runaway")
    parser.add_argument("--cm-track", type=str, default=None, help="Target CM track name or ID")
    parser.add_argument("--cm-distance", type=int, default=None, help="Target CM distance in meters")
    parser.add_argument("--cm-ground", type=str, default=None, help="Target CM surface (turf/dirt or 1/2)")
    parser.add_argument("--cm-ground-condition", type=str, default=None, help="Ground condition (firm/good/soft/heavy or 1..4)")
    parser.add_argument("--cm-weather", type=str, default=None, help="Weather (sunny/cloudy/rainy/snowy or 1..4)")
    parser.add_argument("--cm-season", type=str, default=None, help="Season (spring/summer/autumn/winter or 1..4)")
    parser.add_argument("--cm-course-id", type=int, default=None, help="Exact CM course_id")
    parser.add_argument("--cm-mates", type=str, default=None, help="Comma-separated trained_chara_ids or JSON path")
    return parser


def _bootstrap_cli_client(config: RuntimeConfig):
    from uma_headless import SteamTicketProvider, bootstrap_headless_auth

    token = (os.environ.get("SWEEPY_STEAM_TOKEN") or "").strip()
    provider = SteamTicketProvider(config.refresh_file, token=token or None)
    if not provider.has_refresh_token():
        provider.close()
        raise RuntimeError("no Steam token (SWEEPY_STEAM_TOKEN or web UI login)")
    provider.ensure_lease()
    client, boot_res = bootstrap_headless_auth(config.runtime_dir, provider)
    apply_turn_delay(client, config.load_settings()["turn_delay"])
    return client, provider, boot_res


def _build_cli_cm_options(
    args: argparse.Namespace,
    settings: dict,
    raw_data: dict | None,
) -> dict | None:
    env_args = [
        getattr(args, "cm_track", None),
        getattr(args, "cm_distance", None),
        getattr(args, "cm_ground", None),
        getattr(args, "cm_ground_condition", None),
        getattr(args, "cm_weather", None),
        getattr(args, "cm_season", None),
        getattr(args, "cm_course_id", None),
    ]
    if not any([args.cm, args.cm_role is not None, args.cm_mates, *env_args]):
        if not sweepy_config.CM_ENABLED:
            return None
        return resolve_cm_options_for_account(settings.get("cm_config"), raw_data)

    cm_cfg: dict = {
        "cm_mode": True,
        "cm_course": args.cm or (settings.get("cm_config") or {}).get("cm_course") or "sagittarius",
        "cm_role": args.cm_role if args.cm_role is not None else (0 if not args.cm_mates else 1),
        "cm_style": normalize_cm_style(args.cm_style),
    }
    if getattr(args, "cm_track", None) is not None:
        cm_cfg["track"] = args.cm_track
    if getattr(args, "cm_distance", None) is not None:
        cm_cfg["distance"] = int(args.cm_distance)
    if getattr(args, "cm_ground", None) is not None:
        cm_cfg["ground"] = args.cm_ground
    if getattr(args, "cm_ground_condition", None) is not None:
        cm_cfg["ground_condition"] = args.cm_ground_condition
    if getattr(args, "cm_weather", None) is not None:
        cm_cfg["weather"] = args.cm_weather
    if getattr(args, "cm_season", None) is not None:
        cm_cfg["season"] = args.cm_season
    if getattr(args, "cm_course_id", None) is not None:
        cm_cfg["course_id"] = int(args.cm_course_id)
    mates_arg = (args.cm_mates or "").strip()
    if mates_arg:
        p = Path(mates_arg)
        if p.is_file():
            loaded = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("members"), list):
                cm_cfg["cm_mates"] = loaded["members"]
            elif isinstance(loaded, dict) and isinstance(loaded.get("mates"), list):
                cm_cfg["cm_mates"] = loaded["mates"]
            elif isinstance(loaded, list):
                cm_cfg["cm_mates"] = loaded
            else:
                cm_cfg["cm_mates"] = [loaded]
        elif mates_arg.startswith("[") or mates_arg.startswith("{"):
            parsed = json.loads(mates_arg)
            cm_cfg["cm_mates"] = [parsed] if isinstance(parsed, dict) else list(parsed)
        else:
            cm_cfg["mate_ids"] = [int(x.strip()) for x in mates_arg.split(",") if x.strip()]
    return resolve_cm_options_for_account(cm_cfg, raw_data)


def _run_headless_once_cli(config: RuntimeConfig, args: argparse.Namespace | None = None) -> int:
    settings = config.load_settings()
    if not settings["api_key"]:
        raise RuntimeError("no bearer key (settings.json or SWEEPY_API_KEY)")

    brain = BrainClient(settings["api_url"], settings["api_key"])
    try:
        for warning in verify_contract(brain.meta()):
            print(f"contract: {warning}", file=sys.stderr, flush=True)
    except BaseException:
        brain.close()
        raise
    try:
        client, provider, boot_res = _bootstrap_cli_client(config)
    except BaseException:
        brain.close()
        raise
    try:
        raw_data = unwrap_data(boot_res)
        if "user_info" not in raw_data:
            raw_data = unwrap_data(client.login(read_info=True))
        cm_options = _build_cli_cm_options(args, settings, raw_data or None) if args is not None else resolve_cm_options_for_account(settings.get("cm_config"), raw_data or None)
        runner = MacroCareerRunner(account_salt=config.account_salt(), runtime_dir=config.runtime_dir)
        snap = runner.run_sync(
            client,
            brain,
            burn_clocks=bool(settings["burn_clocks"]),
            cm_options=cm_options,
            account_data=raw_data or None,
        )
        print(json.dumps(snap, ensure_ascii=False), flush=True)
        return 0 if snap.get("finished") else 1
    finally:
        brain.close()
        client.close()
        provider.close()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    config = RuntimeConfig(Path(args.runtime_dir) if args.runtime_dir else None)
    if args.api_url:
        env_key = os.environ.get("SWEEPY_API_KEY") or None
        config.set_brain_config(args.api_url, env_key)

    if args.headless_once:
        return _run_headless_once_cli(config, args)

    server = SweepyWebServer("127.0.0.1", int(args.port), config=config)
    url = server.url
    print(f"Sweepy running on {url}", flush=True)

    if not args.no_browser:
        threading.Timer(0.25, lambda: webbrowser.open(url)).start()

    stop_once = threading.Event()

    def _handle_sig(_signum: int, _frame: object) -> None:
        if not stop_once.is_set():
            stop_once.set()
            threading.Thread(target=server.shutdown, daemon=True).start()

    signal.signal(signal.SIGINT, _handle_sig)
    signal.signal(signal.SIGTERM, _handle_sig)

    try:
        server.serve_forever()
    finally:
        if not stop_once.is_set():
            stop_once.set()
            server.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
