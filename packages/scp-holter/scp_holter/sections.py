"""Обвязка контейнера SCP-ECG: преамбула и таблица указателей секции 0."""

from dataclasses import dataclass
from typing import BinaryIO

PREAMBLE_LEN = 6
HEADER_LEN = 16
POINTER_LEN = 10


def u16(b: bytes, o: int = 0) -> int:
    return int.from_bytes(b[o : o + 2], "little")


def u32(b: bytes, o: int = 0) -> int:
    return int.from_bytes(b[o : o + 4], "little")


@dataclass(frozen=True, slots=True)
class Section:
    """Одна запись таблицы указателей секции 0."""

    id: int
    length: int
    index: int

    @property
    def header_offset(self) -> int:
        return self.index - 1

    @property
    def body_offset(self) -> int:
        return self.index - 1 + HEADER_LEN

    @property
    def body_length(self) -> int:
        return self.length - HEADER_LEN


@dataclass(frozen=True, slots=True)
class Container:
    crc: int
    declared_size: int
    sections: dict[int, Section]

    def __contains__(self, sid: int) -> bool:
        return sid in self.sections

    def __getitem__(self, sid: int) -> Section:
        return self.sections[sid]


def read_container(fh: BinaryIO) -> Container:
    """Разбирает преамбулу и секцию 0; пустые секции отбрасываются."""
    pre = fh.read(PREAMBLE_LEN)
    if len(pre) < PREAMBLE_LEN:
        raise ValueError("file shorter than the SCP-ECG preamble")
    crc, declared = u16(pre, 0), u32(pre, 2)

    fh.seek(PREAMBLE_LEN)
    head = fh.read(HEADER_LEN)
    if u16(head, 2) != 0:
        raise ValueError(f"expected section 0 at byte {PREAMBLE_LEN}, got id {u16(head, 2)}")
    body = fh.read(u32(head, 4) - HEADER_LEN)

    sections: dict[int, Section] = {}
    for o in range(0, len(body) - (POINTER_LEN - 1), POINTER_LEN):
        sid, length, index = u16(body, o), u32(body, o + 2), u32(body, o + 6)
        if length:
            sections[sid] = Section(sid, length, index)
    return Container(crc=crc, declared_size=declared, sections=sections)


def read_body(fh: BinaryIO, sec: Section) -> bytes:
    """Тело секции без её 16-байтового заголовка."""
    fh.seek(sec.body_offset)
    return fh.read(sec.body_length)
