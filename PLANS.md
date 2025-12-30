# Zenoh Remote UI: ロボット操作・IMUチャート・カメラ表示・OLEDテキスト設定

このExecPlanは living document です。実装中は `Progress` / `Surprises & Discoveries` / `Decision Log` / `Outcomes & Retrospective` を必ず更新し、途中停止してもこの1ファイルだけで再開できる状態を維持します。

このリポジトリは現状、設計・実装ガイドがこの `PLANS.md` しかありません。以降の作業はこのExecPlanの記述を唯一の仕様として進めます。


## Purpose / Big Picture

別PC（開発PC）から Zenoh を使ってロボットを遠隔操作できるデスクトップUIアプリを作ります。UIでできることは次の5つです。

1) キーボードで左右タイヤを個別に前後進させる（左: `r` 前進、`f` 後進 / 右: `u` 前進、`j` 後進）。  
2) ジャイロ（IMU）の値をリアルタイムにチャート表示する。  
3) ロボットが送ってくる最新のカメラJPEGを画面に表示する。  
4) OLEDに表示するテキストをUIから送って変更する。
5) LiDAR の点群（スキャン）を2Dで可視化する（俯瞰プロット）。

この変更の「動いた」が分かる状態は、アプリを起動して、キー入力で `dmc_robo/<robot_id>/motor/cmd` に publish が流れ、`dmc_robo/<robot_id>/imu/state` の値がグラフで動き、`dmc_robo/<robot_id>/camera/image/jpeg` が画面に出て、入力したテキストが `dmc_robo/<robot_id>/oled/cmd` に publish されることです。

LiDAR 対応の「動いた」は、`dmc_robo/<robot_id>/lidar/scan` を subscribe して、点が動的にプロットされ、点数や `lidar/front` のサマリがUI上で確認できることです。


## Progress

- [x] (2025-12-29) `docs/remote_zenoh_tool.py` / `docs/zenoh_remote_pubsub.md` / `docs/zenoh_remote.json5.example` を読み、Zenohキーと最低限のpayloadを把握した。
- [x] (2025-12-29) UIアプリ骨格（起動、接続、終了時停止）を追加した（`remote_zenoh_ui.py`）。
- [x] (2025-12-29) キーボード操作 → `motor/cmd` publish を実装した（キー押下中に継続送信、離すと停止）。
- [x] (2025-12-29) `imu/state` subscribe → チャート表示を実装した（raw JSON 表示 + `field path` 指定）。
- [x] (2025-12-29) `camera/*` subscribe → JPEG表示を実装した（最新フレーム表示、meta表示）。
- [x] (2025-12-29) OLED入力UI → `oled/cmd` publish を実装した。
- [x] (2025-12-29) `requirements.txt` と `docs/remote_ui.md` を追加した。
- [x] (2025-12-30) LiDAR（`lidar/scan` / `lidar/front`）を subscribe し、2D点群表示を追加した（`remote_zenoh_ui.py`）。
- [ ] 受け入れ手順（手動テスト）を実行し、必要ならパラメータ調整する。


## Surprises & Discoveries

- Observation: 現時点で `imu/state` のJSONスキーマ（ジャイロのキー名）がこのリポジトリ内に定義されていない。
  Evidence: `docs/remote_zenoh_tool.py` は JSON をそのままprintするだけでフィールド解釈が無い。
- Observation: `docs/zenoh_remote_pubsub.md` が参照している `doc/keys_and_payloads.md` がこのリポジトリには存在しない。
  Evidence: リポジトリ内に `doc/` ディレクトリが無い。


## Decision Log

- Decision: UIは Python + Qt（PySide6）で作り、チャートは `pyqtgraph` を使う。
  Rationale: デスクトップでのリアルタイム描画（画像 + グラフ）を最小実装で成立させやすい。
  Date/Author: 2025-12-29 / Codex

