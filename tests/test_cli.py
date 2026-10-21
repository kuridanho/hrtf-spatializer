from __future__ import annotations

from pathlib import Path

import pytest

from spatializer.__main__ import build_parser, main


def test_parser_defaults() -> None:
    args = build_parser().parse_args([])
    assert args.block_size == 512
    assert args.dataset_dir is None
    assert args.list_datasets is False


def test_list_datasets(dataset_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        [
            "--list-datasets",
            "--dataset-dir",
            str(dataset_dir.parent),
        ]
    )

    assert code == 0
    assert str(dataset_dir.resolve()) in capsys.readouterr().out


def test_list_datasets_missing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--list-datasets", "--dataset-dir", str(tmp_path)])

    assert code == 1
    assert "No datasets found" in capsys.readouterr().err


def test_invalid_block_size_is_rejected() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--block-size", "123"])
