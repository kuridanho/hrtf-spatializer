from __future__ import annotations
import tkinter as tk
from tkinter import ttk


STEPS = [
    (
        "1. BlackHole をインストール",
        "https://existential.audio/blackhole/ からインストーラーをダウンロードして\n"
        "実行してください。「BlackHole 2ch」を選択してください。",
    ),
    (
        "2. システム出力を BlackHole のみに変更  ⚠️ ここが重要",
        "システム設定 → サウンド → 出力 で「BlackHole 2ch」を選択してください。\n"
        "\n"
        "※ AirPods Pro など物理デバイスと同時に選ばないでください。\n"
        "  同時に選ぶと元の音とHRTF処理後の音が重なりエコーになります。\n"
        "  このアプリを起動している間だけ、出力は BlackHole に向けてください。",
    ),
    (
        "3. アプリでデバイスを選択して開始",
        "アプリの「入力デバイス」で「BlackHole 2ch」を選択し、\n"
        "「出力デバイス」でヘッドホン / AirPods Pro を選択して「開始」を押してください。\n"
        "\n"
        "音の流れ:  システム音声 → BlackHole → このアプリ（HRTF処理）→ AirPods Pro",
    ),
]


def show_setup_dialog(parent: tk.Misc) -> None:
    """Display BlackHole setup guide as a modal dialog."""
    dlg = tk.Toplevel(parent)
    dlg.title("BlackHole セットアップ")
    dlg.resizable(False, False)
    dlg.grab_set()  # modal

    pad = {"padx": 12, "pady": 6}

    header = ttk.Label(
        dlg,
        text="BlackHole 仮想デバイスが見つかりませんでした",
        font=("", 14, "bold"),
    )
    header.pack(**pad, pady=(12, 4))

    sub = ttk.Label(
        dlg,
        text=(
            "このアプリは macOS のシステム音声をキャプチャするために\n"
            "BlackHole 仮想オーディオドライバが必要です。\n"
            "以下の手順に従ってセットアップしてください。"
        ),
        justify="center",
    )
    sub.pack(**pad)

    for title, body in STEPS:
        frame = ttk.LabelFrame(dlg, text=title, padding=8)
        frame.pack(fill="x", padx=12, pady=4)
        ttk.Label(frame, text=body, justify="left").pack(anchor="w")

    btn_frame = ttk.Frame(dlg)
    btn_frame.pack(fill="x", padx=12, pady=(6, 12))
    ttk.Button(btn_frame, text="スキップ（後で設定）", command=dlg.destroy).pack(side="left")
    ttk.Button(btn_frame, text="セットアップ完了 →", command=dlg.destroy).pack(side="right")

    # Center over parent
    dlg.update_idletasks()
    x = parent.winfo_rootx() + (parent.winfo_width() - dlg.winfo_width()) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - dlg.winfo_height()) // 2
    dlg.geometry(f"+{x}+{y}")
    parent.wait_window(dlg)
