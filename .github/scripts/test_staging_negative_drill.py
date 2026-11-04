"""Temporary negative probe. Never merge this test branch."""
import unittest


class NegativeDrill(unittest.TestCase):
    def test_intentional_product_ci_failure(self):
        self.fail("MEG-204 intentional failure; do not merge")
