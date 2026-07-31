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

type Scene = {
  imageIndex: number;
  startFrame: number;
  endFrame: number;
  captionIndices: number[];
};

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
      scenes.push({
        imageIndex,
        startFrame: caption.startFrame,
        endFrame: caption.endFrame,
        captionIndices: [i],
      });
      currentImageIndex = imageIndex;
    } else {
      const scene = scenes[scenes.length - 1];
      scene.endFrame = caption.endFrame;
      scene.captionIndices.push(i);
    }
  });
  return scenes;
}

const KenBurnsImage: React.FC<{ src: string; durationInFrames: number }> = ({
  src,
  durationInFrames,
}) => {
  const frame = useCurrentFrame();
  const scale = interpolate(frame, [0, durationInFrames], [1, 1.15], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const translateX = interpolate(frame, [0, durationInFrames], [0, -20], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <AbsoluteFill style={{ overflow: "hidden" }}>
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

  return (
    <AbsoluteFill style={{ backgroundColor: "black" }}>
      <Sequence from={0} durationInFrames={TITLE_DURATION}>
        <TitleCard title={title} />
      </Sequence>

      <Sequence from={TITLE_DURATION}>
        <Audio src={staticFile(audioPath)} />
        {scenes.map((scene, sceneIndex) => (
          <Sequence
            key={sceneIndex}
            from={scene.startFrame}
            durationInFrames={scene.endFrame - scene.startFrame}
          >
            <KenBurnsImage
              src={staticFile(imagePaths[scene.imageIndex])}
              durationInFrames={scene.endFrame - scene.startFrame}
            />
            {scene.captionIndices.map((captionIndex) => {
              const caption = captions[captionIndex];
              return (
                <Sequence
                  key={captionIndex}
                  from={caption.startFrame - scene.startFrame}
                  durationInFrames={caption.endFrame - caption.startFrame}
                >
                  <CaptionText text={caption.text} />
                </Sequence>
              );
            })}
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
