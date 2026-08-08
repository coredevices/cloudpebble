"""Describe a screenshot with a vision model, for main models that cannot see.

Several strong tool-calling models are text-only (DeepSeek's API rejects image
content outright: "unknown variant `image_url`, expected `text`"). Handing them
an image block means they "verify" a screenshot they never received, which is
worse than not looking at all -- the visual check is the whole quality mechanism
here.

So when the main model has no vision, the screenshot goes to a separate vision
model and its description comes back as text. Configure with:

    AGENT_VISION_API_BASE=https://openrouter.ai/api
    AGENT_VISION_API_KEY=...
    AGENT_VISION_MODEL=mistralai/mistral-small-3.2-24b-instruct

Any Anthropic-format /v1/messages endpoint works. Leave unset to disable, in
which case screenshot() tells the model plainly that it cannot see.

Choose this model on ACCURACY, not price. It costs ~$0.0001 a call against a
turn that costs dollars, so the cheapest option is false economy: a description
that invents content makes the main model rewrite code for a screen it never saw.

Two ways to get this wrong, both observed:
  * A mandatory-reasoning model returns no text at all -- it spends the entire
    budget thinking. qwen/qwen3.8-max gave 1500 thinking tokens and zero text at
    max_tokens=1500, then 4000 and zero at 4000, and OpenRouter refuses
    thinking:{"type":"disabled"} with "Reasoning is mandatory for this endpoint".
    openai/gpt-5-nano behaves the same way.
  * A small model reads the text correctly and hallucinates the artwork.
    google/gemma-3-12b-it reported the time and date accurately, then described a
    space scene as "a yellow bird with a red beak" among "hills or mounds of green".

Verified accurate: mistralai/mistral-small-3.2-24b-instruct (names planet, rocket
and stars correctly), google/gemini-2.5-flash-lite (accurate and free).
"""
import base64
import json
import logging
import os
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

API_BASE = os.environ.get('AGENT_VISION_API_BASE', '').rstrip('/')
API_KEY = os.environ.get('AGENT_VISION_API_KEY', '')
MODEL = os.environ.get('AGENT_VISION_MODEL', '')
TIMEOUT = int(os.environ.get('AGENT_VISION_TIMEOUT', '120'))
MAX_TOKENS = int(os.environ.get('AGENT_VISION_MAX_TOKENS', '1500'))

# Written for the caller: a watchface reviewer, not a generic captioner. The
# main model acts on this text, so it has to carry the things the verification
# checklist asks about.
PROMPT = (
    "This is a screenshot of a Pebble smartwatch running a watchface. Describe it "
    "precisely and literally, for someone who cannot see it and has to decide "
    "whether the layout is correct.\n"
    "Cover, in order:\n"
    "1. The exact time and any date text shown, verbatim.\n"
    "2. Everything drawn on screen and roughly where it sits.\n"
    "3. Colours, including the background.\n"
    "4. Anything clipped at an edge, overlapping badly, cut off, or unreadable.\n"
    "5. Anything that looks broken, blank, or obviously wrong.\n"
    "Report only what is actually visible. If the screen shows the stock "
    "'Install an app to continue' watch screen, say exactly that -- it means no "
    "app is installed. Do not speculate about code."
)


def configured(override=None):
    """A per-turn describer config wins over the container's own."""
    if override:
        return bool(override.get('api_base') and override.get('api_key') and override.get('model'))
    return bool(API_BASE and API_KEY and MODEL)


def describe(png_bytes, override=None):
    """Describe the screenshot. Returns (text, usage).

    usage carries the describer's own cost: on a model that cannot see, every
    screenshot is a paid call to another provider, and leaving it out understates
    what a run actually costs.
    """
    if not configured(override):
        raise VisionError('no vision model configured')
    base = (override or {}).get('api_base') or API_BASE
    key = (override or {}).get('api_key') or API_KEY
    model = (override or {}).get('model') or MODEL

    body = json.dumps({
        'model': model,
        'max_tokens': MAX_TOKENS,
        'messages': [{'role': 'user', 'content': [
            {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png',
                                         'data': base64.b64encode(png_bytes).decode()}},
            {'type': 'text', 'text': PROMPT},
        ]}],
    }).encode()

    req = urllib.request.Request(
        base + '/v1/messages', data=body,
        headers={'Authorization': 'Bearer %s' % key,
                 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            payload = json.loads(r.read())
    except urllib.error.HTTPError as e:
        detail = e.read()[:300].decode(errors='replace')
        raise VisionError('vision model HTTP %s: %s' % (e.code, detail))
    except Exception as e:
        raise VisionError('vision model unreachable: %s' % e)

    # Reasoning models spend the budget on thinking blocks and can return no
    # text at all; that is a failure, not an empty description.
    text = '\n'.join(b.get('text', '') for b in payload.get('content', [])
                     if b.get('type') == 'text').strip()
    if not text:
        raise VisionError('vision model returned no text (all reasoning tokens?)')

    u = payload.get('usage') or {}
    usage = {
        'model': model,
        'input_tokens': u.get('input_tokens'),
        'output_tokens': u.get('output_tokens'),
        # OpenRouter returns the actual charge; other gateways may not.
        'cost_usd': u.get('cost'),
    }
    return text, usage


class VisionError(Exception):
    pass
