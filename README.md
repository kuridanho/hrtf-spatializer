# Spatializer — HRTF binaural spatializer for macOS

[![CI](https://github.com/kuridanho/hrtf-spatializer/actions/workflows/ci.yml/badge.svg)](https://github.com/kuridanho/hrtf-spatializer/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

**Spatializer** turns macOS system audio into binaural, headphone audio in real
time. System sound is captured with [BlackHole](https://existential.audio/blackhole/),
convolved with a measured 21-direction HRTF set, and played through headphones
or AirPods.

```
┌──────────────┐    ┌────────────┐    ┌──────────────────────┐    ┌────────────┐
│ System audio │───▶│ BlackHole  │───▶│ Spatializer (UPOLS)  │───▶│ Headphones │
└──────────────┘    │   2ch      │    │ 21 HRIRs → binaural  │    │  AirPods   │
                    └────────────┘    └──────────────────────┘    └────────────┘
```

> [!IMPORTANT]
> The HRTF measurement dataset is **not included**.  The app runs without it,
> but audio processing can only start after you place a dataset in `dataset/`
> (or point `--dataset-dir` / `SPATIALIZER_DATASET_DIR` at one).  See
> [docs/dataset.md](docs/dataset.md) for the exact format.

## 特徴

- **21 方向の HRTF をリアルタイム畳み込み** — 左右 10° 刻み + 正面。入力をパン係数で分配し、左右耳を平均してバイノーラル化。
- **UPOLS（Uniform Partitioned Overlap-Save）** — HRIR をブロック単位に分割し、周波数領域で低遅延処理。512 samples @ 44.1 kHz = 11.6 ms（アルゴリズム遅延）。
- **Rust 拡張（任意）** — `upols_core` が履歴 gather と行列積を融合し rayon で並列化。未ビルドでも NumPy フォールバックで動作。
- **BlackHole / AirPods 自動検出** — 入力・出力デバイスを選択可能。デバイス一覧の再読込にも対応。
- **BYPASS / 音量 / L/R レベルメーター** — 処理前後を聴き比べられる。
- **データセット非依存の起動** — データが未配置でも GUI は起動し、配置後に「再スキャン」で認識。
- **合成データセット生成** — 実測データが届く前に `scripts/generate_dummy_dataset.py` で動作確認できる。

## 必要環境

- macOS 13 以降（Apple Silicon / Intel）
- Python 3.10 以降 + tkinter
- [BlackHole 2ch](https://existential.audio/blackhole/)（`brew install blackhole-2ch`）
- ヘッドホンまたは AirPods（出力デバイス）

## インストール

```bash
git clone https://github.com/kuridanho/hrtf-spatializer.git
cd hrtf-spatializer

python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"

# tkinter が入っていない場合（Homebrew Python）
brew install python-tk@3.12   # Python のバージョンに合わせて変更
```

## HRTF データセット

`dataset/` の直下に、21 個の WAV を含むディレクトリを置きます。

```text
dataset/
└── home_impulse_bedroom_441_6/
    ├── 0_0.wav
    ├── 10_0.wav
    ├── 0_10.wav
    ├── …
    └── 0_100.wav
```

- 各ファイルは **2ch / 同一サンプルレート / 同一長** のステレオ WAV。
- ファイル名 `L_R` は左右の角度（`30_0` = 左 30°、`0_30` = 右 30°、`0_0` = 正面）。
- `0_0(2).wav` のように `(2)` 付きのテイクがある場合、既定で 2 テイクを平均します。
- データセットの探索は「21 ファイルが揃っているディレクトリ」です。`--dataset-dir` には親フォルダでも、データセット自身でも指定できます。

詳細・測定方法・変換方法は **[docs/dataset.md](docs/dataset.md)** を参照してください。

実測データがまだ無い場合は、動作確認用の合成データを生成できます。

```bash
python scripts/generate_dummy_dataset.py --out dataset/demo
python scripts/validate_dataset.py dataset/demo
```

> [!WARNING]
> 合成データは ITD/ILD を模しただけのダミーです。音質・定位の評価には使わないでください。

## 使い方

1. BlackHole 2ch をインストールする。
2. **システム設定 → サウンド → 出力** を **BlackHole 2ch のみ** にする（AirPods と同時に選ぶとエコーになります）。
3. アプリを起動する。

```bash
spatializer --dataset-dir dataset
# または
python -m spatializer --dataset-dir dataset
# チェックアウト直後なら
python main.py --dataset-dir dataset
```

4. 入力に **BlackHole 2ch**、出力に **ヘッドホン / AirPods** を選び、**▶ 開始** を押す。
5. 音量スライダーと **BYPASS** で処理前後を比較する。

### コマンドラインオプション

| オプション | 説明 |
|---|---|
| `--dataset-dir PATH` | データセット、またはデータセットを格納したフォルダ |
| `--sample-rate HZ` | ストリームのサンプルレート（既定 44100、データセットと一致必須） |
| `--block-size {256,512,1024}` | 1 ブロックのサンプル数（既定 512） |
| `--list-datasets` | 検出したデータセットを表示して終了（GUI 不要） |
| `--debug` | デバッグログを表示 |

環境変数 `SPATIALIZER_DATASET_DIR` でもデータセット位置を指定できます。

```bash
export SPATIALIZER_DATASET_DIR="$HOME/Documents/hrtf/measured"
spatializer
```

### GUI の操作

- **開始 / 停止** — ストリームの開始・停止。開始時にデータセットを読み込み、フィルタバンクを構築します（読み込み中は UI が待機状態になります）。
- **BYPASS** — HRTF を通さず素通し。原音との比較に。
- **HRTF データセット** — 検出済みデータセットの選択。**再スキャン** で `dataset/` を再探索。
- **ブロックサイズ** — 256 / 512 / 1024。小さいほど低遅延、大きいほど CPU に余裕。変更は次回開始時に反映。
- **音量** — 0〜150%。出力ゲインとして適用（BYPASS 時も有効）。
- **レベルメーター** — 左右の RMS とピークホールド（-60 dB スケール）。

## アーキテクチャ

```text
src/spatializer/
├── __main__.py          # CLI / tkinter 起動
├── config.py            # 定数・データセットパス解決
├── engine/
│   ├── hrtf.py          # WAV 読み込み・21 方向定義・検証
│   ├── upols.py         # UPOLS 空間化エンジン（NumPy / Rust）
│   └── audio.py         # sounddevice duplex ストリーム・デバイス検出
└── gui/
    ├── main_window.py   # 画面構成・スレッド連携
    ├── control_panel.py # 開始/停止・データセット・音量
    ├── device_panel.py  # 入出力デバイス
    ├── level_meter.py   # L/R メーター
    └── setup_dialog.py  # BlackHole セットアップ案内
```

### 信号処理

1. ステレオ入力を 21 方向へパン係数で分配（`(B, 2) @ (2, 21)`）。
2. 各方向の 2B サンプル窓を `rfft`。
3. 周波数領域の円環バッファに格納し、HRIR を B サンプルごとに分割したフィルタ（K パーティション）と積和。
4. `irfft` して overlap-save の有効半区間を取り出す。
5. 21 方向の左右耳出力を平均して 2ch に戻す。

フィルタバンクは起動時に構築し、`update_dataset()` では次ブロックからアトミックに差し替えます。音声コールバック内では重い再構築を行いません。

### レイテンシ

| ブロックサイズ | アルゴリズム遅延（44.1 kHz） |
|---|---|
| 256 | 5.8 ms |
| 512 | 11.6 ms |
| 1024 | 23.2 ms |

実際の遅延はデバイスバッファと OS のスケジューリングを含みます。

## Rust アクセラレータ（任意）

```bash
pip install maturin
maturin develop --release --manifest-path rust/upols_core/Cargo.toml
spatializer --debug   # "UPOLS accelerator enabled" と表示されれば有効
```

または wheel を作ってインストール:

```bash
maturin build --release --interpreter "$(which python)" \
  --manifest-path rust/upols_core/Cargo.toml --out dist
pip install --no-deps dist/upols_core-*.whl
```

拡張が無い場合は自動的に NumPy 実装へフォールバックします。動作は同じで、速度のみ異なります。

## ベンチマーク

```bash
python scripts/benchmark.py --dataset-dir dataset/demo
# 入力 WAV を使う場合
python scripts/benchmark.py --dataset-dir dataset --input music.wav --output out.wav
```

1 ブロックあたりの平均 / p95 / 最大処理時間と、リアルタイム予算に対する余裕を表示します。80% を超えると警告し、終了コード 1 を返します。

## 開発

```bash
pytest -q
ruff check .
ruff format --check .
```

テストは実測データを必要としません。合成 HRIR を一時ディレクトリに生成し、直接畳み込みとの数値一致、データセット検証、デバイス検出、コールバックの BYPASS / ゲインを確認します。

## トラブルシューティング

**BlackHole が見つからない**
: `brew install blackhole-2ch` で導入し、macOS を再起動（または `sudo killall coreaudiod`）してください。

**音が二重になる / エコーになる**
: システム出力が BlackHole と AirPods の両方になっていませんか。BlackHole のみにしてください。

**音が出ない**
: 入力が BlackHole、出力がヘッドホンになっているか確認。BYPASS で原音が出るか試してください。

**`tkinter` が見つからない**
: `brew install python-tk@3.12` など、使用中の Python に合う formula を入れてください。

**`データセットとストリームのサンプルレートが一致しません`**
: `--sample-rate` をデータセットのレートに合わせるか、HRIR を 44.1 kHz に変換してください。

**音が途切れる / ノイズが乗る**
: ブロックサイズを 1024 に増やす、Rust 拡張を有効化する、他のオーディオアプリを終了する、の順に試してください。

**`HRTF データセットが不完全です`**
: 21 ファイルすべてが必要です。`python scripts/validate_dataset.py <dir>` で不足ファイルを確認できます。

## ライセンス

コードは [MIT License](LICENSE) です。

HRTF データセットはこのリポジトリに含まれません。実測データには測定者・配布元のライセンスが適用される場合があるため、`dataset/` は `.gitignore` で除外されています。公開・再配布の前に権利を確認してください。
