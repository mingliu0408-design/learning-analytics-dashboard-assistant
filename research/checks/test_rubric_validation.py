"""Synthetic validator fixtures only; not human evaluation or study scores."""
import copy
import unittest
from rubric.rating_validation import CRITERIA, validate_ratings


class RatingValidationFixtures(unittest.TestCase):
    def fixture(self):
        item = {'item_id': 'synthetic_item', 'response': 'Synthetic fixture response.',
                'applicability': {c: {'applicable': c == 'CLARITY'} for c in CRITERIA}}
        rows = [{'item_id': 'synthetic_item', 'rater_id': 'synthetic_rater',
                 'criterion_id': c, 'score': 3 if c == 'CLARITY' else 'NA',
                 'note': '', 'applicability_dispute': '',
                 'recorded_at': '2000-01-01T00:00:00+00:00'} for c in CRITERIA]
        return [item], rows

    def test_synthetic_complete_record(self):
        items, rows = self.fixture()
        self.assertEqual(validate_ratings(rows, items, complete=True), [])

    def test_blank_is_not_zero_or_silently_omitted(self):
        items, rows = self.fixture()
        rows[0]['score'] = None
        self.assertIn('missing score; never silently omitted from denominator',
                      validate_ratings(rows, items, complete=True))

    def test_fixed_NA_and_numeric_positions_cannot_swap(self):
        items, rows = self.fixture()
        rows[0]['score'], rows[1]['score'] = 'NA', 3
        errors = validate_ratings(rows, items, complete=True)
        self.assertIn('applicable criterion cannot be NA', errors)
        self.assertIn('inapplicable criterion requires human-entered NA', errors)

    def test_missing_and_duplicate_identity_positions_fail(self):
        items, rows = self.fixture()
        self.assertIn('missing rater/item/criterion row', validate_ratings(rows[:-1], items, complete=True))
        rows.append(copy.deepcopy(rows[0]))
        self.assertIn('duplicate rater/item/criterion row', validate_ratings(rows, items, complete=True))


if __name__ == '__main__':
    unittest.main()