- Decision: 速度コマンドは「キー押下中だけ一定周期でpublish」し、キーが離れたらゼロ指令を送る（死活監視として `deadman_ms` を必ず付ける）。
  Rationale: UIの停止・通信断で走り続ける事故を避けるため（ロボット側が `deadman_ms` を尊重すると想定）。
  Date/Author: 2025-12-29 / Codex

- Decision: LiDAR の可視化は 3D ではなく 2D（極座標→XY）で行う。
  Rationale: `lidar/scan` が角度 + 距離の配列である前提だと 2D が最小で有用、かつ pyqtgraph で高速に描画できる。
  Date/Author: 2025-12-30 / Codex


## Outcomes & Retrospective

（未完了。実装が進んだら、できたこと・できなかったこと・原因をここに追記する）


## Context and Orientation

このリポジトリは「遠隔UIアプリ」をまだ含んでいません。既存の参考資料は `docs/` 配下の3ファイルだけです。

- `docs/remote_zenoh_tool.py` は Zenoh 経由で publish/subscribe する最小Pythonスクリプトです。キー命名、`--zenoh-config` / `--connect` などの接続設定、JSON payload の例が含まれます。
- `docs/zenoh_remote_pubsub.md` は別PCからZenoh router/peer構成で接続する考え方と、各トピックの役割（motor/imu/oled/camera）を説明しています。
- `docs/zenoh_remote.json5.example` は remote 側の zenoh 設定（routerへ connect）例です。

このExecPlanで使う用語を定義します。

- Zenoh: pub/sub（publish/subscribe）でメッセージをやり取りする通信基盤です。この作業では Python ライブラリ `eclipse-zenoh` を使い、`zenoh.open(config)` でセッション（接続）を開き、`declare_publisher` / `declare_subscriber` で送受信します。
- topic/key: Zenohでの宛先文字列です。本件では `dmc_robo/<robot_id>/...` の形を使います（`<robot_id>` はロボット個体識別子）。
- publish: 指定キーへデータを送ることです（例: `motor/cmd`）。
- subscribe: 指定キーのデータを受け取ることです（例: `imu/state` / `camera/*`）。
- deadman_ms: 送信が途切れた場合に停止するための猶予時間（ms）です。ロボット側実装がこれを解釈する前提で、UI側は常に付与します。

本件で扱う Zenoh キー（`docs/remote_zenoh_tool.py` と同じ）は以下です。

- モータ指令（publish）: `dmc_robo/<robot_id>/motor/cmd`
- IMU状態（subscribe）: `dmc_robo/<robot_id>/imu/state`
- OLED指令（publish）: `dmc_robo/<robot_id>/oled/cmd`
- カメラJPEG（subscribe）: `dmc_robo/<robot_id>/camera/image/jpeg`
- カメラmeta（subscribe）: `dmc_robo/<robot_id>/camera/meta`
- LiDAR scan（subscribe）: `dmc_robo/<robot_id>/lidar/scan`
- LiDAR front（subscribe）: `dmc_robo/<robot_id>/lidar/front`


## Plan of Work

このリポジトリに、遠隔操作UIアプリを「実行可能な1コマンド」として追加します。実装は以下の方針で最小化します。

1) まずアプリは「Zenoh接続→UI起動→終了時stop送信→セッションclose」までを確実にします（安全性の土台）。
2) 次にキーボード入力を取り込み、押下中は一定Hzで `motor/cmd` を publish します。左右タイヤを独立制御できるように「左/右の速度」を別々に合成します。
3) その後、IMUを subscribe してチャートに流します。IMUのJSONスキーマが不明なので、最初は「受信JSONを画面にも表示」し、既知候補（`gyro`, `gyr`, `angular_velocity` など）を試しつつ設定でフィールド名を切り替えられるようにします。スキーマが確定したらデフォルト設定を固定します。
4) カメラJPEGを subscribe して、最新フレームをUI表示します。metaが来るなら seq/ts も画面に表示します（なくても動く）。
5) OLEDはテキストボックス＋送信ボタンで `oled/cmd` を publish します。
6) LiDAR は `lidar/scan` と `lidar/front` を subscribe し、`scan` の点群を 2D に可視化します。`front` は数値サマリ（例: 正面距離）として別表示します。

