#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


def _key(robot_id: str, suffix: str) -> str:
    if not robot_id or "/" in robot_id:
        raise SystemExit("robot_id must be non-empty and must not contain '/'")
    return f"dmc_robo/{robot_id}/{suffix}"


def _apply_connect_overrides(cfg: Any, mode: str, connect_endpoints: list[str]) -> Any:
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


class _Bridge:
    def __init__(self) -> None:
        from PySide6.QtCore import QObject, Signal

        class _B(QObject):
            log = Signal(str)
            imu = Signal(object)  # dict
            cam_jpeg = Signal(bytes)
            cam_meta = Signal(object)  # dict

        self._b = _B()

    @property
    def qobj(self):
        return self._b


def _decode_json_payload(sample: Any) -> Any:
    raw = sample.payload.to_bytes()
    return json.loads(raw.decode("utf-8"))


@dataclass
class MotorCommand:
    v_l: float
    v_r: float
    unit: str
    deadman_ms: int
    seq: int
    ts_ms: int

    def to_bytes(self) -> bytes:
        return json.dumps(
            {
                "v_l": self.v_l,
                "v_r": self.v_r,
                "unit": self.unit,
                "deadman_ms": int(self.deadman_ms),
                "seq": int(self.seq),
                "ts_ms": int(self.ts_ms),
            }
        ).encode("utf-8")


class ZenohClient:
    def __init__(self, *, open_session: Any, robot_id: str, bridge: _Bridge) -> None:
        self._open_session = open_session
        self._robot_id = robot_id
        self._bridge = bridge

        self._session: Any = None
        self._pub_motor: Any = None
        self._pub_oled: Any = None
        self._sub_imu: Any = None
        self._sub_cam_meta: Any = None
        self._sub_cam_jpeg: Any = None

    def open(self) -> None:
        self._session = self._open_session()
        self._pub_motor = self._session.declare_publisher(_key(self._robot_id, "motor/cmd"))
        self._pub_oled = self._session.declare_publisher(_key(self._robot_id, "oled/cmd"))

        def on_imu(sample: Any) -> None:
            try:
                payload = _decode_json_payload(sample)
                self._bridge.qobj.imu.emit(payload)
            except Exception as e:
                self._bridge.qobj.log.emit(f"imu decode failed: {e}")

        def on_meta(sample: Any) -> None:
            try:
                payload = _decode_json_payload(sample)
                self._bridge.qobj.cam_meta.emit(payload)
            except Exception:
                return

        def on_jpeg(sample: Any) -> None:
            try:
                jpg = sample.payload.to_bytes()
                self._bridge.qobj.cam_jpeg.emit(jpg)
            except Exception as e:
                self._bridge.qobj.log.emit(f"camera jpeg receive failed: {e}")

        self._sub_imu = self._session.declare_subscriber(_key(self._robot_id, "imu/state"), on_imu)
        self._sub_cam_meta = self._session.declare_subscriber(
            _key(self._robot_id, "camera/meta"), on_meta
        )
        self._sub_cam_jpeg = self._session.declare_subscriber(
            _key(self._robot_id, "camera/image/jpeg"), on_jpeg
        )

        self._bridge.qobj.log.emit("zenoh connected")

    def close(self) -> None:
        try:
            if self._sub_cam_jpeg is not None:
                self._sub_cam_jpeg.undeclare()
        finally:
            self._sub_cam_jpeg = None

        try:
            if self._sub_cam_meta is not None:
                self._sub_cam_meta.undeclare()
        finally:
            self._sub_cam_meta = None

        try:
            if self._sub_imu is not None:
                self._sub_imu.undeclare()
        finally:
            self._sub_imu = None

        try:
            if self._session is not None:
                self._session.close()
        finally:
            self._session = None
            self._pub_motor = None
            self._pub_oled = None

    def publish_motor(self, cmd: MotorCommand) -> None:
        if self._pub_motor is None:
            return
        self._pub_motor.put(cmd.to_bytes())

    def publish_oled(self, text: str) -> None:
        if self._pub_oled is None:
            return
        payload = {"text": str(text), "ts_ms": int(time.time() * 1000)}
        self._pub_oled.put(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def _get_by_path(obj: Any, path: str) -> Any:
    cur = obj
    if not path:
        return cur
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, (list, tuple)):
            try:
                cur = cur[int(part)]
            except Exception:
                return None
        else:
            return None
    return cur


