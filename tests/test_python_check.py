"""The CLI refuses to run on an interpreter older than the code needs."""

import unittest

from tournament.cli import MIN_PYTHON, python_problem


class TestPythonCheck(unittest.TestCase):
    def test_current_interpreter_is_fine(self):
        self.assertIsNone(python_problem())

    def test_exactly_the_minimum_is_fine(self):
        self.assertIsNone(python_problem((MIN_PYTHON[0], MIN_PYTHON[1], 0)))

    def test_older_interpreter_explains_what_to_do(self):
        message = python_problem((3, 9, 7))
        self.assertIsNotNone(message)
        self.assertIn("Python 3.9.7", message)
        self.assertIn(".".join(str(p) for p in MIN_PYTHON), message)
        self.assertIn("python.org", message)


if __name__ == "__main__":
    unittest.main()
