"""First-run BlackHole setup guide."""

from __future__ import annotations

import tkinter as tk
import webbrowser
from tkinter import ttk

BLACKHOLE_URL = "https://existential.audio/blackhole/"

STEPS: tuple[tuple[str, str], ...] = (
    (
        "1. BlackHole をインストール",
        "existential.audio/blackhole/ からインストーラーを取得し、\n"
        "「BlackHole 2ch」を選んでインストールしてください。\n"
        "Homebrew を使う場合は  brew install blackhole-2ch  でも導入できます。",
    ),
    (
        "2. システム出力を BlackHole のみに変更  ⚠️ ここが重要",
        "システム設定 → サウンド → 出力 で「BlackHole 2ch」を選択します。\n"
        "\n"
        "AirPods などの物理デバイスと同時に選ばないでください。\n"
        "同時に選ぶと、原音と HRTF 処理後の音が重なってエコーになります。\n"
        "このアプリを使う間だけ、出力を BlackHole に向けてください。",
    ),
    (
        "3. アプリでデバイスを選択して開始",
        "入力に「BlackHole 2ch」、出力にヘッドホン / AirPods を選び、\n"
        "「▶ 開始」を押してください。\n"
        "\n"
        "音の流れ:  システム音声 → BlackHole → このアプリ (HRTF) → ヘッドホン",
    ),
)


def show_setup_dialog(parent: tk.Misc) -> None:
    """Display the BlackHole setup guide as a modal dialog."""
    dialog = tk.Toplevel(parent)
    dialog.title("BlackHole セットアップ")
    dialog.resizable(False, False)
    dialog.transient(parent)
    dialog.grab_set()

    ttk.Label(
        dialog,
        text="BlackHole 仮想デバイスが見つかりませんでした",
        font=("", 14, "bold"),
    ).pack(padx=12, pady=(12, 4))

    ttk.Label(
        dialog,
        text=(
            "macOS のシステム音声を取り込むには BlackHole が必要です。\n"
            "以下の手順に従ってセットアップしてください。"
        ),
        justify="center",
    ).pack(padx=12, pady=6)

    for title, body in STEPS:
        frame = ttk.LabelFrame(dialog, text=title, padding=8)
        frame.pack(fill="x", padx=12, pady=4)
        ttk.Label(frame, text=body, justify="left").pack(anchor="w")

    ttk.Button(
        dialog,
        text="BlackHole のダウンロードページを開く",
        command=lambda: webbrowser.open(BLACKHOLE_URL),
    ).pack(fill="x", padx=12, pady=(8, 2))

    buttons = ttk.Frame(dialog)
    buttons.pack(fill="x", padx=12, pady=(6, 12))
    ttk.Button(buttons, text="後で設定する", command=dialog.destroy).pack(side="left")
    ttk.Button(buttons, text="セットアップ完了 →", command=dialog.destroy).pack(side="right")

    dialog.update_idletasks()
    x = parent.winfo_rootx() + (parent.winfo_width() - dialog.winfo_width()) // 2
    y = parent.winfo_rooty() + (parent.winfo_height() - dialog.winfo_height()) // 2
    dialog.geometry(f"+{max(x, 0)}+{max(y, 0)}")
    parent.wait_window(dialog)
