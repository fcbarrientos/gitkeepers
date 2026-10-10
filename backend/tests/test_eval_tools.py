import json
import unittest

from core.extraction import build_messages, check_value, parse_and_validate, schema_for
from evals.run_eval import evaluate
from evals.scoring import values_match


class RecordingLLM:
    """Records the note text each extraction call receives."""
    def __init__(self):
        self.notes = []

    def chat_json(self, messages, schema, max_tokens=512):
        self.notes.append(messages[-1]["content"])
        return "{}"


SAMPLE = [{"id": "x1", "note": "Buntis si Maria, 28 weeks. Tawagan sa 09171234567.",
           "expected": {"weeks_pregnant": 28}}]


class PseudonymizeFlagTests(unittest.TestCase):
    def test_notes_are_masked_only_when_asked(self):
        masked = RecordingLLM()
        evaluate(masked, SAMPLE, pseudonymize=True)
        self.assertNotIn("Maria", masked.notes[0])
        self.assertNotIn("09171234567", masked.notes[0])
        self.assertIn("28 weeks", masked.notes[0])
        raw = RecordingLLM()
        evaluate(raw, SAMPLE)
        self.assertIn("Maria", raw.notes[0])


VACCINES = ("BCG", "HepB", "Penta1", "Penta2", "OPV1", "OPV2")
FEEDING = ("exclusive", "partial", "none")
OPTION_FIELDS = {"vaccines_given": ("choices", VACCINES), "breastfeeding": ("choice", FEEDING),
                 "weight_kg": ("number", (0.5, 60))}


class OptionTypeTests(unittest.TestCase):
    def test_choice_values_are_normalized_to_canonical_spelling(self):
        self.assertEqual(check_value("Exclusive", "choice", FEEDING), ("exclusive", None))
        self.assertEqual(check_value(["penta 2", "hepb", "Penta2"], "choices", VACCINES), (["Penta2", "HepB"], None))

    def test_invalid_options_are_rejected_whole(self):
        value, problem = check_value("sometimes", "choice", FEEDING)
        self.assertIsNone(value)
        self.assertIn("one of", problem)
        value, problem = check_value(["BCG", "Rabies"], "choices", VACCINES)
        self.assertIsNone(value)
        self.assertIn("Rabies", problem)
        self.assertEqual(check_value("BCG", "choices", VACCINES)[0], None)  # not a list

    def test_empty_choices_list_means_not_recorded(self):
        self.assertEqual(check_value([], "choices", VACCINES), (None, None))

    def test_schema_uses_enums(self):
        props = schema_for(OPTION_FIELDS)["properties"]
        self.assertEqual(props["breastfeeding"]["enum"], [*FEEDING, None])
        self.assertEqual(props["vaccines_given"]["items"]["enum"], list(VACCINES))
        self.assertEqual(props["weight_kg"], {"type": ["number", "null"]})

    def test_prompt_lists_options_and_uses_the_given_fewshot_file(self):
        shots = [{"note": "BCG given", "fields": {"vaccines_given": ["BCG"], "fever": True}}]
        messages = build_messages("Penta 1 today", OPTION_FIELDS, fewshot=shots, glossary={})
        system = messages[0]["content"]
        self.assertIn("- breastfeeding: one of ['exclusive', 'partial', 'none']", system)
        self.assertIn("- vaccines_given: list of any of", system)
        self.assertEqual(json.loads(messages[2]["content"]), {"vaccines_given": ["BCG"]})  # unknown field dropped

    def test_example_answers_follow_the_schema_field_order(self):
        # The JSON grammar only accepts keys in schema order, so the examples must teach that order.
        shots = [{"note": "Weight 5 kg, BCG given, mixed feeding",
                  "fields": {"breastfeeding": "partial", "weight_kg": 5, "vaccines_given": ["BCG"]}}]
        answer = build_messages("x", OPTION_FIELDS, fewshot=shots, glossary={})[2]["content"]
        self.assertEqual(list(json.loads(answer)), ["vaccines_given", "breastfeeding", "weight_kg"])

    def test_parse_and_validate_handles_option_fields(self):
        r = parse_and_validate('{"vaccines_given": ["OPV 1"], "breastfeeding": "partial"}', OPTION_FIELDS)
        self.assertEqual(r["fields"], {"vaccines_given": ["OPV1"], "breastfeeding": "partial", "weight_kg": None})


class OptionScoringTests(unittest.TestCase):
    def test_strings_and_lists(self):
        self.assertTrue(values_match("partial", "partial"))
        self.assertFalse(values_match("partial", "none"))
        self.assertTrue(values_match(["BCG", "HepB"], ["HepB", "BCG"]))
        self.assertFalse(values_match(["BCG"], ["BCG", "HepB"]))
        self.assertFalse(values_match(["BCG"], "BCG"))
        self.assertTrue(values_match(38, 38.0))  # numbers unchanged
