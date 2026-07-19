/**
 * Attached-image thumbnail strip for the Today composer (FTY-383).
 *
 * Renders the composer's staged images as a horizontal row of thumbnails, each
 * with a remove control. A newly-added thumbnail fades in with the shared motion
 * settings (`theme/motion`), degrading to an instant appearance under Reduce
 * Motion — meaningful state changes animate calmly, never jarringly (design
 * philosophy: *Motion is part of native polish* + *Calm by default*).
 *
 * Pure view: it renders what it is given and calls back on remove; the compose
 * state lives in `useComposerImages`.
 */

import { useEffect, useState } from "react";
import {
  Animated,
  Image,
  Pressable,
  StyleSheet,
  View,
} from "react-native";

import { AppIcon } from "@/components/ui";
import { useReduceMotion } from "@/theme/motion";
import { useTheme, spacing, radius } from "@/theme";

import type { ComposerImage } from "./useComposerImages";

const THUMB_SIZE = 64;

export function ComposerThumbnails({
  images,
  onRemove,
}: {
  images: readonly ComposerImage[];
  onRemove: (index: number) => void;
}) {
  if (images.length === 0) return null;
  return (
    <View style={styles.strip} accessibilityRole="list">
      {images.map((image, index) => (
        <Thumbnail
          key={`${image.uri}-${index}`}
          image={image}
          index={index}
          onRemove={onRemove}
        />
      ))}
    </View>
  );
}

function Thumbnail({
  image,
  index,
  onRemove,
}: {
  image: ComposerImage;
  index: number;
  onRemove: (index: number) => void;
}) {
  const { colors } = useTheme();
  const reduceMotion = useReduceMotion();
  // Fade the thumbnail in on add; Reduce Motion starts it fully visible so no
  // motion is forced on a user who has opted out.
  const [opacity] = useState(() => new Animated.Value(reduceMotion ? 1 : 0));
  useEffect(() => {
    if (reduceMotion) {
      opacity.setValue(1);
      return;
    }
    Animated.timing(opacity, {
      toValue: 1,
      duration: 180,
      useNativeDriver: true,
    }).start();
  }, [opacity, reduceMotion]);

  const label = `Attached photo ${index + 1}`;
  return (
    <Animated.View style={[styles.thumbWrap, { opacity }]}>
      <Image
        source={{ uri: image.uri }}
        style={[styles.thumb, { backgroundColor: colors.controlBackground }]}
        accessibilityRole="image"
        accessibilityLabel={label}
        resizeMode="cover"
      />
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={`Remove photo ${index + 1}`}
        accessibilityHint="Removes this photo from the log you're composing"
        hitSlop={8}
        onPress={() => onRemove(index)}
        style={[styles.remove, { backgroundColor: colors.surface }]}
      >
        <AppIcon name="xmark.circle.fill" size={22} color={colors.textMuted} />
      </Pressable>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  strip: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.sm,
    marginBottom: spacing.sm,
  },
  thumbWrap: {
    width: THUMB_SIZE,
    height: THUMB_SIZE,
  },
  thumb: {
    width: THUMB_SIZE,
    height: THUMB_SIZE,
    borderRadius: radius.md,
  },
  remove: {
    position: "absolute",
    top: -8,
    right: -8,
    borderRadius: 12,
    // Keep a comfortable tap target without inflating the visual glyph.
    padding: 1,
  },
});
