import { Composition, staticFile } from "remotion";
import { Film } from "./Film";
import type { Timeline } from "./timeline";

// The film is a pure function of timeline.json, which sits in the public folder next to the screenshots.
export const Root = () => (
  <Composition
    id="Film"
    component={Film}
    width={1920}
    height={1080}
    fps={60}
    durationInFrames={60}
    defaultProps={{ tl: null as unknown as Timeline }}
    calculateMetadata={async () => {
      const tl: Timeline = await (await fetch(staticFile("timeline.json"))).json();
      return { props: { tl }, fps: tl.fps, durationInFrames: Math.ceil(tl.duration * tl.fps) };
    }}
  />
);
