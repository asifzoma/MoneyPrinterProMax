import React from "react";
import {
  AbsoluteFill,
  Audio,
  Composition,
  Img,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
  CalculateMetadataFunction,
} from "remotion";

export type Caption = {
  text: string;
  startFrame: number;
  endFrame: number;
};

export type HiddenHistoryProps = {
  title: string;
  imagePaths: string[]; // relative to public/, e.g. "tmp/img0.jpg"
  audioPath: string; // relative to public/, e.g. "tmp/narration.mp3"
  captions: Caption[];
};

const WIDTH = 1080;
const HEIGHT = 1920;
const FPS = 30;
const TITLE_DURATION = 60; // 2s
const OUTRO_BUFFER = 15; // 0.5s tail after the last caption
const CROSSFADE_FRAMES = 12; // 0.4s -- desired crossfade duration between images

type Scene = {
  imageIndex: number;
  startFrame: number;
  endFrame: number;
};

// Groups captions into per-image scenes by caption index. Captions
// themselves render separately, at their own absolute frame positions (see
// HiddenHistoryComponent) -- kept independent of image timing so extending
// image Sequences for the crossfade (buildImageSequences, below) never
// shifts caption or audio sync.
function buildScenes(captions: Caption[], imageCount: number): Scene[] {
  if (captions.length === 0 || imageCount === 0) return [];
  const scenes: Scene[] = [];
  let currentImageIndex = -1;
  captions.forEach((caption, i) => {
    const imageIndex = Math.min(
      imageCount - 1,
      Math.floor((i / captions.length) * imageCount),
    );
    if (imageIndex !== currentImageIndex) {
      scenes.push({ imageIndex, startFrame: caption.startFrame, endFrame: caption.endFrame });
      currentImageIndex = imageIndex;
    } else {
      scenes[scenes.length - 1].endFrame = caption.endFrame;
    }
  });
  return scenes;
}

type ImageSequenceSpec = {
  imageIndex: number;
  from: number; // absolute frame, extended for the crossfade where applicable
  durationInFrames: number; // extended to match
  fadeInFrames: number; // 0 for the first image -- starts at full opacity
  fadeOutFrames: number; // 0 for the last image -- stays at full opacity
};

// Extends each scene's image Sequence to straddle its neighboring
// boundaries by half a crossfade window on each side, so two images render
// simultaneously during the transition instead of hard-cutting. Each
// boundary's crossfade is clamped to at most a third of the SHORTER of its
// two neighboring scenes' own durations -- so even back-to-back short
// scenes always keep at least a third of their own time at full opacity:
// no negative/degenerate fades, and a scene's lead-in and lead-out fades
// can never collide with each other.
function buildImageSequences(scenes: Scene[]): ImageSequenceSpec[] {
  const boundaryOverlap = scenes.slice(0, -1).map((scene, i) => {
    const next = scenes[i + 1];
    const shorter = Math.min(
      scene.endFrame - scene.startFrame,
      next.endFrame - next.startFrame,
    );
    return Math.max(0, Math.min(CROSSFADE_FRAMES, Math.floor(shorter / 3)));
  });

  return scenes.map((scene, i) => {
    const leadIn = i > 0 ? Math.round(boundaryOverlap[i - 1] / 2) : 0;
    const leadOut = i < scenes.length - 1 ? Math.round(boundaryOverlap[i] / 2) : 0;
    return {
      imageIndex: scene.imageIndex,
      from: scene.startFrame - leadIn,
      durationInFrames: scene.endFrame - scene.startFrame + leadIn + leadOut,
      fadeInFrames: leadIn,
      fadeOutFrames: leadOut,
    };
  });
}

