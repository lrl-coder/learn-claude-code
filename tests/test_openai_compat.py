import json
import types
import unittest

from openai_compat import OpenAICompat


class FakeResponses:
    def __init__(self, response):
        self.response = response
        self.request = None

    def create(self, **kwargs):
        self.request = kwargs
        return self.response


class OpenAICompatTests(unittest.TestCase):
    def test_translates_tools_and_tool_results(self):
        response = types.SimpleNamespace(
            id="resp_1",
            output=[
                types.SimpleNamespace(
                    type="function_call",
                    call_id="call_1",
                    name="bash",
                    arguments=json.dumps({"command": "pwd"}),
                )
            ],
            usage=types.SimpleNamespace(input_tokens=12, output_tokens=4),
            incomplete_details=None,
        )
        responses = FakeResponses(response)
        sdk = types.SimpleNamespace(responses=responses)
        client = OpenAICompat(client=sdk)

        result = client.messages.create(
            model="test-model",
            system="Be useful.",
            messages=[
                {"role": "user", "content": "Run pwd"},
                {"role": "assistant", "content": [
                    {"type": "tool_use", "id": "old_call", "name": "bash",
                     "input": {"command": "echo hi"}}
                ]},
                {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": "old_call",
                     "content": "hi"}
                ]},
            ],
            tools=[{
                "name": "bash",
                "description": "Run a command",
                "input_schema": {"type": "object", "properties": {}},
            }],
            max_tokens=8000,
        )

        self.assertEqual(result.stop_reason, "tool_use")
        self.assertEqual(result.content[0].name, "bash")
        self.assertEqual(result.content[0].input, {"command": "pwd"})
        self.assertEqual(responses.request["instructions"], "Be useful.")
        self.assertEqual(responses.request["max_output_tokens"], 8000)
        self.assertEqual(responses.request["tools"][0]["type"], "function")
        self.assertEqual(
            responses.request["input"][-1],
            {"type": "function_call_output", "call_id": "old_call", "output": "hi"},
        )

    def test_maps_text_usage_and_max_tokens(self):
        response = types.SimpleNamespace(
            id="resp_2",
            output=[types.SimpleNamespace(
                type="message",
                content=[types.SimpleNamespace(type="output_text", text="done")],
            )],
            usage=types.SimpleNamespace(
                input_tokens=10,
                output_tokens=5,
                input_tokens_details=types.SimpleNamespace(cached_tokens=3),
            ),
            incomplete_details=types.SimpleNamespace(reason="max_output_tokens"),
        )
        sdk = types.SimpleNamespace(responses=FakeResponses(response))

        result = OpenAICompat(client=sdk).messages.create(
            model="test-model", messages=[{"role": "user", "content": "hi"}],
            max_tokens=20,
        )

        self.assertEqual(result.stop_reason, "max_tokens")
        self.assertEqual(result.content[0].text, "done")
        self.assertEqual(result.usage.input_tokens, 10)
        self.assertEqual(result.usage.cache_read_input_tokens, 3)

    def test_replays_reasoning_items_before_tool_results(self):
        reasoning = types.SimpleNamespace(type="reasoning", id="rs_1")
        first_response = types.SimpleNamespace(
            id="resp_3",
            output=[
                reasoning,
                types.SimpleNamespace(
                    type="function_call",
                    call_id="call_2",
                    name="bash",
                    arguments='{"command":"pwd"}',
                ),
            ],
            usage=None,
            incomplete_details=None,
        )
        responses = FakeResponses(first_response)
        client = OpenAICompat(client=types.SimpleNamespace(responses=responses))
        first = client.messages.create(
            model="test-model",
            messages=[{"role": "user", "content": "pwd"}],
            tools=[{"name": "bash", "input_schema": {"type": "object"}}],
            max_tokens=20,
        )

        responses.response = types.SimpleNamespace(
            id="resp_4", output=[], usage=None, incomplete_details=None
        )
        client.messages.create(
            model="test-model",
            messages=[
                {"role": "user", "content": "pwd"},
                {"role": "assistant", "content": first.content},
                {"role": "user", "content": [{
                    "type": "tool_result", "tool_use_id": "call_2", "content": "/tmp"
                }]},
            ],
            tools=[{"name": "bash", "input_schema": {"type": "object"}}],
            max_tokens=20,
        )

        replay = responses.request["input"]
        self.assertIs(replay[1], reasoning)
        self.assertEqual(replay[2]["type"], "function_call")
        self.assertEqual(replay[3]["type"], "function_call_output")


if __name__ == "__main__":
    unittest.main()
