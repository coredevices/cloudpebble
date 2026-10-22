# Agent model bench

Runs any model through the identical watchface brief so results are comparable.
Adding a model is a JSON entry, not a code change.

```bash
export MOONSHOT_API_KEY=... OPENROUTER_API_KEY=... CP_PASSWORD=...

./switch.sh kimi                      # point the agent VM at a model
AGENT_LABEL=kimi python3 bench.py     # run the brief against it
python3 compare.py                    # table across every recorded run
```

Results land in `results/<label>/`: one PNG per screenshot the agent took, plus
`summary.json` with per-turn tool calls, timings and token usage.

## Adding a model

Add an entry to `models.json`:

```json
"my-model": {
  "model": "vendor/model-id",
  "api_base": "https://gateway.example.com/anthropic",
  "key_env": "MY_API_KEY",
  "vision": true
}
```

`api_base` must speak the Anthropic Messages API (`POST {api_base}/v1/messages`).
Leave it empty for first-party Anthropic. `key_env` names the environment
variable holding the key -- **no secrets in this repo**, and `switch.sh` refuses
to run if the variable is unset.

Set `"vision": false` if the model cannot accept image content. Screenshots then
go through the vision describer instead, and the agent is told plainly that a
different model did the looking.

## The vision describer

Text-only models are the norm among cheap tool-callers, and handing one an image
block means it "verifies" a screenshot it never received -- worse than not
looking, because the visual check is the whole quality mechanism.

So `vision_describer` in `models.json` names a vision model that reads the
screenshot and returns a text description. Currently `qwen/qwen3.8-max`, chosen
because it reported the time, date, layout, background gradient and small
sprites correctly against a known image, and costs less than kimi-k3 per call.

Verify a candidate describer before trusting it: give it a screenshot you have
looked at yourself and check it gets the *time* right. A describer that
hallucinates is worse than none.

## What the bench measures

Two turns: an ambitious animated space watchface, then one follow-up asking for
a denser composition and proof the animation is real. Recorded per turn:

- wall clock, and which tools were called in what order
- every screenshot, so quality is judged from pixels rather than the model's claims
- `input_tokens`, `output_tokens`, `cache_read_input_tokens`,
  `cache_creation_input_tokens`, `total_cost_usd`
- the full configuration, in `usage`: `model`, `api_base`, `model_vision`,
  `vision_model`, `max_output_tokens`. A result is not interpretable without
  knowing which eye the agent was using -- runs before this was recorded carry a
  hand-written `note` marked RECONSTRUCTED, which is weaker evidence.

**Read the cache hit rate**, which `compare.py` prints. What dominates cost is
the share of input served from cache, and a cheap model with a poor hit rate
ends up more expensive than an expensive one with a good rate.

Do **not** read `cache_creation = 0` as "caching is broken". Providers with
implicit caching never bill a separate cache write and always report zero there
while still serving most of the conversation from cache. Measured on the same
brief:

| route | uncached in | cache read | hit rate | cost |
|---|---|---|---|---|
| kimi-k3 via OpenRouter | 103,126 | 407,552 | 80% | $1.87 |
| kimi-k3 direct (Moonshot) | 70,929 | 795,330 | 92% | $1.76 |
| claude-sonnet-5 | 32 | 662,142 | ~100% | $1.25 |

Going direct to Moonshot cut uncached input 31% and lifted the hit rate to 92%,
but per-turn cost barely moved, because that run also did more work (3 builds
and 4 screenshots against 2 and 2).

### Prompt caching across turns

The agent used to create a fresh `CLAUDE_CONFIG_DIR` per turn and delete it
afterwards. That destroyed prefix caching on every provider that caches by
prefix rather than by explicit `cache_control` breakpoints -- DeepSeek's docs
are blunt that only requests with identical prefixes from the 0th token hit, and
that "a changing timestamp, request ID, or user-specific line at the top can
destroy useful prefix reuse". A random path per turn is exactly that.

The config dir is now stable per session. Measured with two trivial turns on one
session, before and after:

| provider              | turn 2 before | turn 2 after |
|-----------------------|---------------|--------------|
| deepseek-v4-flash     | 0.0%          | **96.2%**    |
| kimi-k3 (Moonshot)    | -             | **95.3%**    |
| kimi-k3 (OpenRouter)  | -             | 75.2%        |
| claude-sonnet-5       | 97.8%         | 97.8%        |

Two things the numbers show:

* **Use Moonshot directly, not OpenRouter, for kimi.** 95% against 75% on the
  same model. Moonshot's `/anthropic` endpoint honours `cache_control`; the
  gateway appears not to forward it.
* **A cold prefix reads 0%.** The first request that establishes a prefix cannot
  hit anything. Moonshot carries a warm prefix across sessions (turn 1 measured
  97.3% on a second run); DeepSeek does not, so its turn 1 is always cold. Do
  not read a single cold turn as a caching failure -- measure turn 2.

## Gotchas this harness already handles

Each of these silently corrupted a run before being fixed:

- The event stream replays a session from `?since=`, so record the last seq
  before sending or the previous turn's events look like the new one's.
- The qemu controller reaps an emulator after 300s without a ping; a turn runs
  far longer, so the harness pings every 60s.
- Swapping in a fresh emulator per turn is *worse* than losing one: the agent
  screenshots a watch it never installed to and cannot know why.
- The long-lived SSE connection is cut well before a turn ends. Reconnect from
  the last seq, exactly as `agent.js`'s EventSource does.
