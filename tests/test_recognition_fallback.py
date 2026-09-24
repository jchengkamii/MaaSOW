from __future__ import annotations
import copy
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
import numpy as np

# Direct execution in the native probe puts tests/, not the project root, on sys.path.
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.recognition_fallback import (
    apply_full_image_fallbacks, recognition_candidates, with_full_image_fallback,
)
from agent.custom.action.auto_treatment.auto_treatment import detect_treatment_rows


class RecognitionFallbackTests(unittest.TestCase):
    def test_ocr_keeps_local_mode_but_detects_full_image_text(self):
        original = {"type": "OCR", "param": {"roi": "anchor", "roi_offset": [20, 0, 80, 20],
                    "only_rec": True, "expected": ["[0-9]+:[0-9]+"], "threshold": 0.4}}
        saved = copy.deepcopy(original)
        result = with_full_image_fallback(original)
        local, full = [x["recognition"] for x in result["param"]["any_of"]]
        self.assertEqual(saved, original)
        self.assertEqual(original, local)
        self.assertEqual([0, 0, 0, 0], full["param"]["roi"])
        self.assertEqual([0, 0, 0, 0], full["param"]["roi_offset"])
        self.assertFalse(full["param"]["only_rec"])
        self.assertEqual(original["param"]["expected"], full["param"]["expected"])
        self.assertEqual(original["param"]["threshold"], full["param"]["threshold"])
        self.assertEqual(result, with_full_image_fallback(result))

    def test_already_full_image_and_direct_hit_are_unchanged(self):
        for kind in ("OCR", "TemplateMatch", "DirectHit"):
            node = {"type": kind, "param": {"roi": [0, 0, 0, 0]}}
            self.assertEqual(node, with_full_image_fallback(node))

    def test_ocr_reader_prefers_successful_full_branch(self):
        def leaf(text, hit):
            candidate = SimpleNamespace(text=text)
            return SimpleNamespace(hit=hit, best_result=candidate,
                                   filtered_results=[candidate], all_results=[candidate])
        local, full = leaf("wrong", False), leaf("00:30:00", True)
        combined = SimpleNamespace(sub_results=[local, full])
        detail = SimpleNamespace(best_result=combined, filtered_results=[combined], all_results=[combined])
        self.assertEqual(["00:30:00"], [c.text for c in recognition_candidates(detail)])
        full.hit = False
        self.assertEqual(["wrong", "00:30:00"], [c.text for c in recognition_candidates(detail)])

    def test_python_button_search_falls_back_beyond_original_region(self):
        image = np.zeros((1315, 720, 3), dtype=np.uint8)
        image[1000:1040, 570:600] = (220, 130, 40)
        rows = detect_treatment_rows(image)
        self.assertEqual(1, len(rows))
        self.assertTrue(570 <= rows[0].plus_x < 600)
        self.assertTrue(1000 <= rows[0].y < 1040)

    def test_python_button_search_prefers_local_and_handles_no_match(self):
        image = np.zeros((1315, 720, 3), dtype=np.uint8)
        self.assertEqual([], detect_treatment_rows(image))
        image[1000:1040, 570:600] = (220, 130, 40)
        image[600:640, 490:520] = (220, 130, 40)
        rows = detect_treatment_rows(image)
        self.assertEqual(1, len(rows))
        self.assertTrue(600 <= rows[0].y < 640)

    def test_native_recognition_and_all_project_nodes(self):
        # AgentServer switches the framework library globally in other tests.
        # Use an isolated process to test the real MaaFramework implementation.
        result = subprocess.run([sys.executable, "-X", "utf8", str(Path(__file__).resolve()), "--native-probe"],
                                capture_output=True, encoding="utf-8", timeout=60)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)


def native_probe():
    from maa.resource import Resource
    from maa.tasker import Tasker
    from maa.library import Library
    from maa.pipeline import JRecognitionType, JOr, JAnd
    root = Path(__file__).resolve().parents[1]
    resource = Resource()
    assert resource.post_bundle(root / "resource/base").wait().succeeded
    before = {n: resource.get_node_data(n) for n in resource.node_list}
    assert apply_full_image_fallbacks(resource) > 0
    for name, original in before.items():
        current = resource.get_node_data(name)
        if name.startswith("通用自动补体"):
            assert current == original, name
            continue
        for key, value in original.items():
            if key != "recognition":
                assert current[key] == value, (name, key)
        def audit(rec, inside_fallback=False):
            if rec["type"] in {"And", "Or"}:
                children = rec["param"].get("any_of", rec["param"].get("all_of", []))
                fallback = rec["type"] == "Or" and len(children) == 2 and isinstance(children[0], dict) and children[0].get("sub_name") == "__MaaSOW_roi_first__"
                if fallback:
                    assert children[1]["param"]["roi"] == [0, 0, 0, 0]
                    assert children[1]["param"]["roi_offset"] == [0, 0, 0, 0]
                for child in children:
                    if isinstance(child, dict):
                        audit(child, fallback)
            elif "roi" in rec["param"] and rec["type"] != "DirectHit":
                restricted = rec["param"]["roi"] != [0, 0, 0, 0] or any(rec["param"]["roi_offset"])
                assert not restricted or inside_fallback, name
        audit(current["recognition"])
    tasker = Tasker()
    assert Library.framework().MaaTaskerBindResource(tasker._handle, resource._handle)
    rng = np.random.default_rng(42)
    template = rng.integers(20, 240, (12, 12, 3), dtype=np.uint8)
    resource.override_image("FallbackProbe.png", template)
    rec = with_full_image_fallback({"type": "TemplateMatch", "param": {
        "template": ["FallbackProbe.png"], "threshold": 0.99, "roi": [0, 0, 40, 40]}})
    for local_hit, outside_hit in ((True, True), (False, True), (False, False)):
        image = np.zeros((100, 100, 3), dtype=np.uint8)
        if local_hit: image[10:22, 10:22] = template
        if outside_hit: image[60:72, 70:82] = template
        job = tasker.post_recognition(JRecognitionType.Or, JOr(**rec["param"]), image).wait()
        detail = job.get().nodes[0].recognition
        assert detail.hit == (local_hit or outside_hit), (local_hit, outside_hit, detail)
        if detail.hit:
            assert detail.box.x == (10 if local_hit else 70)
            assert detail.box.y == (10 if local_hit else 60)
        children = detail.all_results[0].sub_results
        assert len(children) == (1 if local_hit else 2), "Full-image search must short-circuit"
    # Compound node references must preserve the hit box for subsequent relative ROIs.
    assert resource.override_pipeline({"ProbeAnchor": {"recognition": rec}})
    dependent = with_full_image_fallback({"type": "ColorMatch", "param": {
        "roi": "ProbeAnchor", "roi_offset": [0, 15, 0, 0],
        "method": 4, "lower": [0, 200, 0], "upper": [0, 255, 0], "count": 10}})
    compound = JAnd(all_of=["ProbeAnchor", {"recognition": dependent}], box_index=1)
    image = np.zeros((100, 100, 3), dtype=np.uint8)
    image[60:72, 70:82] = template
    image[75:87, 70:82] = (0, 255, 0)
    job = tasker.post_recognition(JRecognitionType.And, compound, image).wait()
    assert job.succeeded
    assert job.get().nodes[0].recognition.box.y == 75
    print("Native ROI priority, global match, no match, compound/relative ROI and all-node coverage: PASS")


if __name__ == "__main__":
    if "--native-probe" in sys.argv:
        native_probe()
    else:
        unittest.main()
