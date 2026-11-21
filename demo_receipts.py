"""Repeatable photo and scan samples for the offline duplicate review demo."""

from functools import lru_cache
from hashlib import sha256
from io import BytesIO
import json

from PIL import Image, ImageDraw, ImageFont

from demo import SAMPLE_KEY, azure_fixture
from duplicate_receipts import receipt_number


@lru_cache(maxsize=2)
def demo_variants(original):
    with Image.open(BytesIO(original)) as source:
        photo = source.convert("RGB")
    rotated = photo.rotate(2, resample=Image.Resampling.BICUBIC, expand=True, fillcolor="#d8d7d4")
    cropped = photo.copy()
    ImageDraw.Draw(cropped).rectangle((302, 124, 460, 163), fill="#fcfaf5")
    separate = photo.copy()
    draw = ImageDraw.Draw(separate)
    draw.rectangle((302, 124, 460, 163), fill="#fcfaf5")
    draw.text((307, 144), "BILL 041", font=ImageFont.load_default(size=23), fill="#6b675f", anchor="lm")
    return {name: as_png(image) for name, image in (
        ("second-photo", rotated), ("cropped-number", cropped), ("separate-purchase", separate),
    )}


def as_png(image):
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


@lru_cache(maxsize=2)
def demo_hashes(original):
    return {sha256(data).hexdigest(): name for name, data in {"original": original, **demo_variants(original)}.items()}


def demo_extraction(original, file_hash):
    name = demo_hashes(original).get(file_hash)
    if not name:
        return None
    result = azure_fixture()
    analysis = result["analyzeResult"]
    bill = {"cropped-number": "", "separate-purchase": " / BILL 041"}.get(name, " / BILL 026")
    analysis["content"] = f"THE CAMPUS KITCHEN\n17 NOV 2026{bill}"
    return result


def backfill_demo_identifier(conn):
    """Record the printed number on demo receipts seeded before matching existed."""
    row = conn.execute("SELECT id, extraction_json FROM receipts WHERE file_key = ?", (SAMPLE_KEY,)).fetchone()
    if not row or not row["extraction_json"]:
        return
    extraction = json.loads(row["extraction_json"])
    raw = extraction.get("raw", {})
    if not receipt_number(raw):
        analysis = raw.get("analyzeResult", raw)
        analysis["content"] = "THE CAMPUS KITCHEN\n17 NOV 2026 / BILL 026"
        conn.execute("UPDATE receipts SET extraction_json = ? WHERE id = ?",
                     (json.dumps(extraction, ensure_ascii=False), row["id"]))
