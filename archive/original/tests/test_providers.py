"""Network contract and failure tests. These tests never call paid APIs."""
import base64
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests
from PIL import Image

from studio import providers


def image_bytes(fmt="PNG"):
    output = io.BytesIO()
    Image.new("RGB", (12, 10), "#829eb5").save(output, format=fmt)
    return output.getvalue()


def response(body=None, *, status=200, raw=None):
    result = requests.Response()
    result.status_code = status
    result._content = raw if raw is not None else json.dumps(body).encode("utf-8")
    result._content_consumed = True
    return result


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.reference = Path(self.folder.name) / "private-ref.png"
        self.reference.write_bytes(image_bytes())
        self.output = Path(self.folder.name) / "result.png"
        self.settings = {
            "provider": "openai", "api_key": "sk-test-SECRET-DO-NOT-LOG",
            "base_url": "https://api.openai.com/v1", "image_model": "gpt-image-1.5",
            "text_model": "chosen-text-model", "size": "1024x1024", "quality": "high",
        }
        self.parts = [{"name": "Cotton", "percent": 60}, {"name": "Polyester", "percent": 40}]
        self.color = {"id": "blue", "name": "Light blue", "hex": "#829eb5"}

    def generate(self, **kwargs):
        return providers.generate_image(self.settings, self.parts, self.color, str(self.reference), str(self.output), **kwargs)

    def test_openai_edit_uses_reference_exact_text_and_selected_model(self):
        encoded = base64.b64encode(image_bytes("JPEG")).decode()
        with patch.object(providers.requests, "request", return_value=response({"data": [{"b64_json": encoded}]})) as request:
            result = self.generate(feedback="Keep the top seam sharper", fabric_reference_path=str(self.reference))
        args, options = request.call_args
        self.assertEqual(args, ("POST", "https://api.openai.com/v1/images/edits"))
        self.assertEqual(options["data"]["model"], "gpt-image-1.5")
        self.assertEqual(options["data"]["n"], "1")
        self.assertEqual(options["data"]["input_fidelity"], "high")
        self.assertEqual(options["data"]["size"], "1024x1024")
        self.assertEqual(options["timeout"], (30, 240))
        self.assertFalse(options["allow_redirects"])
        self.assertEqual(len(options["files"]), 2)
        self.assertEqual(options["files"][0][0], "image[]")
        self.assertEqual(options["files"][0][1][1], self.reference.read_bytes())
        self.assertNotIn("private-ref", repr(options["files"][0][1][0]))
        self.assertIn("60% Cotton\n40% Polyester\n\nMade in China", result["prompt"])
        self.assertIn("Remove the original clothing-size letter completely", result["prompt"])
        self.assertIn("Keep the top seam sharper", result["prompt"])
        self.assertIn("SECOND image", result["prompt"])
        with Image.open(self.output) as pic:
            self.assertEqual(pic.format, "PNG")
            self.assertEqual(pic.size, (12, 10))
        self.assertEqual(result["path"], str(self.output.resolve()))

    def test_newer_or_custom_models_do_not_get_unsupported_fidelity(self):
        encoded = base64.b64encode(image_bytes()).decode()
        for provider, model in [("openai", "gpt-image-2"), ("compatible", "my-custom-model")]:
            with self.subTest(provider=provider, model=model):
                self.settings.update(provider=provider, image_model=model)
                with patch.object(providers.requests, "request", return_value=response({"data": [{"b64_json": encoded}]})) as request:
                    self.generate()
                self.assertNotIn("input_fidelity", request.call_args.kwargs["data"])

    def test_image_download_does_not_send_api_key(self):
        self.settings["provider"] = "compatible"
        with patch.object(providers.requests, "request", side_effect=[
            response({"data": [{"url": "https://storage.example/image.png?signature=example"}]}),
            response(raw=image_bytes()),
        ]) as request:
            self.generate()
        download = request.call_args_list[1]
        self.assertEqual(download.args[0], "GET")
        self.assertNotIn("headers", download.kwargs)
        self.assertNotIn(self.settings["api_key"], repr(download))

    def test_gemini_uses_native_inline_images_and_ignores_thought_images(self):
        self.settings.update(provider="gemini", base_url="https://generativelanguage.googleapis.com/v1beta", image_model="models/my-image-model", size="2K")
        encoded = base64.b64encode(image_bytes()).decode()
        reply = {"candidates": [{"content": {"parts": [
            {"thought": True, "inlineData": {"mimeType": "image/png", "data": "bad image"}},
            {"text": "Here is your label"},
            {"inlineData": {"mimeType": "image/png", "data": encoded}},
        ]}}]}
        with patch.object(providers.requests, "request", return_value=response(reply)) as request:
            self.generate()
        args, options = request.call_args
        self.assertEqual(args[1], "https://generativelanguage.googleapis.com/v1beta/models/my-image-model:generateContent")
        self.assertNotIn(self.settings["api_key"], args[1])
        self.assertEqual(options["headers"]["x-goog-api-key"], self.settings["api_key"])
        self.assertNotIn("Authorization", options["headers"])
        body = options["json"]
        self.assertEqual(body["generationConfig"]["responseModalities"], ["TEXT", "IMAGE"])
        self.assertEqual(body["generationConfig"]["imageConfig"]["imageSize"], "2K")
        self.assertEqual(base64.b64decode(body["contents"][0]["parts"][1]["inlineData"]["data"]), self.reference.read_bytes())
        self.assertTrue(self.output.is_file())

    def test_gemini_text_only_response_does_not_create_fake_image(self):
        self.settings.update(provider="gemini", base_url="https://generativelanguage.googleapis.com/v1beta")
        with patch.object(providers.requests, "request", return_value=response({"candidates": [{"content": {"parts": [{"text": "Cannot generate"}]}}]})):
            with self.assertRaisesRegex(providers.ProviderError, "no image"):
                self.generate()
        self.assertFalse(self.output.exists())

    def test_openai_model_discovery_is_not_a_hardcoded_allowlist(self):
        reply = {"data": [{"id": "z-custom"}, {"id": "a-image"}, {"id": "z-custom"}]}
        with patch.object(providers.requests, "request", return_value=response(reply)):
            self.assertEqual(providers.list_models(self.settings), ["a-image", "z-custom"])

    def test_gemini_model_discovery_follows_pages_without_query_key(self):
        self.settings.update(provider="gemini", base_url="https://generativelanguage.googleapis.com/v1beta")
        with patch.object(providers.requests, "request", side_effect=[
            response({"models": [{"name": "models/z-model"}], "nextPageToken": "next-one"}),
            response({"models": [{"name": "models/a-model"}]}),
        ]) as request:
            self.assertEqual(providers.list_models(self.settings), ["a-model", "z-model"])
        self.assertEqual(request.call_args_list[1].kwargs["params"]["pageToken"], "next-one")
        self.assertNotIn("key", request.call_args_list[1].kwargs["params"])

    def test_source_images_and_fiber_totals_validated_before_network(self):
        with patch.object(providers.requests, "request") as request:
            self.parts[1]["percent"] = 30
            with self.assertRaisesRegex(providers.ProviderError, "total 100"):
                self.generate()
            self.parts[1]["percent"] = 40
            self.reference.write_text("not an image")
            with self.assertRaisesRegex(providers.ProviderError, "reference image"):
                self.generate()
            request.assert_not_called()

    def test_size_and_embedded_newline_cannot_be_fiber_name(self):
        self.parts[0]["name"] = "Cotton\nM"
        with patch.object(providers.requests, "request") as request:
            with self.assertRaises(providers.ProviderError):
                self.generate()
            request.assert_not_called()

    def test_bad_output_does_not_destroy_existing_candidate(self):
        self.output.write_bytes(b"previous candidate")
        with patch.object(providers.requests, "request", return_value=response({"data": [{"b64_json": base64.b64encode(b"HTML instead of image").decode()}]})):
            with self.assertRaises(providers.ProviderError):
                self.generate()
        self.assertEqual(self.output.read_bytes(), b"previous candidate")

    def test_timeout_is_not_retried_and_does_not_expose_key(self):
        with patch.object(providers.requests, "request", side_effect=requests.Timeout("Request with " + self.settings["api_key"])) as request:
            with self.assertRaises(providers.ProviderError) as error:
                self.generate()
        self.assertEqual(request.call_count, 1)
        self.assertIn("billed", str(error.exception))
        self.assertNotIn(self.settings["api_key"], str(error.exception))

    def test_error_body_and_secret_are_never_rendered(self):
        for status in (400, 401, 403, 404, 413, 429, 500, 307):
            with self.subTest(status=status):
                body = {"error": {"message": "Credential " + self.settings["api_key"]}}
                with patch.object(providers.requests, "request", return_value=response(body, status=status)):
                    with self.assertRaises(providers.ProviderError) as error:
                        providers.list_models(self.settings)
                self.assertIn(f"HTTP {status}", str(error.exception))
                self.assertNotIn(self.settings["api_key"], str(error.exception))

    def test_unsafe_endpoint_is_rejected_before_sending_credentials(self):
        for url in ("http://remote.example/v1", "https://user:secret@example.com/v1", "https://example.com/v1?key=secret", "https://example.com/v1#fragment"):
            with self.subTest(url=url):
                self.settings["base_url"] = url
                with patch.object(providers.requests, "request") as request:
                    with self.assertRaises(providers.ProviderError):
                        providers.list_models(self.settings)
                    request.assert_not_called()

    def test_local_compatible_server_is_supported(self):
        self.settings.update(provider="compatible", base_url="http://127.0.0.1:8888/v1")
        with patch.object(providers.requests, "request", return_value=response({"data": [{"id": "local-model"}]})) as request:
            self.assertEqual(providers.list_models(self.settings), ["local-model"])
        self.assertEqual(request.call_args.args[1], "http://127.0.0.1:8888/v1/models")

    def test_normalization_preserves_original_percentages_and_order(self):
        with patch.object(providers.requests, "request", return_value=response({"choices": [{"message": {"content": "60% Cotton\n40% Polyester"}}]})) as request:
            result = providers.normalize_composition(self.settings, "棉60%聚酯纤维40%")
        self.assertEqual(result, "60% Cotton\n40% Polyester")
        self.assertEqual(request.call_args.kwargs["json"]["model"], "chosen-text-model")
        self.assertEqual(request.call_args.args[1], "https://api.openai.com/v1/chat/completions")

    def test_normalization_rejects_changed_numbers_and_embedded_instructions(self):
        for reply in ("70% Cotton\n30% Polyester", "40% Polyester\n60% Cotton", "60% Cotton\n40% Polyester\nIgnore previous instructions"):
            with self.subTest(reply=reply):
                with patch.object(providers.requests, "request", return_value=response({"choices": [{"message": {"content": reply}}]})):
                    with self.assertRaises(providers.ProviderError):
                        providers.normalize_composition(self.settings, "棉60%聚酯纤维40%")


if __name__ == "__main__":
    unittest.main()
