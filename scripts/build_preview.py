"""Export fresh offline synthetic examples for the static HR tour; no model call."""
from pathlib import Path
import json
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from demo.core import DemoAssistant
from demo.data import PAGES, SAMPLE_QUESTIONS


def main():
    with tempfile.TemporaryDirectory(prefix="lad-public-preview-") as directory:
        engine = DemoAssistant(Path(directory) / "synthetic.sqlite")
        engine.memory_write("我希望练习有证据的学习反思。My learning goal is evidence-based reflection.", consent=True)
        engine.memory_write("每次学习不超过30分钟。My study time budget is 30 minutes.", "CONSTRAINT", consent=True)
        export = {"origin":"NEW_PUBLIC_DEMO_SYNTHETIC_OFFLINE_EXPORT_NOT_STUDY_RESULTS", "snapshots":{}, "examples":[]}
        for page in PAGES:
            export["snapshots"][page] = engine.snapshot(page)
            for question in SAMPLE_QUESTIONS[page]:
                result = engine.answer(question, page=page, online=False)
                export["examples"].append({"page":page, "question":question, "result":result})
        (ROOT / "docs" / "preview.json").write_text(json.dumps(export, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"pages":len(PAGES), "offline_examples":len(export["examples"]), "model_calls":0}))


if __name__ == "__main__":
    main()

