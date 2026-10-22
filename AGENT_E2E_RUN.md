# New-user end-to-end run — 6 August 2026

One person who cannot code, sitting in front of CloudPebble, on the free tier
(`deepseek-v4-flash` for the work, `mistral-small-3.2-24b` as its eyes). Everything
below was done through the browser: create a project, type into the chat panel, look at
what came back. No API calls, no shortcuts.

Two projects:

| | Project 67 "Aurora Face" | Project 68 "Dice Roller" |
|---|---|---|
| Type | Alloy (JavaScript SDK), tutorial template | Pebble C SDK, empty project |
| Asked for | big time, day/date, battery bar, aurora colours | roll dice on a button press, big number, shake animation, colour |
| Turns | 5 | 3 |
| Outcome | working, installed, verified by screenshot | working, installed, verified by screenshot |

Both were built, installed and visually verified by the agent itself. The free tier
cannot see, so every screenshot went through the describer — 3 to 6 describer calls per
turn, about $0.0001 each.

## What the run cost, in the user's time

The dice app was right on the first build: two dice with correct pips, a total, button
hints. Three turns, no dead ends, and it added colour and a tumble animation when asked.

The watchface took five turns and roughly 25 minutes, and most of that was spent on
problems that had nothing to do with the watchface. One turn burned its entire 30-step
budget. A user without an engineer watching would have given up somewhere around the
third "emulator rejected the install".

## What blocked a new user, and what was done about it

**The agent could not read its own reference guides.** `Read` is banned and `read_file`
only sees project files, so the Alloy guide shipped inside the skill was unreachable. The
model tried both routes, failed, and then spent a whole 30-step budget rediscovering by
trial that `import Battery from "battery"` does not exist in that runtime — which is what
the guide says. *Fixed: a `read_reference` tool, path-checked to the skills directory.
On the retry the model read the guide, found the real API (`embedded:sensor/Battery`),
and shipped the battery bar in one turn.*

**"Emulator rejected the install" read as "your code is broken".** qemu answers BlobDB
errors that way and CloudPebble's own UI responds by telling the user to reboot. The
agent, told only "status 1", concluded its app was crashing and began deleting working
features to bisect — it removed the battery bar, then reverted to the stock template.
*Fixed: the tool now says it is an emulator problem, not the code, and to ask the user to
reboot.*

**A turn could never see a new emulator.** The descriptor is captured when the turn
starts. Reboot the emulator mid-turn — which is exactly what the rejection asks for — and
every later install and screenshot dials a dead instance until the turn ends. *Fixed: an
agent-scoped endpoint returns the live emulator, and the tools re-resolve through it when
a connection dies.*

**Nothing but the user can open an emulator, and nothing said so.** Both projects built
on the first turn and dead-ended on "no emulator is running -- open the emulator in
CloudPebble first". The agent explains it well, but a new user does not know that means
Build & Run → Emery. *Fixed: those failures now carry an Open emulator / Restart emulator
button that drives Build & Run's own control.*

**No visible way to queue a message mid-turn.** Stop replaced Send, so Enter was the only
route to the queue and nothing advertised it; clicking where Send had been did nothing.
*Fixed: Send stays visible and becomes Queue.*

**An invisible modal ate the keyboard.** CloudPebble leaves its install-progress modal
open behind the reboot prompt. Dismiss the prompt and the page keeps a focus-trapping
modal nobody can see: the chat composer cannot be typed into again until a reload. This
one predates the agent and is easy to hit without it. *Fixed: the progress modal is
hidden before the prompt goes up.*

## Still open

- **One emulator per user, shared by every project.** Both tabs got the same instance
  (`qemu-user-<id>-<platform>`), so two projects overwrite each other's installed app and
  a screenshot can show the wrong project's work. Pre-existing; the agent makes it much
  easier to hit.
- **30 steps is not enough for an unfamiliar runtime.** The Alloy turn ended mid-
  experiment with `main.js` left as a debug probe. It recovered on the next turn, but the
  step limit should scale with how much trouble the turn is in.