def _extract_vec3(payload: Any, path: str) -> Optional[tuple[float, float, float]]:
    candidate = _get_by_path(payload, path)
    if candidate is None:
        return None

    if isinstance(candidate, dict):
        for keys in (("x", "y", "z"), ("gx", "gy", "gz"), ("wx", "wy", "wz")):
            x, y, z = candidate.get(keys[0]), candidate.get(keys[1]), candidate.get(keys[2])
            if all(isinstance(v, (int, float)) for v in (x, y, z)):
                return float(x), float(y), float(z)
        return None

    if isinstance(candidate, (list, tuple)) and len(candidate) >= 3:
        x, y, z = candidate[0], candidate[1], candidate[2]
        if all(isinstance(v, (int, float)) for v in (x, y, z)):
            return float(x), float(y), float(z)
        return None

    return None


def _autodetect_vec3(payload: Any) -> tuple[Optional[str], Optional[tuple[float, float, float]]]:
    candidates = ("gyro", "gyr", "angular_velocity", "angularVelocity")
    for path in candidates:
        vec = _extract_vec3(payload, path)
        if vec is not None:
            return path, vec

    q: deque[tuple[str, Any]] = deque([("", payload)])
    seen: set[int] = set()
    max_nodes = 500

    def _push(base: str, k: str, v: Any) -> None:
        if base:
            q.append((f"{base}.{k}", v))
        else:
            q.append((k, v))

    while q and max_nodes > 0:
        max_nodes -= 1
        path, obj = q.popleft()
        obj_id = id(obj)
        if obj_id in seen:
            continue
        seen.add(obj_id)

        if isinstance(obj, dict):
            vec = _extract_vec3(obj, "")  # type: ignore[arg-type]
        elif isinstance(obj, (list, tuple)):
            vec = _extract_vec3({"v": obj}, "v")
        else:
            vec = None
        if vec is not None:
            return (path or "<root>"), vec

        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(k, str):
                    _push(path, k, v)
        elif isinstance(obj, (list, tuple)):
            for i, v in enumerate(obj[:10]):
                _push(path, str(i), v)

    return None, None