成果物は次を想定します（最終決定は実装開始時に `Progress` で明記する）。

- `remote_zenoh_ui.py`（アプリ本体。単体実行できる）
- `requirements.txt`（依存を固定する。厳密な固定（hash）までは不要）
- `docs/remote_ui.md`（起動方法とキー割当、受信データの期待値、トラブルシュート）


## Concrete Steps

作業ディレクトリはこのリポジトリのルート（`dmc_ai_host`）です。

1) 仮想環境を作る（例）。既存環境がある場合は読み替えてよいです。

    python3 -m venv .venv
    source .venv/bin/activate
    python -m pip install -U pip

2) 依存を入れる（最小セット案）。

    python -m pip install eclipse-zenoh PySide6 pyqtgraph numpy pillow

補足: macOS の一部環境では `PySide6` の wheel 内に含まれる `*.tmpl.py` が bytecode compile 対象になり、`SyntaxError` でインストールが落ちることがあります。その場合は compile を無効化します。

    python -m pip install --no-compile eclipse-zenoh PySide6 pyqtgraph numpy pillow

3) 参考スクリプトで接続を確認する（UI作業の前に通信を切り分ける）。

    python docs/remote_zenoh_tool.py --robot-id <ROBOT_ID> --connect "tcp/<ROUTER_IP>:7447" imu

期待する観察: 何らかのJSONが継続的に表示される（ロボットがIMUをpublishしている場合）。

3.5) LiDAR の payload を確認する（点数・キー名をこの時点で把握し、UI実装の前提にする）。

    # (デフォルト) lidar/front のJSONを表示
    python docs/remote_zenoh_tool.py --robot-id <ROBOT_ID> --connect "tcp/<ROUTER_IP>:7447" lidar

    # lidar/scan のJSONをそのまま表示（配列が大きい場合あり）
    python docs/remote_zenoh_tool.py --robot-id <ROBOT_ID> --connect "tcp/<ROUTER_IP>:7447" lidar --scan --print-json

    # lidar/scan を角度(deg)/距離(m)として表示（先頭N点）
    python docs/remote_zenoh_tool.py --robot-id <ROBOT_ID> --connect "tcp/<ROUTER_IP>:7447" lidar --scan --print-points --max-points 200

4) UIアプリを実装し、起動できることを確認する（このExecPlanの後続マイルストーン）。

    python remote_zenoh_ui.py --robot-id <ROBOT_ID> --connect "tcp/<ROUTER_IP>:7447"


## Validation and Acceptance

受け入れ条件は「ロボットが実際にpublish/subscribeしている環境」で、次を満たすことです。

1) 起動: `python remote_zenoh_ui.py ...` でウィンドウが開き、接続エラーがあれば明確に表示される（黙って落ちない）。
2) キーボード: `r/f/u/j` の押下で `motor/cmd` が一定Hzで送信され、離すと停止（ゼロ指令）になる。アプリ終了時も停止指令が送られる。
3) IMU: `imu/state` を受信するとグラフが更新され、最新値（数値）がUI上で確認できる。スキーマ不一致の場合でも生JSONを確認でき、アプリがクラッシュしない。
4) カメラ: `camera/image/jpeg` を受信すると画像が表示・更新される。デコードできない場合はエラーをUIに表示しつつ継続する。
5) OLED: 入力したテキストが `oled/cmd` に送信される（確認方法はロボット側の表示、または別subscriberでpayloadを確認）。
6) LiDAR: `lidar/scan` を受信すると散布図が更新される。点数が多い場合でもUIが固まらず、必要に応じて間引き（max points / decimation）で描画する。`lidar/front` のサマリ値がUI上で確認できる。

安全条件（必須）:

