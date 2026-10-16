# API connections

The application connects directly from your computer to your configured provider.
An API key and a model that supports image editing or image output are required for
AI generation. The optional composition translation uses the selected text model.
Model IDs can be entered manually or retrieved from the provider's model list.
A listed model is not necessarily capable of creating images.

| Setting | OpenAI | OpenAI-compatible service | Google Gemini |
| --- | --- | --- | --- |
| Default API base | `https://api.openai.com/v1` | Enter your service's API base, including `/v1` if required | `https://generativelanguage.googleapis.com/v1beta` |
| Image route | `POST /images/edits` | Same multipart route; the service must support reference-image edits | `POST /models/{model}:generateContent` |
| Image input | Multipart `image[]`, first layout reference then optional fabric reference | Same | Base64 `inlineData` |
| Text route | `POST /chat/completions` | Same | Native `generateContent` |
| Model discovery | `GET /models` | Same, if provided | `GET /models`, including pagination |
| Dimensions | `auto` or a pixel size supported by your model | Provider-specific | `auto`, a supported aspect ratio, or `1K` / `2K` / `4K`; OpenAI pixel dimensions are omitted |
| Quality | Selected quality, if not `auto` | Provider-specific | Omitted; Gemini uses its own model settings |

Use an image-capable model for generation and a text/chat-capable model for the
optional translator. An OpenAI-compatible endpoint alone does not make every model
an image model. Services that expose images only through a proprietary endpoint,
text-to-image generation without editing, or an agent/tool API need another adapter.

## What is sent

For generation, the service receives the layout reference photo, optional fabric
reference, selected English fiber names and percentages, fabric color, and any
regeneration feedback. Words in attached images are treated as reference data.
For translation, only the supplied composition description is sent. Model discovery
sends credentials but no reference photos or composition data.

The image prompt requests the original label placement, perspective, satin texture,
stitching, and a centered composition block above “Made in China”. It removes the
clothing-size line and applies the chosen color to the garment fabric. Generative
models can change spelling, percentages, color, or geometry: inspect each result
in the review screen before approving it. Approval is a human decision.

## Network and error behavior

- Connections require HTTPS; HTTP is permitted only for localhost and loopback IPs.
- Base URLs cannot contain credentials, query parameters, or fragments.
- Requests have a 30-second connection timeout and a 240-second read timeout.
- Each generation attempt sends one billable request. In v1.1 the queue retries
  HTTP 408/429/5xx and transient connection/timeout failures up to 3 attempts total,
  waiting at least 10 seconds after failure and spacing generation starts at least
  10 seconds apart. Configuration/TLS and unexpected errors pause immediately.
  Requests are never routed to another model automatically. Retries and timed-out
  attempts may incur provider charges. Pause suspends retries; Cancel queued cancels
  pending retries. Attempt counts survive reopening; only new versions reset them.
- API redirects are rejected so keys cannot accidentally follow another endpoint.
- Signed image URLs returned by compatible services are fetched without the API key.
  Downloads must use HTTPS (or local HTTP) and return the image directly.
- Source images must be PNG, JPEG, or WebP, smaller than 20 MB each and at most
  40 million pixels. Gemini's combined JSON upload must be smaller than 20 MB.
- Returned files are decoded with Pillow and saved as PNG atomically. An invalid
  response does not replace an existing candidate.
- Errors shown to the interface use status-based messages; response bodies, keys,
  and raw network exceptions are not displayed or logged by the provider module.

## Development verification

Run `python -m unittest discover -s tests -p test_providers.py -v` from the project
directory. Tests mock all network calls and incur no API charges. They verify
multipart reference uploads, Gemini inline image input/output, model selection,
translation percentage preservation, endpoint validation, secret-safe errors,
retry classification without transport-level resubmission, and safe image writes. A paid live API run still requires
the user's own credentials, account access, and a chosen model.

## Official references

The REST adapter follows [OpenAI's image edit reference](https://developers.openai.com/api/reference/python/resources/images/methods/edit)
and [image generation guide](https://developers.openai.com/api/docs/guides/image-generation).
Gemini's native payload and output parsing follow its [generateContent API reference](https://ai.google.dev/api/generate-content),
with [model discovery](https://ai.google.dev/api/models). Google also provides an
[image generation guide](https://ai.google.dev/gemini-api/docs/image-generation),
whose current examples use the separate Interactions API. This application uses
the documented `generateContent` adapter.

Reference check date: 2026-09-15. Model access, prices, and supported dimensions
are controlled by each provider; the application makes no availability guarantee.
