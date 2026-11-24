import random
import re

import datasets

LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _norm(text):
    return re.sub(r"\W+", " ", text.lower()).strip()


def process_docs(dataset):
    """Lay each question out as lettered multiple choice.

    TruthfulQA lists the single true answer first, so the options are shuffled (seeded by the question's
    position, so every run sees the same order). The question's category and adversarial/non-adversarial
    type live in the dataset's other config; they are joined in by question text for the dashboard.
    """
    try:
        gen = datasets.load_dataset("truthfulqa/truthful_qa", "generation", split="validation")
        meta = {_norm(r["question"]): (r["category"], r["type"]) for r in gen}
    except Exception:  # the breakdown is optional; the benchmark itself does not need it
        meta = {}

    def fmt(doc, idx):
        choices = doc["mc1_targets"]["choices"]
        labels = doc["mc1_targets"]["labels"]
        order = list(range(len(choices)))
        random.Random(idx).shuffle(order)
        letters = LETTERS[: len(choices)]
        options = "\n".join(f"{letters[i]}. {choices[j]}" for i, j in enumerate(order))
        target = letters[next(i for i, j in enumerate(order) if labels[j] == 1)]
        category, qtype = meta.get(_norm(doc["question"]), ("Unknown", "Unknown"))
        return {"options": options, "target_letter": target, "n_options": len(choices),
                "category": category, "qtype": qtype}

    return dataset.map(fmt, with_indices=True)
