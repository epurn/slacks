/** Border-radius tokens. */
export const radius = {
  sm: 6,
  md: 10,
  lg: 12,
  xl: 20,
  full: 9999,
} as const;

export type RadiusKey = keyof typeof radius;
