import json
import unittest
from pathlib import Path

from core import i18n
from core.extraction import PRENATAL_FIELDS, build_messages, extract, parse_and_validate, strip_think
from evals.run_eval import evaluate, load_samples
from evals.scoring import score_sample, values_match


class FakeLLM:
    """Stands in for the real model so the logic can be tested without a download."""
    def __init__(self, reply):
        self.reply = reply

    def chat_json(self, messages, schema, max_tokens=512):
        return self.reply(messages) if callable(self.reply) else self.reply


class OracleLLM:
    """Returns the expected answer for each sample, looked up by note text."""
    def __init__(self, samples, wrong_for=()):
        self.by_note = {s["note"]: s for s in samples}
        self.wrong_for = set(wrong_for)

    def chat_json(self, messages, schema, max_tokens=512):
        note = messages[-1]["content"].replace(" /no_think", "")
        s = self.by_note[note]
        out = {k: s["expected"].get(k) for k in PRENATAL_FIELDS}
        if s["id"] in self.wrong_for:
            out["bleeding"] = not bool(out["bleeding"])
        return json.dumps(out)


class ParsingTests(unittest.TestCase):
    def test_good_json(self):
        r = parse_and_validate('{"weeks_pregnant": 28, "fever": false}')
        self.assertTrue(r["ok"])
        self.assertEqual(r["fields"]["weeks_pregnant"], 28)
        self.assertIs(r["fields"]["fever"], False)
        self.assertIsNone(r["fields"]["bleeding"])
        self.assertEqual(r["problems"], [])

    def test_think_tags_stripped(self):
        self.assertEqual(strip_think("<think>\n\n</think>\n{\"a\": 1}"), '{"a": 1}')
        r = parse_and_validate('<think>hmm</think>{"bleeding": true}')
        self.assertIs(r["fields"]["bleeding"], True)

    def test_json_inside_text(self):
        r = parse_and_validate('Here you go: {"headache": true} thanks')
        self.assertTrue(r["ok"])
        self.assertIs(r["fields"]["headache"], True)

    def test_invalid_output(self):
        r = parse_and_validate("sorry, I can't")
        self.assertFalse(r["ok"])
        self.assertTrue(all(v is None for v in r["fields"].values()))

    def test_out_of_range_becomes_none(self):
        r = parse_and_validate('{"bp_systolic": 1400, "bp_diastolic": 90}')
        self.assertIsNone(r["fields"]["bp_systolic"])
        self.assertEqual(r["fields"]["bp_diastolic"], 90)
        self.assertTrue(any("bp_systolic" in p for p in r["problems"]))

    def test_wrong_types_rejected(self):
        r = parse_and_validate('{"fever": "yes", "weeks_pregnant": true, "temperature_c": "38"}')
        self.assertIsNone(r["fields"]["fever"])
        self.assertIsNone(r["fields"]["weeks_pregnant"])
        self.assertIsNone(r["fields"]["temperature_c"])
        self.assertEqual(len(r["problems"]), 3)

    def test_float_that_is_whole_accepted_for_integer(self):
        self.assertEqual(parse_and_validate('{"weeks_pregnant": 28.0}')["fields"]["weeks_pregnant"], 28)
        self.assertIsNone(parse_and_validate('{"weeks_pregnant": 28.5}')["fields"]["weeks_pregnant"])

    def test_unknown_key_ignored(self):
        r = parse_and_validate('{"fever": true, "diagnosis": "flu"}')
        self.assertNotIn("diagnosis", r["fields"])
        self.assertTrue(any("diagnosis" in p for p in r["problems"]))


class PromptTests(unittest.TestCase):
    def test_messages_shape(self):
        m = build_messages("Buntis po si Ana")
        self.assertEqual(m[0]["role"], "system")
        self.assertIn("lagnat = fever", m[0]["content"])
        self.assertIn("Available fields:", m[0]["content"])
        self.assertEqual(m[-1], {"role": "user", "content": "Buntis po si Ana /no_think"})
        n_shots = len(json.loads((Path(__file__).resolve().parent.parent / "prompts/prenatal_fewshot.json").read_text(encoding="utf-8")))
        self.assertEqual(len(m), 1 + n_shots * 2 + 1)   # system + (user, assistant) per example + final user turn
        answer = json.loads(m[2]["content"])
        self.assertTrue(all(k in PRENATAL_FIELDS for k in answer))
        self.assertTrue(len(answer) > 0)

    def test_fewshot_not_in_eval_samples(self):
        root = Path(__file__).resolve().parent.parent
        shots = {e["note"] for e in json.loads((root / "prompts/prenatal_fewshot.json").read_text(encoding="utf-8"))}
        samples = {s["note"] for s in load_samples(root / "evals/samples.jsonl")}
        self.assertEqual(shots & samples, set())

    def test_extract_end_to_end_with_fake(self):
        r = extract(FakeLLM('{"fever": true}'), "May lagnat")
        self.assertIs(r["fields"]["fever"], True)


class ScoringTests(unittest.TestCase):
    def test_values_match(self):
        self.assertTrue(values_match(38.5, 38.5))
        self.assertTrue(values_match(None, None))
        self.assertFalse(values_match(None, False))
        self.assertFalse(values_match(False, None))
        self.assertFalse(values_match(True, False))
        self.assertTrue(values_match(38, 38.0))

    def test_missing_expected_means_none(self):
        c = score_sample({"fever": True}, {"fever": True, "bleeding": True}, ["fever", "bleeding"])
        self.assertTrue(c["fever"])
        self.assertFalse(c["bleeding"])      # model reported bleeding that was never mentioned

    def test_evaluate_perfect_and_imperfect(self):
        samples = load_samples(Path(__file__).resolve().parent.parent / "evals/samples.jsonl")
        self.assertGreaterEqual(len(samples), 10)
        perfect = evaluate(OracleLLM(samples), samples)["summary"]
        self.assertEqual(perfect["overall"], 1.0)
        self.assertEqual(perfect["exact_match"], 1.0)
        self.assertEqual(perfect["parse_fail"], 0.0)
        flawed = evaluate(OracleLLM(samples, wrong_for=["s01", "s02"]), samples)["summary"]
        self.assertAlmostEqual(flawed["exact_match"], (len(samples) - 2) / len(samples))
        self.assertLess(flawed["field_accuracy"]["bleeding"], 1.0)

    def test_parse_failures_counted(self):
        samples = load_samples(Path(__file__).resolve().parent.parent / "evals/samples.jsonl")[:4]
        s = evaluate(FakeLLM("nonsense"), samples)["summary"]
        self.assertEqual(s["parse_fail"], 1.0)


class I18nTests(unittest.TestCase):
    def test_translation_and_fallback(self):
        self.assertEqual(i18n.t("prenatal.fever", "fil"), "Lagnat")
        self.assertEqual(i18n.t("prenatal.fever", "en"), "Fever")
        self.assertEqual(i18n.t("prenatal.fever", "ceb"), "Fever")      # unknown language -> English
        self.assertEqual(i18n.t("no.such.key", "fil"), "no.such.key")

    def test_review_flag(self):
        self.assertTrue(i18n.is_reviewed("en"))
        self.assertTrue(i18n.is_reviewed("fil"))

    def test_fil_has_every_english_key(self):
        en = {k for k in i18n._load("en") if not k.startswith("_")}
        fil = {k for k in i18n._load("fil") if not k.startswith("_")}
        self.assertEqual(en - fil, set())


if __name__ == "__main__":
    unittest.main()
