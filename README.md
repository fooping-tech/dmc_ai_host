# dmc_ai_host（Zenoh Remote UI）

このリポジトリは、Zenoh pub/sub 経由でロボットを遠隔操作するための最小UIアプリと、動作確認用の最小ツールを含みます。

- UIアプリ: `remote_zenoh_ui.py`
- 最小CLIツール: `docs/remote_zenoh_tool.py`
- Zenoh 接続/トピック説明: `docs/zenoh_remote_pubsub.md`

## 機能

- キーボード操作で左右タイヤを個別に前後進（左: `r` 前進 / `f` 後進、右: `u` 前進 / `j` 後進）
- IMU（ジャイロ）値をリアルタイムチャート表示（raw JSON 表示 + フィールドパス指定）
- カメラJPEGの最新フレーム表示（meta表示つき）
- LiDAR（`lidar/scan`）点群を2D表示（間引き・距離フィルタ）
- 表示範囲は 2m x 2m（x/y がそれぞれ -1.0〜+1.0m）
- 中心位置とフロント方向（+y）をアイコンで表示
- OLED表示テキスト送信

## 前提

- Python 3.9+（推奨）
- Zenoh router/peer 構成は `docs/zenoh_remote_pubsub.md` を参照

## セットアップ

venv例:

    python3 -m venv .venv
    source .venv/bin/activate
    python -m pip install -U pip
    python -m pip install -r requirements.txt

インストールで `PySide6` 関連の `*.tmpl.py` が `SyntaxError` になる場合（pip が bytecode compile しようとして失敗するケース）は、compile を無効化して入れてください:

    python -m pip install --no-compile -r requirements.txt

もしくは環境変数で:

    PIP_NO_COMPILE=1 PYTHONIOENCODING=utf-8 python -m pip install -r requirements.txt

## 起動（UI）

routerへ接続する例（推奨）:

    python remote_zenoh_ui.py --robot-id <ROBOT_ID> --connect "tcp/<ROUTER_IP>:7447"

json5設定ファイルを使う例:

    python remote_zenoh_ui.py --robot-id <ROBOT_ID> --zenoh-config ./zenoh_remote.json5

publish しているメッセージをターミナルに出したい場合:

    python remote_zenoh_ui.py --robot-id <ROBOT_ID> --connect "tcp/<ROUTER_IP>:7447" --print-pub

設定ファイルのテンプレート: `docs/zenoh_remote.json5.example`

## 操作（キーボード）

左右タイヤを独立制御します（キー押下中だけ一定周期で publish し、離すと停止指令を送ります）。

- 左タイヤ: `r` 前進 / `f` 後進
- 右タイヤ: `u` 前進 / `j` 後進
- カーソル: `↑` 前進 / `↓` 後退 / `←` 左回転 / `→` 右回転
- `STOP (send zero)` ボタン: ゼロ指令を送信

注意:

- このUIには `duration` の概念はありません（押している間だけ動かす設計です）。一定時間だけ動かしたい場合は `docs/remote_zenoh_tool.py motor --duration-s ...` を使ってください。
- テキスト入力欄にフォーカスがある間は、誤操作防止のためモータキーを拾いません。
- `deadman_ms` を payload に含めて送るため、通信断時はロボット側が停止する想定です（ロボット側実装に依存）。

## IMU（ジャイロ）チャート

`imu/state` の JSON スキーマが環境依存の可能性があるため、UIの `field path` に「ジャイロ3軸（x,y,z）」が入っているフィールドを指定できます。

例:

- `gyro`
- `angular_velocity`

raw JSON を見て、`gyro.x` のように `.` 区切りで辿れるパスを指定してください（配列は `0` / `1` / `2` の添字も可）。

## カメラ

- `camera/image/jpeg` を受信すると最新フレームを表示します
- `camera/meta` が届く場合は meta JSON も表示します

## OLED

テキストボックスに入力して `Send` を押すと `oled/cmd` に送信します。

## 緊急停止（別ターミナル）

UIが落ちた場合などは、付属の最小ツールで stop を投げてください。

    python docs/remote_zenoh_tool.py --robot-id <ROBOT_ID> --connect "tcp/<ROUTER_IP>:7447" stop

## トラブルシュート

- UIが受信できない:
  - `--robot-id` がロボット側と一致しているか確認
  - router構成なら、ロボット側/PC側が同じ router に `connect/endpoints` で接続しているか確認
- IMUがグラフに出ない:
  - raw JSON を見て `field path` を正しく指定（例: `gyro`）
- カメラが出ない:
  - ロボット側が `camera/image/jpeg` を publish しているか確認（`docs/remote_zenoh_tool.py` の `camera` サブコマンドでも切り分け可能）
