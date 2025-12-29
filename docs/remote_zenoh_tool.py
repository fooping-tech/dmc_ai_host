#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Optional


def _apply_connect_overrides(cfg, mode: str, connect_endpoints: list[str]):
    if mode:
        cfg.insert_json5("mode", json.dumps(mode))
    if connect_endpoints:
        cfg.insert_json5("connect/endpoints", json.dumps(connect_endpoints))
    return cfg


def _build_session_opener(
    *, config_path: Optional[Path], mode: str, connect_endpoints: list[str]
):
    import zenoh  # provided by `pip install eclipse-zenoh`

    if config_path is not None and not config_path.exists():
        raise SystemExit(
            f"zenoh config not found: {config_path}\n"
            "Create it (see docs/zenoh_remote_pubsub.md) or omit --zenoh-config to use defaults."
        )

    if config_path:
        cfg = zenoh.Config.from_file(str(config_path))
    else:
        try:
            cfg = zenoh.Config.from_env()
        except Exception:
            cfg = zenoh.Config()

    if connect_endpoints:
        cfg = _apply_connect_overrides(cfg, mode, connect_endpoints)

    def _opener() -> Any:
        try:
            return zenoh.open(cfg)
        except Exception as e:
            raise SystemExit(f"failed to open zenoh session: {e}") from e

    return _opener


def _key(robot_id: str, suffix: str) -> str:
    if not robot_id or "/" in robot_id:
        raise SystemExit("robot_id must be non-empty and must not contain '/'")
    return f"dmc_robo/{robot_id}/{suffix}"


def cmd_motor(args: argparse.Namespace) -> int:
    key = _key(args.robot_id, "motor/cmd")
    session = args.open_session()
    pub = session.declare_publisher(key)

    interval_s = 1.0 / args.hz if args.hz > 0 else 0.05
    end_t = time.monotonic() + args.duration_s
    seq = 0

    try:
        while time.monotonic() < end_t:
            payload = {
                "v_l": args.v_l,
                "v_r": args.v_r,
                "unit": args.unit,
                "deadman_ms": args.deadman_ms,
                "seq": seq,
                "ts_ms": int(time.time() * 1000),
            }
            pub.put(json.dumps(payload).encode("utf-8"))
            seq += 1
            time.sleep(interval_s)
    finally:
        session.close()
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    key = _key(args.robot_id, "motor/cmd")
    session = args.open_session()
    pub = session.declare_publisher(key)

    try:
        for i in range(args.count):
            payload = {
                "v_l": 0.0,
                "v_r": 0.0,
                "unit": args.unit,
                "deadman_ms": args.deadman_ms,
                "seq": i,
                "ts_ms": int(time.time() * 1000),
            }
            pub.put(json.dumps(payload).encode("utf-8"))
            time.sleep(0.05)
    finally:
        session.close()
    return 0


def cmd_oled(args: argparse.Namespace) -> int:
    key = _key(args.robot_id, "oled/cmd")
    session = args.open_session()
    pub = session.declare_publisher(key)
    try:
        payload = {"text": args.text, "ts_ms": int(time.time() * 1000)}
        pub.put(json.dumps(payload).encode("utf-8"))
        time.sleep(0.1)
    finally:
        session.close()
    return 0


def _decode_json_payload(sample: Any) -> Any:
    raw = sample.payload.to_bytes()
    return json.loads(raw.decode("utf-8"))


def cmd_imu(args: argparse.Namespace) -> int:
    key = _key(args.robot_id, "imu/state")
    session = args.open_session()

    def on_sample(sample: Any) -> None:
        try:
            print(json.dumps(_decode_json_payload(sample), ensure_ascii=False))
        except Exception as e:
            print(f"decode failed: {e}")

    sub = session.declare_subscriber(key, on_sample)
    try:
        input("subscribing imu... press Enter to quit\n")
    finally:
        sub.undeclare()
        session.close()
    return 0


def cmd_camera(args: argparse.Namespace) -> int:
    key_img = _key(args.robot_id, "camera/image/jpeg")
    key_meta = _key(args.robot_id, "camera/meta")
    session = args.open_session()

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    state: dict[str, Any] = {"seq": None}

    def on_meta(sample: Any) -> None:
        try:
            meta = _decode_json_payload(sample)
            state["seq"] = meta.get("seq")
            if args.print_meta:
                print("meta:", json.dumps(meta, ensure_ascii=False))
        except Exception:
            return

    def on_img(sample: Any) -> None:
        jpg = sample.payload.to_bytes()
        seq = state.get("seq")
        name = out_dir / f"frame_{seq if seq is not None else int(time.time()*1000)}.jpg"
        name.write_bytes(jpg)
        print(f"saved: {name} ({len(jpg)} bytes)")

    sub_meta = session.declare_subscriber(key_meta, on_meta)
    sub_img = session.declare_subscriber(key_img, on_img)
    try:
        input("subscribing camera... press Enter to quit\n")
    finally:
        sub_img.undeclare()
        sub_meta.undeclare()
        session.close()
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Minimal remote Zenoh control tool for dmc_ai_mobility")
    p.add_argument("--robot-id", required=True, help="robot_id (e.g. rasp-zero-01)")
    p.add_argument(
        "--zenoh-config",
        type=Path,
        default=None,
        help="Path to a zenoh json5 config (connect/endpoints). If omitted, uses defaults.",
    )
    p.add_argument(
        "--mode",
        type=str,
        default="peer",
        help="Zenoh mode override when using --connect (default: peer).",
    )
    p.add_argument(
        "--connect",
        action="append",
        default=[],
        help='Connect endpoint override (repeatable), e.g. --connect "tcp/192.168.1.10:7447". '
        "If set, it is applied on top of defaults or --zenoh-config.",
    )

    sub = p.add_subparsers(dest="cmd", required=True)

    motor = sub.add_parser("motor", help="Publish motor/cmd for a duration")
    motor.add_argument("--v-l", type=float, required=True)
    motor.add_argument("--v-r", type=float, required=True)
    motor.add_argument("--unit", type=str, default="mps")
    motor.add_argument("--deadman-ms", type=int, default=300)
    motor.add_argument("--duration-s", type=float, default=2.0)
    motor.add_argument("--hz", type=float, default=20.0)
    motor.set_defaults(func=cmd_motor)

    stop = sub.add_parser("stop", help="Publish zero motor command a few times")
    stop.add_argument("--unit", type=str, default="mps")
    stop.add_argument("--deadman-ms", type=int, default=300)
    stop.add_argument("--count", type=int, default=5)
    stop.set_defaults(func=cmd_stop)

    oled = sub.add_parser("oled", help="Publish oled/cmd once")
    oled.add_argument("--text", type=str, required=True)
    oled.set_defaults(func=cmd_oled)

    imu = sub.add_parser("imu", help="Subscribe imu/state and print JSON")
    imu.set_defaults(func=cmd_imu)

    cam = sub.add_parser("camera", help="Subscribe camera jpeg/meta and save JPEGs")
    cam.add_argument("--out-dir", type=Path, default=Path("./camera_frames"))
    cam.add_argument("--print-meta", action="store_true")
    cam.set_defaults(func=cmd_camera)

    args = p.parse_args(argv)
    args.open_session = _build_session_opener(
        config_path=args.zenoh_config, mode=args.mode, connect_endpoints=list(args.connect)
    )
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