class MainWindow:
    def __init__(self, *, client: ZenohClient, bridge: _Bridge, args: argparse.Namespace) -> None:
        from PySide6.QtCore import QEvent, QObject, QTimer, Qt
        from PySide6.QtGui import QAction, QCloseEvent, QFont, QKeyEvent
        from PySide6.QtWidgets import (
            QDoubleSpinBox,
            QFormLayout,
            QFrame,
            QGroupBox,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QMainWindow,
            QMessageBox,
            QPlainTextEdit,
            QPushButton,
            QSpinBox,
            QSplitter,
            QVBoxLayout,
            QWidget,
        )

        import pyqtgraph as pg

        self._Qt = Qt
        self._QCloseEvent = QCloseEvent
        self._QEvent = QEvent
        self._QObject = QObject
        self._QKeyEvent = QKeyEvent
        self._QMessageBox = QMessageBox

        self._client = client
        self._bridge = bridge
        self._args = args

        self._seq = 0
        self._pressed: set[int] = set()
        self._last_nonzero = False

        class _Win(QMainWindow):
            def __init__(self, owner: "MainWindow"):
                super().__init__()
                self._owner = owner

            def closeEvent(self, event: QCloseEvent) -> None:
                self._owner._on_close()
                event.accept()

        self._win = _Win(self)
        self._win.setWindowTitle(f"Zenoh Remote UI ({args.robot_id})")
        self._win.setMinimumSize(1100, 700)

        central = QWidget()
        root = QHBoxLayout(central)
        self._win.setCentralWidget(central)

        # Left: controls + logs
        left = QWidget()
        left_layout = QVBoxLayout(left)

        conn_box = QGroupBox("Connection")
        conn_form = QFormLayout(conn_box)
        self._lbl_status = QLabel("connecting...")
        self._lbl_status.setFrameStyle(QFrame.Panel | QFrame.Sunken)
        conn_form.addRow("status", self._lbl_status)
        self._lbl_keys = QLabel(
            "motor: left r/f, right u/j (release to stop)\n"
            "note: key capture disabled while typing in text fields"
        )
        conn_form.addRow("keys", self._lbl_keys)
        left_layout.addWidget(conn_box)

        motor_box = QGroupBox("Motor")
        motor_form = QFormLayout(motor_box)
        self._spin_step = QDoubleSpinBox()
        self._spin_step.setRange(0.0, 2.0)
        self._spin_step.setSingleStep(0.01)
        self._spin_step.setDecimals(3)
        self._spin_step.setValue(0.10)
        motor_form.addRow("speed step (mps)", self._spin_step)
        self._spin_hz = QDoubleSpinBox()
        self._spin_hz.setRange(1.0, 60.0)
        self._spin_hz.setDecimals(1)
        self._spin_hz.setValue(20.0)
        motor_form.addRow("publish Hz", self._spin_hz)
        self._spin_deadman = QSpinBox()
        self._spin_deadman.setRange(50, 2000)
        self._spin_deadman.setValue(300)
        motor_form.addRow("deadman ms", self._spin_deadman)
        self._btn_stop = QPushButton("STOP (send zero)")
        motor_form.addRow(self._btn_stop)
        self._lbl_motor = QLabel("v_l=0.000 v_r=0.000")
        self._lbl_motor.setFrameStyle(QFrame.Panel | QFrame.Sunken)
        motor_form.addRow("last cmd", self._lbl_motor)
        left_layout.addWidget(motor_box)

        oled_box = QGroupBox("OLED")
        oled_form = QFormLayout(oled_box)
        self._edit_oled = QLineEdit()
        self._btn_oled = QPushButton("Send")
        row = QWidget()
        row_l = QHBoxLayout(row)
        row_l.setContentsMargins(0, 0, 0, 0)
        row_l.addWidget(self._edit_oled, 1)
        row_l.addWidget(self._btn_oled)
        oled_form.addRow("text", row)
        left_layout.addWidget(oled_box)

        imu_box = QGroupBox("IMU (gyro)")
        imu_form = QFormLayout(imu_box)
        self._combo_gyro_path = QLineEdit()
        self._combo_gyro_path.setPlaceholderText("auto (examples: gyro, angular_velocity)")
        imu_form.addRow("field path", self._combo_gyro_path)
        self._lbl_gyro_path = QLabel("auto: (not detected yet)")
        self._lbl_gyro_path.setFrameStyle(QFrame.Panel | QFrame.Sunken)
        imu_form.addRow("auto detect", self._lbl_gyro_path)
        self._lbl_gyro = QLabel("x=-- y=-- z=--")
        self._lbl_gyro.setFont(QFont("Monospace"))
        self._lbl_gyro.setFrameStyle(QFrame.Panel | QFrame.Sunken)
        imu_form.addRow("latest", self._lbl_gyro)
        left_layout.addWidget(imu_box)

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(2000)
        left_layout.addWidget(QLabel("Log"))
        left_layout.addWidget(self._log, 1)

        # Right: camera + chart + raw json
        right_split = QSplitter()
        right_split.setOrientation(Qt.Vertical)

        cam_panel = QWidget()
        cam_layout = QVBoxLayout(cam_panel)
        cam_layout.setContentsMargins(0, 0, 0, 0)
        self._cam_label = QLabel("camera: waiting for jpeg...")
        self._cam_label.setAlignment(Qt.AlignCenter)
        self._cam_label.setMinimumHeight(300)
        self._cam_label.setFrameStyle(QFrame.Panel | QFrame.Sunken)
        self._lbl_cam_meta = QLabel("meta: --")
        self._lbl_cam_meta.setFrameStyle(QFrame.Panel | QFrame.Sunken)
        cam_layout.addWidget(self._cam_label, 1)
        cam_layout.addWidget(self._lbl_cam_meta)
        right_split.addWidget(cam_panel)

        imu_panel = QWidget()
        imu_layout = QVBoxLayout(imu_panel)
        imu_layout.setContentsMargins(0, 0, 0, 0)
        pg.setConfigOptions(antialias=True)
        self._plot = pg.PlotWidget()
        self._plot.showGrid(x=True, y=True, alpha=0.25)
        self._plot.addLegend()
        self._plot.setLabel("left", "gyro")
        self._plot.setLabel("bottom", "t", units="s")
        self._curve_x = self._plot.plot([], [], pen=pg.mkPen("r", width=2), name="x")
        self._curve_y = self._plot.plot([], [], pen=pg.mkPen("g", width=2), name="y")
        self._curve_z = self._plot.plot([], [], pen=pg.mkPen("b", width=2), name="z")
        self._raw = QPlainTextEdit()
        self._raw.setReadOnly(True)
        self._raw.setMaximumBlockCount(2000)
        self._raw.setPlaceholderText("imu raw JSON will appear here")
        imu_layout.addWidget(self._plot, 2)
        imu_layout.addWidget(QLabel("IMU raw JSON"))
        imu_layout.addWidget(self._raw, 1)
        right_split.addWidget(imu_panel)

        splitter = QSplitter()
        splitter.addWidget(left)
        splitter.addWidget(right_split)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

        # Menus
        action_quit = QAction("Quit", self._win)
        action_quit.triggered.connect(self._win.close)
        self._win.menuBar().addAction(action_quit)

        # Data buffers
        self._t0 = time.monotonic()
        self._buf_t: deque[float] = deque(maxlen=400)
        self._buf_x: deque[float] = deque(maxlen=400)
        self._buf_y: deque[float] = deque(maxlen=400)
        self._buf_z: deque[float] = deque(maxlen=400)

        # Wiring
        self._btn_oled.clicked.connect(self._on_send_oled)
        self._btn_stop.clicked.connect(lambda: self._send_stop(repeat=3))

        bridge.qobj.log.connect(self._append_log)
        bridge.qobj.imu.connect(self._on_imu)
        bridge.qobj.cam_jpeg.connect(self._on_cam_jpeg)
        bridge.qobj.cam_meta.connect(self._on_cam_meta)

        # Motor publish timer
        self._motor_timer = QTimer()
        self._motor_timer.timeout.connect(self._tick_motor)
        self._motor_timer.start(int(1000 / float(self._spin_hz.value())))
        self._spin_hz.valueChanged.connect(self._on_hz_changed)

        # Global key capture
        self._typing_widgets = (QLineEdit, QPlainTextEdit)

        class _KeyFilter(QObject):
            def __init__(self, owner: "MainWindow"):
                super().__init__()
                self._owner = owner

            def eventFilter(self, obj: Any, event: Any) -> bool:
                return self._owner._event_filter(obj, event)

        self._key_filter = _KeyFilter(self)

        # Open Zenoh now
        try:
            self._client.open()
            self._lbl_status.setText("connected")
        except SystemExit:
            raise
        except Exception as e:
            self._lbl_status.setText("error")
            self._append_log(f"connect failed: {e}")
            QMessageBox.critical(self._win, "Zenoh connect failed", str(e))

    def show(self) -> None:
        self._win.show()

    def _append_log(self, msg: str) -> None:
        ts = time.strftime("%H:%M:%S")
        self._log.appendPlainText(f"[{ts}] {msg}")

    def _event_filter(self, obj: Any, event: Any) -> bool:
        from PySide6.QtWidgets import QApplication, QPlainTextEdit

        if event.type() in (self._QEvent.ApplicationDeactivate, self._QEvent.WindowDeactivate):
            if self._pressed:
                self._pressed.clear()
                self._send_stop(repeat=2)
            return False

        if event.type() not in (self._QEvent.KeyPress, self._QEvent.KeyRelease):
            return False

        focused = QApplication.focusWidget()
        if focused is not None:
            if isinstance(focused, QPlainTextEdit) and focused.isReadOnly():
                pass
            elif isinstance(focused, self._typing_widgets):
                return False

        ev = event  # QKeyEvent
        key = ev.key()
        if key not in (
            self._Qt.Key_R,
            self._Qt.Key_F,
            self._Qt.Key_U,
            self._Qt.Key_J,
        ):
            return False

        if event.type() == self._QEvent.KeyPress and not ev.isAutoRepeat():
            self._pressed.add(key)
            return True
        if event.type() == self._QEvent.KeyRelease and not ev.isAutoRepeat():
            self._pressed.discard(key)
            if not self._pressed:
                self._send_stop(repeat=2)
            return True
        return False

    def _on_hz_changed(self, v: float) -> None:
        try:
            interval_ms = int(1000 / float(v))
        except Exception:
            interval_ms = 50
        self._motor_timer.setInterval(max(10, interval_ms))

    def _desired_motor(self) -> tuple[float, float]:
        step = float(self._spin_step.value())

        left = 0.0
        right = 0.0

        if self._Qt.Key_R in self._pressed:
            left += step
        if self._Qt.Key_F in self._pressed:
            left -= step

        if self._Qt.Key_U in self._pressed:
            right += step
        if self._Qt.Key_J in self._pressed:
            right -= step

        return left, right

    def _tick_motor(self) -> None:
        v_l, v_r = self._desired_motor()
        nonzero = (abs(v_l) > 1e-9) or (abs(v_r) > 1e-9)
        if not nonzero:
            if self._last_nonzero:
                self._send_stop(repeat=1)
            self._last_nonzero = False
            return

        self._last_nonzero = True
        self._lbl_motor.setText(f"v_l={v_l:+.3f} v_r={v_r:+.3f}")
        cmd = MotorCommand(
            v_l=v_l,
            v_r=v_r,
            unit="mps",
            deadman_ms=int(self._spin_deadman.value()),
            seq=self._seq,
            ts_ms=int(time.time() * 1000),
        )
        self._seq += 1
        try:
            self._client.publish_motor(cmd)
        except Exception as e:
            self._append_log(f"motor publish failed: {e}")

    def _send_stop(self, *, repeat: int) -> None:
        self._lbl_motor.setText("v_l=+0.000 v_r=+0.000")
        for _ in range(max(1, int(repeat))):
            cmd = MotorCommand(
                v_l=0.0,
                v_r=0.0,
                unit="mps",
                deadman_ms=int(self._spin_deadman.value()),
                seq=self._seq,
                ts_ms=int(time.time() * 1000),
            )
            self._seq += 1
            try:
                self._client.publish_motor(cmd)
            except Exception as e:
                self._append_log(f"stop publish failed: {e}")
                break

    def _on_send_oled(self) -> None:
        text = self._edit_oled.text()
        if not text:
            self._QMessageBox.information(self._win, "OLED", "text is empty")
            return
        try:
            self._client.publish_oled(text)
            self._append_log(f"oled sent: {text!r}")
        except Exception as e:
            self._append_log(f"oled publish failed: {e}")

    def _on_imu(self, payload: Any) -> None:
        try:
            self._raw.setPlainText(json.dumps(payload, ensure_ascii=False, indent=2))
        except Exception:
            self._raw.setPlainText(str(payload))

        path = self._combo_gyro_path.text().strip()
        vec = None
        if path:
            vec = _extract_vec3(payload, path)
        else:
            detected_path, vec = _autodetect_vec3(payload)
            if detected_path:
                self._lbl_gyro_path.setText(f"auto: {detected_path}")
            else:
                self._lbl_gyro_path.setText("auto: (not found)")

        if vec is None:
            self._lbl_gyro.setText("x=-- y=-- z=-- (set field path)")
            return

        x, y, z = vec
        self._lbl_gyro.setText(f"x={x:+.4f} y={y:+.4f} z={z:+.4f}")
        t = time.monotonic() - self._t0
        self._buf_t.append(t)
        self._buf_x.append(x)
        self._buf_y.append(y)
        self._buf_z.append(z)
        self._curve_x.setData(list(self._buf_t), list(self._buf_x))
        self._curve_y.setData(list(self._buf_t), list(self._buf_y))
        self._curve_z.setData(list(self._buf_t), list(self._buf_z))

    def _on_cam_meta(self, payload: Any) -> None:
        try:
            self._lbl_cam_meta.setText("meta: " + json.dumps(payload, ensure_ascii=False))
        except Exception:
            self._lbl_cam_meta.setText("meta: (decode failed)")

    def _on_cam_jpeg(self, jpg: bytes) -> None:
        from PySide6.QtGui import QImage, QPixmap

        img = QImage.fromData(jpg, "JPG")
        if img.isNull():
            self._append_log(f"camera jpeg decode failed (bytes={len(jpg)})")
            return
        pix = QPixmap.fromImage(img)
        scaled = pix.scaled(
            self._cam_label.size(), self._Qt.KeepAspectRatio, self._Qt.SmoothTransformation
        )
        self._cam_label.setPixmap(scaled)

    def _on_close(self) -> None:
        try:
            self._send_stop(repeat=3)
        finally:
            try:
                self._client.close()
            except Exception:
                pass


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Zenoh remote UI for dmc_robo")
    p.add_argument("--robot-id", required=True, help="robot_id (e.g. rasp-zero-01)")
    p.add_argument(
        "--zenoh-config",
        type=Path,
        default=None,
        help="Path to a zenoh json5 config. If omitted, uses defaults.",
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
    args = p.parse_args(argv)

    open_session = _build_session_opener(
        config_path=args.zenoh_config, mode=args.mode, connect_endpoints=list(args.connect)
    )

    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv[:1])
    bridge = _Bridge()
    client = ZenohClient(open_session=open_session, robot_id=args.robot_id, bridge=bridge)
    win = MainWindow(client=client, bridge=bridge, args=args)
    app.installEventFilter(win._key_filter)  # global motor key capture
    win.show()
    return int(app.exec())


if __name__ == "__main__":
    raise SystemExit(main())
