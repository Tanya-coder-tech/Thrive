"""Score saved receipt extraction responses against a JSON Lines label manifest."""

from argparse import ArgumentParser
from collections import defaultdict, deque
from dataclasses import dataclass, field
import json
from pathlib import Path
from unicodedata import normalize as unicode_normalize

from receipt_extraction import ScanError, normalize_extraction


def text(value):
    return " ".join(unicode_normalize("NFKC", value or "").casefold().split())


@dataclass
class Score:
    matched: int = 0
    labeled: int = 0

    def add(self, ok):
        self.labeled += 1
        self.matched += bool(ok)
        return bool(ok)

    def report(self):
        return dict(matched=self.matched, labeled=self.labeled,
                    percent=round(100 * self.matched / self.labeled, 2) if self.labeled else None)


@dataclass
class Evaluation:
    merchant: Score = field(default_factory=Score)
    purchase_date: Score = field(default_factory=Score)
    total: Score = field(default_factory=Score)
    item_coverage: Score = field(default_factory=Score)
    matched_item_amounts: Score = field(default_factory=Score)
    manual_correction: Score = field(default_factory=Score)

    def record(self, expected, draft, uncertain):
        needs_review = bool(uncertain) or draft is None
        extracted = draft or {}
        for key, metric, normalizer in (
            ("merchant", self.merchant, text),
            ("purchase_date", self.purchase_date, str),
            ("total_paise", self.total, lambda value: value),
        ):
            if expected.get(key) is not None:
                equal = extracted.get(key) is not None and normalizer(expected[key]) == normalizer(extracted[key])
                needs_review |= not metric.add(equal)

        if "items" in expected:
            found = defaultdict(deque)
            for item in extracted.get("items", []):
                found[text(item["description"])].append(item["amount_paise"])
            for item in expected["items"]:
                candidates = found[text(item["description"])]
                if self.item_coverage.add(bool(candidates)):
                    equal = candidates.popleft() == item["amount_paise"]
                    needs_review |= not self.matched_item_amounts.add(equal)
                else:
                    needs_review = True
            needs_review |= any(found.values())
        self.manual_correction.add(needs_review)

    def report(self):
        return dict(receipts=self.manual_correction.labeled,
                    **{key: value.report() for key, value in vars(self).items()})


def evaluate(manifest):
    results = defaultdict(Evaluation)
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        extraction = json.loads((manifest.parent / entry["response"]).read_text(encoding="utf-8"))
        try:
            draft, uncertain = normalize_extraction(extraction, 1, [1], currency_code=entry.get("currency", "INR"))
        except ScanError:
            draft, uncertain = None, []
        results[entry["dataset"]].record(entry["expected"], draft, uncertain)
    return {dataset: score.report() for dataset, score in results.items()}


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    arguments = parser.parse_args()
    print(json.dumps(evaluate(arguments.manifest), indent=2, ensure_ascii=False))