- **`max_turns` prints twice** — the friendly sentence, then the raw SDK line.
- **An empty chat panel offers a new user nothing**: no examples, no hint that an
  emulator will be needed, no sense of what this thing can do.
- **The model reached for a `run` skill that does not exist here**, and for
  `Skill: pebble-watchface:reference/...` as a way to read a file. Both are harmless
  noise, both cost a step.

---

# Second run — 7 August 2026

Same setup, harder briefs, after the first run's fixes. Step limit raised to 75, the
emulator now opens itself, and the model is told what tools it has.

| | Project 69 "Tide Clock" | Project 70 "Space Now" |
|---|---|---|
| Type | Pebble C SDK, empty project | Pebble C SDK, empty project |
| Asked for | big time, ocean scene whose water level tracks the tide, a wave animation on every minute change | how many people are in space right now with their names, live from a free API, down to scroll |
| Outcome | working, animated, verified | fetches live data, proven in logs; last screenshot still showed the demo list |

## What the fixes bought

`read_reference` was the first tool both agents reached for -- the Alloy guide, the API
reference, the animated-watchface template, the watchapp guide. No more trial and error
against an unfamiliar runtime.

The emulator opened itself. The space app hit "no emulator is running", the panel started
one and queued its own "carry on", and the agent continued. No user action, no button.

"The emulator rejected the install" now says it is an emulator problem: the tide agent
read it, said so to the user, and did NOT start deleting working features to bisect --
which is exactly what happened in the first run.

## What this run found

**`logs()` had never worked.** The watch ships APP_LOG output only after it is asked to;
the browser sends APP_LOGS=1 to endpoint 2006 after every install and the agent never did.
Four drains, "0 log lines" every time, so the space app gave up on the live fetch it had
been asked for and shipped an offline demo. With the fix it read the logs, found that
HTTPS is blocked in the emulator sandbox but plain HTTP works, switched, and got
`JS: ok via source1 200 (12 people)` -> `[C]: Space Now inbox received`. The whole feature
turned on the ability to read a log line.

**The automatic emulator started the worst watch.** Aplite is first in DOM order, so a
colour watchface got designed and verified on a 144x168 black and white screen. It now
prefers the platform the agent is laying out for, then the richest available -- the tide
face moved to emery and stopped looking like a fax.

**A deploy orphans every in-flight turn.** The relay is a thread inside a web worker. I
killed both runs twice this way; sessions sat 'running' with disabled composers until the
stale timeout half an hour later. The web container now releases them at startup with an
event that says so and that "continue" resumes. Verified: 3 released on the next deploy.

**Two projects share one emulator, and it is worse than it looks.** Screenshots showed the
other project's app; logs carried the other project's phone-side JS; installs kicked each
other off until both agents were retrying against a moving target. The agents each
diagnosed it correctly and kept working, which is the best that can be done from their
side. This needs an emulator per project, or a lock.

**The model still defaults to a watchface.** "Space Now", an explicit app request with
button scrolling, was built as a watchface with a big clock until corrected. The skill is
watchface-first and the project name nudged it. It switched instantly when told.

**Correcting the kind of thing being built does not correct the setting.** Told "this
isn't a watchface, I want an app", the model rewrote the code as an app -- and left
`app_is_watchface = true`, so it still installs over the user's clock instead of appearing
in the app menu. The skill is emphatic that a watchface must be flagged; it needs to be
just as emphatic in the other direction, and to re-check the flag whenever the user
redescribes what they are building.

**A still frame cannot prove an animation.** The tide agent reported the wave as working
from a single screenshot. Asked to prove it across a minute boundary, it discovered the
wave was not animating at all, added it, and then showed it moving. Worth teaching: for
anything time-driven, several shots and a statement of what changed between them.

## Environment note

Chromium cannot sandbox on this host (`kernel.apparmor_restrict_unprivileged_userns=1`),
so browser automation needs `GSTACK_CHROMIUM_NO_SANDBOX=1`.
