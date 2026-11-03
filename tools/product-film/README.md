# Product Film

Turn a storyboard into a clean, Apple-style product film of any web app: real clicks and typing in the real app, a
smooth camera, big quiet headlines, and an original score that changes on the same beats as the picture.

You write about 40 lines describing what the viewer should see. One command gives you the film.

```bash
cd tools/product-film
npm install
npm run setup      # the capture browser and the score's Python packages; no system installs
npm run example    # makes example/harbor-film.mp4 from the small app in example/app
```

Needs Node 20+ and Python 3.9+. Renders about as fast as real time on an M-series Mac: a one-minute film takes about a
minute, plus capture. Rendering uses [Remotion](https://www.remotion.dev), which is free for individuals, non-profits
and companies of up to 3 people. **Larger for-profit companies need a [company license](https://www.remotion.pro/license).**

## Why it isn't a screen recording

Screen recordings look like screen recordings: jittery cursor, spinners, the wrong window size, and every retake means
performing the whole thing again. So nothing here records the screen in real time.

```
 storyboard ─► 1 capture ─► 2 compile ─► 3 score ─► 4 render ─► film.mp4
 what the      Playwright   timeline     music on   Remotion    + chapters
 viewer sees   drives the   .json:       the same   draws each  + player page
               real app;    every        beats      frame from
               2× screen-   moment as               the timeline
               shots        data
```

- **The clicks are real.** Playwright operates your actual app, so every state on screen is genuine.
- **The motion is not.** The camera and cursor are drawn afterwards, so they move perfectly at 60 fps whatever the app
  was doing, and you can change the timing without touching the app again.
- **Picture and music share a clock.** Every scene starts on a downbeat and lasts whole bars.
- **Reading time is automatic.** A scene is never shorter than the time it takes to read its words.

## Make a film of your app

**1. Run your app with good demo data** (see [the look](#the-look) for why this matters most).

**2. Write a storyboard.** Put it anywhere, for example `my-app/film.mjs`:

```js
export default ({ click, type, press, focus, spotlight, scroll, hover, pull }) => ({
  output: "my-app-film.mp4",
  app: { url: "http://localhost:3000" },
  brand: { name: "Acme", accent: "#0071e3", logo: "public/logo.svg" },
  window: { address: "acme.com" },

  intro: { headline: "Invoices that", accent: "send themselves.", sub: "Acme for small teams." },

  scenes: [
    {
      id: "create",
      eyebrow: "Create",
      title: "An invoice in ten seconds.",
      body: "Start typing. Acme fills in the rest.",
      start: "/invoices",
      steps: [
        click("role=button[name='New invoice']"),
        type("#client", "Northwind Traders"),
        press("Enter"),
        focus("#total", { hold: 1.6, ring: true, note: "Tax worked out for you." }),
      ],
    },
    // … 4 to 8 scenes is a good film
  ],

  outro: { headline: "Acme.", accent: "Get paid.", cta: "acme.com" },
});
```

**3. Check it, then make it:**

```bash
node tools/product-film/film.mjs my-app/film.mjs capture   # run the storyboard against the app
node tools/product-film/film.mjs my-app/film.mjs stills    # key frames as images, in seconds
node tools/product-film/film.mjs my-app/film.mjs preview   # scrub through the film, with sound
node tools/product-film/film.mjs my-app/film.mjs render    # the final film
```

You get, next to the storyboard:

| File | What it is |
|---|---|
| `my-app-film.mp4` | The film: 1080p60 H.264 with AAC audio and chapters built in |
| `my-app-film.html` | A player with a clickable chapter list. ← → jump between chapters. Host it with the video |
| `my-app-film.chapters.txt` | Paste into a YouTube description to get chapters there |
| `my-app-film.chapters.vtt` | Chapters for your own web player |

Add `.film/` to your `.gitignore`. It holds the screenshots.

## The stages

`node film.mjs <storyboard> <stage>`

| Stage | Does | Use it when |
|---|---|---|
| `capture` | Runs the storyboard in the app. `--only=a,b` redoes those scenes (they need a `start`) | The steps or the app changed |
| `compile` | Rebuilds the timeline from the captures | You want to check the length (every stage below does this for you) |
| `score` | Rewrites the music (also automatic whenever the timing changes) | You want a fresh score |
| `stills` | Key frames as images in `.film/<name>/stills`. `--at=12.5,30` picks the moments | Checking the look. It takes seconds |
| `preview` | Opens Remotion Studio: scrub the film, with sound | Checking the motion and timing |
| `draft` | A quick half-size 30 fps video | Sending someone a rough cut |
| `render` | The final film, chapters and player | You're happy |
| `all` | capture, then render (the default) | Start to finish |

Changing titles, holds, zooms or music needs no recapture: just `stills` or `render` again.

## Storyboard reference

### Steps

A **target** is any [Playwright selector](https://playwright.dev/docs/other-locators):
`"role=button[name='Save']"`, `"text=Invoices"`, `"#total"`, or `page => page.getByTestId("x")`. Prefer roles and text:
they survive redesigns.

| Step | The viewer sees | Options |
|---|---|---|
| `click(target)` | The cursor glides over, its hover state shows, it clicks, the result fades in | `hold`, `camera: false`, `note`, `settle` |
| `hover(target)` | The cursor glides over and rests | `hold`, `camera: false`, `note` |
| `type(target, text)` | Clicks the field and types, key by key, with soft key sounds | `cps` (speed), `every` (keys per screenshot), `hold`, `camera: false` |
| `press("Meta+K")` | A key is pressed | `show: true` draws a keycap on screen, `hold` |
| `focus(target)` | The camera pushes in on it | `zoom`, `hold`, `ring: true`, `note` |
| `spotlight(target)` | Everything else dims, Keynote style | `hold`, `note` |
| `pull()` | The camera returns to the whole window | `hold` |
| `scroll({by})` / `scroll({to})` | A smooth scroll | `within` (a scrolling panel), `seconds`, `hold` |
| `drag(from, to)` | The cursor drags, and the app responds as it moves | `seconds`, `frames`, `hold` |
| `waitFor(what)` | Nothing: waits off camera, then fades to the result | `hold`, `timeout` |
| `lapse({until})` | Long work as a time-lapse, such as an AI response streaming | `seconds` (playback), `every`, `max`, `note` |
| `goto(url)` | Fades to that page | `hold` |
| `hold(seconds)` | Rests on the frame | |
| `run(page => …)` | Anything Playwright can do, off camera, then a fade to the result | `hold` |

`hold` is how many seconds to linger afterwards. `note` is a short line in a frosted pill.
By default the camera follows clicks and typing when the target is off screen or the view is wide.

### Scenes

| Field | |
|---|---|
| `id` | Lowercase and hyphens. Names the folder of screenshots |
| `title` | The headline, nine words at most |
| `eyebrow` | One word above it, in the accent colour. Also the chapter name |
| `body` | One line under it, under 18 words |
| `start` | A URL to open first. Without it, the scene carries on from the last |
| `steps` | What happens |
| `energy` | Overrides the music here: `low`, `mid`, `breath`, `high`, `build` |
| `minBars`, `chapter` | Shortest length in bars; a chapter name other than the eyebrow |

### Settings

| Setting | Default | |
|---|---|---|
| `app.url` | required | Where your app runs |
| `app.start`, `app.cwd` | | A command to start the app if it isn't running |
| `app.viewport` | 1440 × 810 | Smaller makes the UI larger on screen. Keep it 16:9 |
| `app.colorScheme` | `light` | Match this to `brand.theme` |
| `app.css` | | Injected CSS: hide dev badges, cookie banners |
| `app.storageState` | | A [saved login](https://playwright.dev/docs/auth) |
| `app.setup(page)`, `app.init(context)` | | Log in, set a theme; stub network calls |
| `brand.name`, `brand.logo` | | No logo: a glass sphere in the accent colour, which the app then opens inside |
| `brand.accent` | `#0071e3` | |
| `brand.theme` | `light` | `dark` is the black-stage keynote look |
| `brand.font` | Inter | A font installed on this machine |
| `window.chrome` | `browser` | `plain` drops the browser bar |
| `window.address` | | The text in the address bar. Use your public domain, not localhost |
| `music.mood` | `airy` | `airy` or `pulse`, see below |
| `music.bpm`, `music.key` | 96, 2 | Tempo; semitones up from C |
| `music.file`, `music.gain` | | Your own track, and its volume |
| `film.fps` | 60 | |
| `film.scale` | 1 | `2` makes a 4K film. The screenshots are sharp enough |
| `film.crf` | 16 | Higher makes a smaller file. 22 is still clean |
| `film.concurrency` | half your cores | Lower it if memory runs short |
| `film.autoCamera`, `film.autoZoom`, `film.focusZoom` | true, 1.5, 2 | |
| `film.typingSpeed`, `film.maxTyping` | 24, 3.2 | Characters a second; the longest typing takes, in seconds |

## The look

The tool handles the camera, easing, type and pacing. These are the decisions that are still yours, in order of how much
they matter.

**1. Demo data is the film.** A real product demo looks expensive because the data looks real: believable names, tidy
numbers, charts that go up, no "test123", no error badges, nothing half-finished. Build a seed script before anything
else. Never film real customer data.

**2. One idea per scene.** Each scene shows one thing the product does and says it in one line. If a title needs "and",
it's two scenes. Four to eight scenes and 60 to 90 seconds beats three minutes of everything.

**3. Say what it does for them, not what it is.** "Get paid in two days", not "Automated payment reminders". Short,
declarative, a little proud. Read each line aloud: if it sounds like a feature list, cut it.

**4. Push in on what matters.** A whole app window is too small to read on a phone. Follow every wide shot with a
`focus`. Text in the UI should be readable at the moment it matters.

**5. Show, then stop.** After the payoff of a scene, `hold` a beat longer than feels necessary. Pace is what reads as
expensive; rushing reads as a tutorial.

**6. Set the scene.** Hide dev badges (`app.css`), use a large clean window, and hide whatever isn't in the story.
Choose light or dark to match the product and keep them consistent: `brand.theme` and `app.colorScheme` together.

**7. Music from a real composer is the last 10%.** The built-in score is unobtrusive and free of licensing questions,
but a licensed track is better if the film matters. See below.

### Music

The score is synthesised for each film from the timeline, so there are no samples and nothing to license. It follows
the shape of the film: quiet opening, a soft arrival as the app appears, rising through the scenes, a breath in the
middle, full near the end, and a last chord ringing out under the logo.

- `airy` (default): felt-piano pulse, warm pad, very soft kick. Keynote-demo calm.
- `pulse`: the same harmony with more drive: firmer kick, claps, hats, bells up front. Closer to a launch film.

Using your own track (Artlist, Epidemic Sound and similar):

```js
music: { file: "assets/track.mp3", bpm: 120, gain: 0.8 },
```

Set `bpm` to the track's real tempo so scene changes land on its beats. Pick one with few vocals and little change in
level. The click and key sounds are still added over the top.

## Recipes

**Log in first.** Save a session once with `npx playwright codegen --save-storage=auth.json <url>`, then set
`app.storageState: "auth.json"`. Keep it out of git.

**Slow, costly or random backends.** Answer those calls yourself, so captures are free, instant and identical every time:

```js
app: {
  init: async (context) => {
    await context.route("**/api/suggestions", (route) => route.fulfill({ json: { items: ["Summarise", "Translate"] } }));
  },
},
```

`example/agentic-translation.film.mjs` does this. Watch for AI features that run on their own when a page opens: they
spend real tokens during capture unless stubbed.

**Live AI output.** Start it, then `lapse({ until: "text=Done", seconds: 4 })` shows it streaming in four seconds.

**Non-English UIs.** Set `app.locale` and `app.timezone`. Chinese, Japanese, Korean and Arabic in the film's own text
fall back to the system fonts.

**Apps that don't run in a browser.** Capture only automates web apps (including anything served locally). For a native
or mobile app, take the screenshots yourself and write `.film/<name>/public/<scene>/manifest.json` by hand:
`[{ "type": "cut", "src": "<scene>/1.png" }, { "type": "click", "rect": {"x":0,"y":0,"w":80,"h":32}, "x":40, "y":16, "before": "<scene>/2.png", "after": "<scene>/3.png" }]`,
with coordinates in `app.viewport` pixels. Then skip `capture` and run `render`.

## When something goes wrong

| Symptom | What to do |
|---|---|
| `Scene "x", step 3 … failed` | Look at the `failed-step-3.png` it names, in the scene's folder, and fix the selector. Find selectors with `npx playwright codegen <url>` |
| `Nothing answers at …` | Start your app, or set `app.start` |
| A shot is caught mid-transition | Give the step a longer `settle` (milliseconds) |
| Dev tools or badges in shot | Hide them with `app.css`. For Next.js: `nextjs-portal { display: none !important; }` |
| `the scroll moved nothing` | The page scrolls inside a panel: use `scroll({ by: 400, within: "#panel" })` |
| Clicks fail on custom widgets | Make the target more specific, or use `run(page => …)` |
| The app's own animation doesn't play | See limits below; a `lapse` often gets close enough |
| File too large | Raise `film.crf` to 22, or lower `film.fps` to 30 |
| `Timeout … rendering the component`, or a very slow render | The machine is short of memory: close heavy apps, or set `film.concurrency: 2` |

## Limits

- **The app's own animations don't play as motion.** A click shows the state before and after, with a soft fade between.
  `drag`, `scroll` and typing are captured as real frame sequences, and `lapse` captures whatever is happening, at the
  rate screenshots can be taken.
- **Video inside the app appears as still frames**, for the same reason.
- **Native and mobile apps** need the hand-written manifest above.
- **16:9 only.** Portrait and square films aren't supported.

## Working on the tool

| Path | |
|---|---|
| `lib/dsl.mjs` | The storyboard steps |
| `lib/capture.mjs` | Stage 1: Playwright, screenshots, measurements |
| `lib/compile.mjs` | Stage 2: the timing rules. Tested in `test/` (`npm test`) |
| `score/score.py` | Stage 3: the music. `ENERGY` and `MOODS` at the top are the arrangement |
| `src/` | Stage 4: the Remotion composition. `Film.tsx` holds all the visual design |
| `lib/player.mjs` | The chapter files and player page |
