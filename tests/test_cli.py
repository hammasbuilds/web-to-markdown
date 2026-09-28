import io
import json
import sys
from pathlib import Path

import pytest

from web2md.cli import main

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "news_article.html"


def test_file_to_stdout(capsys):
    assert main([str(EXAMPLE)]) == 0
    out = capsys.readouterr().out
    assert "reopened to traffic" in out and "Related stories" not in out


def test_json_output(capsys):
    assert main([str(EXAMPLE), "--json", "--url", "https://courier.example/a"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["metadata"]["author"] == "Priya Raman"
    assert data["metadata"]["canonical_url"] == (
        "https://courier.example/news/2024/03/harbour-bridge-reopens"
    )
    assert data["tokens"]["html"] > data["tokens"]["markdown"] > 0


def test_front_matter_and_stats(capsys):
    assert main([str(EXAMPLE), "--front-matter", "--stats"]) == 0
    captured = capsys.readouterr()
    assert captured.out.startswith('---\ntitle: "Harbour bridge reopens after two-year repair"')
    assert "saved, estimated" in captured.err


def test_stdin(monkeypatch, capsys):
    stdin = io.TextIOWrapper(io.BytesIO(EXAMPLE.read_bytes()), encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", stdin)
    assert main(["-", "--no-links", "--no-images"]) == 0
    out = capsys.readouterr().out
    assert "reopened to traffic" in out and "](" not in out


def test_output_file(tmp_path):
    target = tmp_path / "out.md"
    assert main([str(EXAMPLE), "-o", str(target)]) == 0
    assert "reopened to traffic" in target.read_text(encoding="utf-8")


def test_output_into_a_missing_folder_creates_it(tmp_path):
    target = tmp_path / "new" / "deeper" / "out.md"
    assert main([str(EXAMPLE), "-o", str(target)]) == 0
    assert "reopened to traffic" in target.read_text(encoding="utf-8")


def test_unwritable_output_is_a_clear_error(tmp_path, capsys):
    blocker = tmp_path / "a-file"
    blocker.write_text("x", encoding="utf-8")
    assert main([str(EXAMPLE), "-o", str(blocker / "out.md")]) == 2
    err = capsys.readouterr().err
    assert "cannot write" in err and "Traceback" not in err


def test_directory_input_is_named_as_a_directory(tmp_path):
    with pytest.raises(SystemExit, match="is a directory"):
        main([str(tmp_path)])


def test_all_mode_keeps_boilerplate(capsys):
    assert main([str(EXAMPLE), "--all"]) == 0
    assert "Related stories" in capsys.readouterr().out


def test_url_without_fetch_is_refused():
    with pytest.raises(SystemExit, match="pass --fetch"):
        main(["https://example.com/"])


def test_missing_file_is_a_clear_error():
    with pytest.raises(SystemExit, match="no such file"):
        main(["does-not-exist.html"])


def test_empty_page_exits_nonzero_with_warning(tmp_path, capsys):
    empty = tmp_path / "empty.html"
    empty.write_text("<html><body></body></html>", encoding="utf-8")
    assert main([str(empty)]) == 1
    assert "no text content found" in capsys.readouterr().err


def test_help_lists_examples(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    assert "examples:" in capsys.readouterr().out


def test_binary_input_is_refused(tmp_path, capsys):
    blob = tmp_path / "image.png"
    blob.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + bytes(64))
    assert main([str(blob)]) == 2
    assert "binary file" in capsys.readouterr().err
