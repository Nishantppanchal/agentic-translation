// A complete storyboard, run against the small app in example/app. Copy it as the start of your own.
export default ({ click, type, press, focus, spotlight, scroll, hover, drag }) => ({
  output: "harbor-film.mp4",
  app: {
    url: "http://localhost:4173",
    start: "node example/app/server.mjs", // optional: leave it out if your app is already running
    cwd: "..",
  },
  brand: { name: "Harbor", accent: "#0071e3", theme: "light" }, // no logo given: a glass sphere in the accent colour
  window: { chrome: "browser", address: "harbor.example" },
  music: { mood: "airy", bpm: 96 },

  intro: { headline: "Every project,", accent: "finally calm.", sub: "Harbor. Plan, track and ship together." },

  scenes: [
    {
      id: "board",
      eyebrow: "Plan",
      title: "See the whole week at a glance.",
      body: "Every task, every teammate, one quiet board.",
      steps: [
        hover("text=Redesign the checkout", { hold: 0.8 }),
        focus("#col-doing", { hold: 1.2, zoom: 1.8 }),
      ],
    },
    {
      id: "capture",
      eyebrow: "Capture",
      title: "An idea takes one keystroke.",
      steps: [
        press("Meta+K", { show: true, hold: 0.5 }),
        type("#new-title", "Write the launch announcement", { hold: 0.3 }),
        click("role=button[name='Priya']", { hold: 0.4, camera: false }),
        click("role=button[name='Add task']", { hold: 1.0, camera: false }),
      ],
    },
    {
      id: "move",
      eyebrow: "Move",
      title: "Drag it. Done.",
      body: "Status follows the work, with no forms to fill in.",
      steps: [drag("text=Write the launch announcement", "#col-doing .dropzone", { hold: 1.0 })],
    },
    {
      id: "focus",
      eyebrow: "Insight",
      title: "Know what's slipping, before it does.",
      start: "/#insights",
      steps: [
        spotlight("#risk-card", { hold: 1.6, note: "Harbor flags risk from the work itself." }),
        scroll({ within: "#content", by: 420, seconds: 1.6, hold: 1.0 }),
      ],
    },
  ],

  outro: { headline: "Harbor.", accent: "Calm by design.", sub: "Free for teams of up to ten.", cta: "harbor.example" },
});
