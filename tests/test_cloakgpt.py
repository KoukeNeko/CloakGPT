import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

import cloakgpt


class CloakGPTCliTests(unittest.TestCase):
    @patch("cloakgpt.start_conversation", return_value="First answer")
    def test_ask_command(self, start_conversation) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            result = cloakgpt.main(
                ["ask", "Hello", "--reasoning", "high", "--timezone", "Asia/Taipei"]
            )

        self.assertEqual(result, 0)
        self.assertEqual(output.getvalue().strip(), "First answer")
        start_conversation.assert_called_once_with(
            "Hello",
            timezone="Asia/Taipei",
            timeout_seconds=120,
            reasoning_level="high",
        )

    @patch("cloakgpt.continue_conversation", return_value="Next answer")
    def test_continue_command(self, continue_conversation) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            result = cloakgpt.main(["continue", "More details"])

        self.assertEqual(result, 0)
        self.assertEqual(output.getvalue().strip(), "Next answer")
        continue_conversation.assert_called_once_with(
            "More details",
            timezone="Asia/Taipei",
            timeout_seconds=120,
            reasoning_level=None,
        )

    @patch("cloakgpt.start_conversation", side_effect=ValueError("not available"))
    def test_errors_are_reported_without_traceback(self, _start_conversation) -> None:
        errors = io.StringIO()
        with redirect_stderr(errors):
            result = cloakgpt.main(["ask", "Hello"])

        self.assertEqual(result, 1)
        self.assertEqual(errors.getvalue().strip(), "error: not available")


if __name__ == "__main__":
    unittest.main()
