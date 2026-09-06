import {
  AbsoluteFill,
  Sequence,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

// Word-level caption for TikTok-style highlight display
export interface WordCaption {
  word: string;
  startMs: number;
  endMs: number;
  // Force a page break after this word (e.g. sentence or scene boundaries).
  // Useful for CJK captions where pages should align with clause boundaries.
  pageBreakAfter?: boolean;
  // ASR per-word confidence (0-1), carried through from the transcriber.
  // Reel speech is transcribed off a mixed music track — there is no stem
  // separation — so a caption stage gates on this rather than printing
  // whatever the model guessed. Purely informational here.
  confidence?: number;
}

// "default" is the shipped look and must stay pixel-identical.
// "reel_pop" is the 9:16 short-form look: per-word scale pop, heavy stroke,
// uppercase, no pill.
export type CaptionPreset = "default" | "reel_pop";

// Fractions of the frame kept clear of caption text. A 9:16 frame needs this
// expressed proportionally: the shipped 80px bottom offset was tuned on 16:9
// and lands captions underneath Instagram's own lower UI band on a reel.
export interface CaptionSafeZone {
  // Fraction of frame height between the caption box and the bottom edge.
  bottom: number;
  // Fraction of frame width kept clear on each side.
  sides?: number;
}

interface PresetStyle {
  popScale: number;        // extra scale applied to the active word
  strokeRatio: number;     // text stroke width as a fraction of fontSize
  uppercase: boolean;
  // Inter-word gap as a fraction of fontSize. `wordSeparator` alone does not
  // survive: each word is an inline-block with `white-space: nowrap`, and CSS
  // drops a trailing space at the end of such a box, so the separator renders
  // as nothing. Verified in a real 1080x1920 render — the shipped default is
  // affected too, but it is left alone deliberately (see the issue) so that
  // existing callers keep rendering byte-identically. New presets opt in.
  wordGapRatio: number;
  safeZone: CaptionSafeZone | null;
}

const PRESETS: Record<CaptionPreset, PresetStyle> = {
  default: {
    popScale: 0,
    strokeRatio: 0,
    uppercase: false,
    wordGapRatio: 0,
    safeZone: null,
  },
  reel_pop: {
    // Tuned on a real 10s / 26-word cut at 1080x1920: the gap has to survive
    // the peak of the pop, or the growing word touches its neighbour for the
    // two frames it is largest.
    popScale: 0.16,
    strokeRatio: 0.14,
    uppercase: true,
    wordGapRatio: 0.4,
    safeZone: { bottom: 0.18, sides: 0.08 },
  },
};

// The shipped absolute offset, used whenever no safe zone is in play.
const LEGACY_PADDING_BOTTOM = 80;

// A 10s reel is ~25-30 words, so a word holds the frame for roughly 350ms.
// The pop has to be over well inside that or every word reads as mid-animation.
// Fixing the duration in frames keeps the timing identical at 24/30/60 fps.
const POP_DURATION_FRAMES = 5;

// Scale impulse: rest -> peak -> rest across POP_DURATION_FRAMES. It is
// deliberately transient. A pop that *stays* enlarged for as long as the word
// is active grows the word about its centre and swallows the gap to its
// neighbour, which at reel font sizes reads as two words run together.
function popPulse(wordFrame: number): number {
  const t = Math.min(Math.max(wordFrame / POP_DURATION_FRAMES, 0), 1);
  return Math.sin(Math.PI * t);
}

type CaptionOverlayProps = {
  words: WordCaption[];
  // How many words to show at once in a "page"
  wordsPerPage?: number;
  fontSize?: number;
  color?: string;
  highlightColor?: string;
  backgroundColor?: string;
  fontFamily?: string;
  // Separator rendered between words. Space-delimited languages want the
  // default " "; CJK languages (no inter-word spacing) should pass "".
  wordSeparator?: string;
  // Opt-in look. Omitted or "default" renders exactly as before.
  preset?: CaptionPreset;
  // Overrides the preset's safe zone. Applies to either preset.
  safeZone?: CaptionSafeZone;
};

interface CaptionPage {
  words: WordCaption[];
  startMs: number;
  endMs: number;
}

function buildPages(words: WordCaption[], wordsPerPage: number): CaptionPage[] {
  const pages: CaptionPage[] = [];
  let pageWords: WordCaption[] = [];
  const flush = () => {
    if (pageWords.length === 0) return;
    pages.push({
      words: pageWords,
      startMs: pageWords[0].startMs,
      endMs: pageWords[pageWords.length - 1].endMs,
    });
    pageWords = [];
  };
  for (const w of words) {
    pageWords.push(w);
    if (pageWords.length >= wordsPerPage || w.pageBreakAfter) flush();
  }
  flush();
  return pages;
}

const PageRenderer: React.FC<{
  page: CaptionPage;
  fontSize: number;
  color: string;
  highlightColor: string;
  backgroundColor: string;
  fontFamily: string;
  wordSeparator: string;
  style: PresetStyle;
  safeZone: CaptionSafeZone | null;
}> = ({ page, fontSize, color, highlightColor, backgroundColor, fontFamily, wordSeparator, style, safeZone }) => {
  const frame = useCurrentFrame();
  const { fps, height } = useVideoConfig();

  const currentMs = page.startMs + (frame / fps) * 1000;

  // Spring entrance
  const entrance = spring({
    frame,
    fps,
    config: { damping: 18, stiffness: 120 },
  });

  return (
    <AbsoluteFill
      style={{
        justifyContent: "flex-end",
        alignItems: "center",
        paddingBottom: safeZone
          ? Math.round(height * safeZone.bottom)
          : LEGACY_PADDING_BOTTOM,
      }}
    >
      <div
        style={{
          opacity: entrance,
          transform: `translateY(${interpolate(entrance, [0, 1], [20, 0])}px)`,
          backgroundColor,
          borderRadius: 12,
          padding: "14px 28px",
          maxWidth: safeZone?.sides
            ? `${Math.round((1 - 2 * safeZone.sides) * 100)}%`
            : "80%",
          textAlign: "center",
        }}
      >
        <span
          style={{
            fontSize,
            fontWeight: 700,
            fontFamily,
            lineHeight: 1.4,
            whiteSpace: "pre-wrap",
            ...(style.uppercase ? { textTransform: "uppercase" as const } : {}),
          }}
        >
          {page.words.map((w, i) => {
            const isActive = w.startMs <= currentMs && w.endMs > currentMs;
            const isPast = w.endMs <= currentMs;
            // Pop is seeded at the word's own start frame, not the page's, so
            // every word gets the same snap regardless of where it sits.
            const wordFrame =
              frame - Math.round(((w.startMs - page.startMs) / 1000) * fps);
            const pop = style.popScale ? popPulse(wordFrame) : 0;
            return (
              <span
                key={`${w.startMs}-${i}`}
                style={{
                  // Keep each word unbroken so lines wrap only at word
                  // boundaries. For space-delimited text this matches the
                  // previous behavior; for CJK it prevents mid-word breaks.
                  display: "inline-block",
                  whiteSpace: "nowrap",
                  color: isActive ? highlightColor : isPast ? color : `${color}99`,
                  transition: "none", // CSS transitions forbidden in Remotion
                  textShadow: isActive
                    ? `0 0 20px ${highlightColor}66, 0 2px 4px rgba(0,0,0,0.5)`
                    : "0 2px 4px rgba(0,0,0,0.5)",
                  // Only emitted under a popping preset — a bare scale(1) still
                  // promotes the span to its own layer and shifts rasterization.
                  ...(style.popScale
                    ? { transform: `scale(${1 + style.popScale * pop})` }
                    : {}),
                  // Not applied after the last word, and not at all when the
                  // caller cleared wordSeparator for CJK.
                  ...(style.wordGapRatio && wordSeparator && i < page.words.length - 1
                    ? { marginRight: fontSize * style.wordGapRatio }
                    : {}),
                  ...(style.strokeRatio
                    ? {
                        WebkitTextStrokeWidth: `${fontSize * style.strokeRatio}px`,
                        WebkitTextStrokeColor: "#000",
                        // Without this the stroke is centred on the glyph edge
                        // and eats half the letterform at these widths.
                        paintOrder: "stroke fill",
                      }
                    : {}),
                }}
              >
                {w.word}{i < page.words.length - 1 ? wordSeparator : ""}
              </span>
            );
          })}
        </span>
      </div>
    </AbsoluteFill>
  );
};

export const CaptionOverlay: React.FC<CaptionOverlayProps> = ({
  words,
  wordsPerPage = 6,
  fontSize = 42,
  color = "#F8FAFC",
  highlightColor = "#22D3EE",
  backgroundColor = "rgba(15, 23, 42, 0.75)",
  fontFamily = "Space Grotesk, Inter, system-ui, sans-serif",
  wordSeparator = " ",
  preset = "default",
  safeZone,
}) => {
  const { fps } = useVideoConfig();
  const pages = buildPages(words, wordsPerPage);
  const style = PRESETS[preset] ?? PRESETS.default;
  const resolvedSafeZone = safeZone ?? style.safeZone;

  return (
    <AbsoluteFill>
      {pages.map((page, i) => {
        const fromFrame = Math.round((page.startMs / 1000) * fps);
        const nextStart = pages[i + 1]?.startMs ?? page.endMs + 500;
        const duration = Math.max(
          1,
          Math.round(((nextStart - page.startMs) / 1000) * fps)
        );

        return (
          <Sequence key={i} from={fromFrame} durationInFrames={duration}>
            <PageRenderer
              page={page}
              fontSize={fontSize}
              color={color}
              highlightColor={highlightColor}
              backgroundColor={backgroundColor}
              fontFamily={fontFamily}
              wordSeparator={wordSeparator}
              style={style}
              safeZone={resolvedSafeZone}
            />
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};
