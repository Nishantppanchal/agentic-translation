// The storyboard for this repository's own app. It uses documents already translated, and answers the app's AI-assist
// requests itself, so a capture calls no model, spends nothing and comes out the same every time.
// FILM_URL=http://localhost:3000 node film.mjs example/agentic-translation.film.mjs all
export default ({ click, type, focus, hover, pull }) => ({
  output: "agentic-translation-film.mp4",
  app: {
    url: process.env.FILM_URL ?? "http://localhost:3000",
    css: "nextjs-portal { display: none !important; }", // no dev-server badge in the film
    init: async (context) => {
      await context.route("**/assist/**", (route) => route.fulfill({ json: { suggestions: [], completion: "", cached: true } }));
    },
    setup: async (page) => {
      await page.evaluate(() => localStorage.setItem("theme", "light"));
    },
  },
  brand: { name: "Agentic Translator", accent: "#4a7fc1", theme: "light" },
  window: { chrome: "browser", address: "translate.app" },
  music: { mood: "airy", bpm: 96 },

  intro: { headline: "Machine translation", accent: "you can talk to.", sub: "Next-generation OCR & translation" },

  scenes: [
    {
      id: "start",
      eyebrow: "Upload",
      title: "Any document. Any language.",
      body: "Scans, PDFs, Word, PowerPoint and Excel, always into English.",
      start: "/",
      steps: [
        hover("text=Drop a file here", { hold: 0.9 }),
        focus("role=button[name=/^Second reading/]", { hold: 1.2, zoom: 1.7, ring: true, note: "Two models read every page. A third settles where they differ." }),
      ],
    },
    {
      id: "document",
      eyebrow: "Translation",
      title: "Read it like the original.",
      steps: [
        click("text=Defect re-inspection report >> nth=0", { hold: 0.9, camera: false, settle: 5000 }),
        click("role=tab[name='Document']", { hold: 0.5, camera: false }),
        focus("role=heading[name=/Defect Re-inspection Report/]", { hold: 1.2, zoom: 1.6 }),
        pull(),
        click("text=Side by side", { hold: 1.8, camera: false, settle: 5000 }),
      ],
    },
    {
      id: "chat",
      eyebrow: "Chat",
      title: "Ask for changes in plain words.",
      body: "Every edit arrives as a proposal you accept or reject.",
      steps: [type("textarea", "Use “rectification” for 消缺 throughout", { hold: 1.0, cps: 20 })],
    },
    {
      id: "segments",
      eyebrow: "Segments",
      title: "The linguist's view, when you want it.",
      steps: [
        click("role=tab[name='Segments']", { hold: 0.8, camera: false, settle: 4000 }),
        focus("text=Confirm AI-checked", { hold: 1.2, zoom: 1.7, note: "Confirm everything the AI reviewer passed, in one click." }),
      ],
    },
    {
      id: "quality",
      eyebrow: "Quality",
      title: "Quality you can measure.",
      steps: [
        click("role=tab[name='Quality']", { hold: 0.8, camera: false, settle: 4000 }),
        focus("text=Quality score (LQA)", { hold: 1.4, zoom: 1.8, ring: true }),
      ],
    },
  ],

  outro: { headline: "Machine translation", accent: "you can talk to.", sub: "Next-generation OCR & translation" },
});