const KenBurnsImage: React.FC<{
  src: string;
  durationInFrames: number;
  fadeInFrames: number;
  fadeOutFrames: number;
}> = ({ src, durationInFrames, fadeInFrames, fadeOutFrames }) => {
  const frame = useCurrentFrame();
  const scale = interpolate(frame, [0, durationInFrames], [1, 1.25], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const translateX = interpolate(frame, [0, durationInFrames], [0, -60], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  // Crossfade opacity: ramps in over fadeInFrames at the start, full
  // opacity through the steady middle, ramps out over fadeOutFrames at the
  // end. fadeInFrames/fadeOutFrames are 0 for the first/last image, so
  // those two never ramp -- they start/stay at full opacity, matching the
  // old hard-cut behavior at the very start and end of the sequence.
  const opacityIn =
    fadeInFrames > 0
      ? interpolate(frame, [0, fadeInFrames], [0, 1], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        })
      : 1;
  const opacityOut =
    fadeOutFrames > 0
      ? interpolate(frame, [durationInFrames - fadeOutFrames, durationInFrames], [1, 0], {
          extrapolateLeft: "clamp",
          extrapolateRight: "clamp",
        })
      : 1;
  const opacity = Math.min(opacityIn, opacityOut);

  return (
    <AbsoluteFill style={{ overflow: "hidden", opacity }}>
      <Img
        src={src}
        style={{
          width: "100%",
          height: "100%",
          objectFit: "cover",
          transform: `scale(${scale}) translateX(${translateX}px)`,
        }}
      />
    </AbsoluteFill>
  );
};

const CaptionText: React.FC<{ text: string }> = ({ text }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const pop = spring({ frame, fps, config: { damping: 14, stiffness: 160 } });
  return (
    <AbsoluteFill
      style={{ justifyContent: "flex-end", alignItems: "center", paddingBottom: 220 }}
    >
      <div
        style={{
          opacity: pop,
          transform: `scale(${0.85 + pop * 0.15})`,
          fontFamily: "sans-serif",
          fontSize: 58,
          fontWeight: 800,
          color: "white",
          textAlign: "center",
          textShadow: "0 0 16px rgba(0,0,0,0.85), 0 4px 8px rgba(0,0,0,0.6)",
          maxWidth: "88%",
          lineHeight: 1.25,
        }}
      >
        {text}
      </div>
    </AbsoluteFill>
  );
};

const TitleCard: React.FC<{ title: string }> = ({ title }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const pop = spring({ frame, fps, config: { damping: 12, stiffness: 140 } });
  const fadeOut = interpolate(frame, [TITLE_DURATION - 15, TITLE_DURATION], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <AbsoluteFill style={{ backgroundColor: "black", justifyContent: "center", alignItems: "center" }}>
      <div
        style={{
          opacity: pop * fadeOut,
          transform: `scale(${0.9 + pop * 0.1})`,
          fontFamily: "sans-serif",
          fontSize: 64,
          fontWeight: 900,
          color: "white",
          textAlign: "center",
          maxWidth: "85%",
          lineHeight: 1.2,
        }}
      >
        {title}
      </div>
    </AbsoluteFill>
  );
};

export const HiddenHistoryComponent: React.FC<HiddenHistoryProps> = ({
  title,
  imagePaths,
  audioPath,
  captions,
}) => {
  const scenes = buildScenes(captions, imagePaths.length);
  const imageSequences = buildImageSequences(scenes);

  return (
    <AbsoluteFill style={{ backgroundColor: "black" }}>
      <Sequence from={0} durationInFrames={TITLE_DURATION}>
        <TitleCard title={title} />
      </Sequence>

      <Sequence from={TITLE_DURATION}>
        <Audio src={staticFile(audioPath)} />

        {imageSequences.map((spec, i) => (
          <Sequence key={`img-${i}`} from={spec.from} durationInFrames={spec.durationInFrames}>
            <KenBurnsImage
              src={staticFile(imagePaths[spec.imageIndex])}
              durationInFrames={spec.durationInFrames}
              fadeInFrames={spec.fadeInFrames}
              fadeOutFrames={spec.fadeOutFrames}
            />
          </Sequence>
        ))}

        {captions.map((caption, i) => (
          <Sequence
            key={`cap-${i}`}
            from={caption.startFrame}
            durationInFrames={caption.endFrame - caption.startFrame}
          >
            <CaptionText text={caption.text} />
          </Sequence>
        ))}
      </Sequence>
    </AbsoluteFill>
  );
};

const calculateMetadata: CalculateMetadataFunction<HiddenHistoryProps> = ({
  props,
}) => {
  const lastEnd = props.captions.length
    ? props.captions[props.captions.length - 1].endFrame
    : 0;
  return {
    durationInFrames: TITLE_DURATION + lastEnd + OUTRO_BUFFER,
  };
};

export const HiddenHistory: React.FC = () => {
  return (
    <Composition
      id="HiddenHistory"
      component={HiddenHistoryComponent}
      durationInFrames={TITLE_DURATION + OUTRO_BUFFER}
      fps={FPS}
      width={WIDTH}
      height={HEIGHT}
      calculateMetadata={calculateMetadata}
      defaultProps={{
        title: "Sample Title",
        imagePaths: [] as string[],
        audioPath: "",
        captions: [] as Caption[],
      }}
    />
  );
};
