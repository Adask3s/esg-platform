from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException

from backend.utils.files import (
    calculate_file_hash,
    sanitize_filename,
    save_upload_streamed,
    sniff_simple_mime,
    validate_file_on_disk,
)


class FakeUpload:
    def __init__(self, chunks: list[bytes]):
        self._chunks = list(chunks)
        self.seek_position = None

    async def read(self, _chunk_size: int) -> bytes:
        return self._chunks.pop(0) if self._chunks else b""

    async def seek(self, position: int) -> None:
        self.seek_position = position


def test_sanitize_filename_removes_path_and_unsafe_chars():
    assert sanitize_filename(r"..\..\strange file @2026.pdf") == "strange_file_2026.pdf"
    assert sanitize_filename("   ") == "file"


def test_save_upload_streamed_writes_chunks_and_resets_upload(tmp_path: Path):
    upload = FakeUpload([b"abc", b"def"])
    dst = tmp_path / "out.bin"

    written = asyncio.run(save_upload_streamed(upload, dst, chunk_size=2))

    assert written == 6
    assert dst.read_bytes() == b"abcdef"
    assert upload.seek_position == 0


def test_sniff_simple_mime_detects_pdf_text_and_binary(tmp_path: Path):
    pdf = tmp_path / "file.pdf"
    txt = tmp_path / "file.txt"
    binary = tmp_path / "file.bin"
    pdf.write_bytes(b"%PDF-1.7\n")
    txt.write_bytes(b"plain text\n")
    binary.write_bytes(b"\x00\x01\x02\x03")

    assert sniff_simple_mime(pdf) == "application/pdf"
    assert sniff_simple_mime(txt) == "text/plain"
    assert sniff_simple_mime(binary) == "application/octet-stream"


def test_validate_file_on_disk_accepts_valid_pdf_and_txt(tmp_path: Path):
    pdf = tmp_path / "valid.pdf"
    txt = tmp_path / "valid.txt"
    pdf.write_bytes(b"%PDF-1.7\nbody")
    txt.write_text("plain text", encoding="utf-8")

    validate_file_on_disk(pdf, pdf.name)
    validate_file_on_disk(txt, txt.name)


def test_validate_file_on_disk_rejects_bad_extension_and_header(tmp_path: Path):
    exe = tmp_path / "bad.exe"
    fake_pdf = tmp_path / "bad.pdf"
    exe.write_bytes(b"data")
    fake_pdf.write_bytes(b"not a pdf")

    with pytest.raises(HTTPException) as ext_error:
        validate_file_on_disk(exe, exe.name)
    assert ext_error.value.status_code == 415

    with pytest.raises(HTTPException) as mime_error:
        validate_file_on_disk(fake_pdf, fake_pdf.name)
    assert mime_error.value.status_code == 415


def test_calculate_file_hash_is_sha256(tmp_path: Path):
    path = tmp_path / "data.txt"
    path.write_text("abc", encoding="utf-8")

    assert calculate_file_hash(path) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
