from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class RmcFix:
    sentence_type: str
    utc_ns: int
    valid: bool
    raw_sentence: str


def checksum_valid(sentence: str) -> bool:
    sentence = sentence.strip()
    if not sentence.startswith("$") or "*" not in sentence:
        return False
    body, supplied = sentence[1:].split("*", 1)
    checksum = 0
    for char in body:
        checksum ^= ord(char)
    try:
        return checksum == int(supplied[:2], 16)
    except ValueError:
        return False


def parse_rmc(sentence: str) -> RmcFix | None:
    text = sentence.strip()
    if not checksum_valid(text):
        return None
    body = text[1:text.index("*")]
    fields = body.split(",")
    if not fields or fields[0] not in {"GPRMC", "GNRMC"}:
        return None
    if len(fields) < 10 or not fields[1] or not fields[9]:
        return None

    time_text = fields[1]
    date_text = fields[9]
    status = fields[2] if len(fields) > 2 else "V"

    hours = int(time_text[0:2])
    minutes = int(time_text[2:4])
    seconds_float = float(time_text[4:])
    seconds = int(seconds_float)
    microseconds = int(round((seconds_float - seconds) * 1_000_000))
    if microseconds >= 1_000_000:
        seconds += 1
        microseconds -= 1_000_000

    day = int(date_text[0:2])
    month = int(date_text[2:4])
    year_two_digit = int(date_text[4:6])
    year = 2000 + year_two_digit if year_two_digit < 80 else 1900 + year_two_digit

    dt = datetime(year, month, day, hours, minutes, seconds, microseconds, tzinfo=timezone.utc)
    return RmcFix(
        sentence_type=fields[0],
        utc_ns=int(round(dt.timestamp() * 1e9)),
        valid=(status == "A"),
        raw_sentence=text,
    )


def rmc_second_utc_ns(fix: RmcFix) -> int:
    return int(round(fix.utc_ns / 1e9)) * 1_000_000_000