- 例外でUIが落ちても、可能な範囲で停止指令を送る（少なくとも正常終了パスは確実に stop を送る）。
- `deadman_ms` を payload に必ず含める（デフォルト 300ms）。


## Idempotence and Recovery

- インストール手順（pip）は何度実行しても安全です（同一バージョンに上書きされるだけ）。
- UIアプリは何度起動しても安全であるべきです。もしクラッシュする場合は `Surprises & Discoveries` に再現手順とログを残し、復旧手順（例: 設定リセット）を `docs/remote_ui.md` に追記します。
- 走行安全のため、異常終了時の「止め方」を必ず用意します。最低限、別ターミナルから stop を投げられるようにします。

    python docs/remote_zenoh_tool.py --robot-id <ROBOT_ID> --connect "tcp/<ROUTER_IP>:7447" stop


## Artifacts and Notes

最低限、実装後にこのExecPlanへ貼るべきログの種類:

- 起動時に表示される接続情報（mode/connect/config の要約）
- `imu/state` の生JSON例（スキーマ確定の根拠）
- カメラJPEG受信時のmeta（あれば seq/ts）


## Interfaces and Dependencies

### Zenoh I/F（送受信）

このアプリは `docs/remote_zenoh_tool.py` と同等の接続オプションを持ちます。

- `--robot-id <id>`（必須。`/` を含まない）
- `--zenoh-config <path>`（任意。json5）
- `--connect <endpoint>`（任意。複数指定可。`tcp/<ip>:7447` など）
- `--mode <peer|client|...>`（任意。`--connect` を使う場合の上書き用。デフォルト `peer`）

publishするpayload（JSON）は `docs/remote_zenoh_tool.py` を踏襲します。

- motor/cmd:
  - `v_l` (float): 左速度
  - `v_r` (float): 右速度
  - `unit` (str): 既定 `"mps"`
  - `deadman_ms` (int): 既定 `300`
  - `seq` (int): 送信連番
  - `ts_ms` (int): epoch ms

- oled/cmd:
  - `text` (str)
  - `ts_ms` (int)

subscribeするpayload:

- imu/state: UTF-8 JSON（スキーマは現場データから確定し、確定後にこのExecPlanへ追記する）
- camera/image/jpeg: JPEG bytes
- camera/meta: UTF-8 JSON（例: `seq` を含む可能性がある）
- lidar/scan: UTF-8 JSON（以下の最小想定は `docs/remote_zenoh_tool.py` 実装に基づく）
  - `seq` (int|null)
  - `ts_ms` (int|null)
  - `points` (list[object]): 各点が少なくとも `angle_rad` と `range_m` を含む想定
    - `angle_rad` (float): 角度 [rad]
    - `range_m` (float): 距離 [m]
    - `intensity` (float|int|null): 任意
- lidar/front: UTF-8 JSON（スキーマ未確定。現場データから確定し、このExecPlanへ追記する）

### UI I/F（操作）

- 速度設定: UIに「速度ステップ（mps）」の設定を置き、キー押下で `-step / 0 / +step` を左右それぞれに適用して合成する。
- キー同時押し: 左右キーは同時押し可能とし、例えば `r` + `u` で前進、`f` + `j` で後退、`r` + `j` で旋回のような合成ができる。

### Python依存

最低限の依存:

- `eclipse-zenoh`（Zenohクライアント）
- `PySide6`（UI）
- `pyqtgraph`（高速チャート）
- `numpy`（チャート用リングバッファ等に利用）
- `pillow`（必要ならJPEGデコード補助。Qtの `QImage.fromData` だけで十分なら省略可）

LiDAR 可視化で追加が必要になる可能性:

- `numpy` は既に入っているので、極座標→XY変換・間引き・色付けに使う（追加依存なしで実現する）。


---

変更メモ（このファイル自体の改訂理由）:

- 2025-12-29: ユーザー要件（Zenoh pub/sub の遠隔操作UI）に合わせ、既存の汎用テンプレートを「本リポジトリの具体ExecPlan」に全面置換した。
