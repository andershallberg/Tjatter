from __future__ import annotations

import unittest

from tjatter import ChatMessage, _read_reply, create_chat_completions_url


class EndpointTests(unittest.TestCase):
    def test_project_endpoint_maps_to_chat_completions_route(self) -> None:
        self.assertEqual(
            create_chat_completions_url(
                "https://example.services.ai.azure.com/api/projects/my-project/"
            ),
            "https://example.services.ai.azure.com/openai/v1/chat/completions",
        )

    def test_rejects_non_azure_hosts(self) -> None:
        with self.assertRaisesRegex(ValueError, "Foundry resource"):
            create_chat_completions_url("https://example.com/api/projects/my-project")

    def test_rejects_invalid_project_endpoint_shape(self) -> None:
        with self.assertRaisesRegex(ValueError, "project endpoint format"):
            create_chat_completions_url(
                "https://example.services.ai.azure.com/not-a-project"
            )

    def test_rejects_credentials_and_non_https(self) -> None:
        for endpoint in (
            "http://example.services.ai.azure.com/api/projects/my-project",
            "https://user:secret@example.services.ai.azure.com/api/projects/my-project",
        ):
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(ValueError):
                    create_chat_completions_url(endpoint)


class ResponseTests(unittest.TestCase):
    def test_reads_text_response(self) -> None:
        self.assertEqual(
            _read_reply({"choices": [{"message": {"content": "Hello"}}]}),
            "Hello",
        )

    def test_reads_text_parts_response(self) -> None:
        self.assertEqual(
            _read_reply(
                {
                    "choices": [
                        {
                            "message": {
                                "content": [
                                    {"type": "text", "text": "Hello"},
                                    {"type": "text", "text": "there"},
                                ]
                            }
                        }
                    ]
                }
            ),
            "Hello\nthere",
        )

    def test_rejects_response_without_assistant_text(self) -> None:
        with self.assertRaisesRegex(ValueError, "without any assistant text"):
            _read_reply({"choices": []})


if __name__ == "__main__":
    unittest.main()
