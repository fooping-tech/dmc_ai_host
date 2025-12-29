# Zenoh Remote UI（操作UIアプリ）

このリポジトリの `remote_zenoh_ui.py` は、Zenoh pub/sub 経由でロボットを操作し、IMU（ジャイロ）とカメラを表示し、OLED表示文字列を送るデスクトップUIです。

前提となる Zenoh キーやネットワーク構成の説明は `docs/zenoh_remote_pubsub.md` を参照してください。

## セットアップ

例（venv）:

    python3 -m venv .venv
    source .venv/bin/activate
    python -m pip install -U pip
    python -m pip install -r requirements.txt

`PySide6` のインストールで `*.tmpl.py` が `SyntaxError` になる場合（pip の bytecode compile が原因のケース）は、次で回避できます:

    python -m pip install --no-compile -r requirements.txt

## 起動

routerへ接続する例（推奨）:

    python remote_zenoh_ui.py --robot-id <ROBOT_ID> --connect "tcp/<ROUTER_IP>:7447"

json5設定ファイルを使う例:

    python remote_zenoh_ui.py --robot-id <ROBOT_ID> --zenoh-config ./zenoh_remote.json5

## 操作（キーボード）

左右タイヤを独立制御します（キー押下中だけ一定周期で publish し、離すと停止指令を送ります）。

- 左タイヤ: `r` 前進 / `f` 後進
- 右タイヤ: `u` 前進 / `j` 後進

注意:

- テキスト入力欄（OLEDやIMU rawなど）にフォーカスがある間は、誤操作防止のためモータキーを拾いません。
- `STOP` ボタンでもゼロ指令を送れます。
- `duration` 指定で一定時間だけ動かしたい場合は `docs/remote_zenoh_tool.py motor --duration-s ...` を使ってください（UIは押している間だけ動かす設計です）。

## IMU（ジャイロ）チャート

`imu/state` の JSON スキーマは環境依存の可能性があるため、UIの `field path` でジャイロ3軸（x,y,z）が入っているフィールドを指定できます。

例:

- `gyro`
- `angular_velocity`

raw JSON を見て、`gyro.x` のように `.` 区切りで辿れるパスを指定してください（配列は `0` / `1` / `2` の添字も可）。

## カメラ表示

- `camera/image/jpeg` を受信すると最新フレームを画面に表示します。
- `camera/meta` が届く場合、meta JSON を表示します。

## OLED

テキストボックスに入力して `Send` を押すと `oled/cmd` に送信します。

## 緊急停止（別ターミナル）

UIが落ちた場合などは、付属の最小ツールで stop を投げてください。

    python docs/remote_zenoh_tool.py --robot-id <ROBOT_ID> --connect "tcp/<ROUTER_IP>:7447" stop
