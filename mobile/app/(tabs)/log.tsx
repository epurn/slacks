import { StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useTheme } from '@/theme';

/**
 * Log tab — placeholder.
 * The full natural-language composer is implemented in its own story.
 * This screen keeps the tab reachable and the shell navigable without
 * regressing any currently-shipped feature.
 */
export default function LogTab() {
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();

  return (
    <View
      style={[
        styles.container,
        { backgroundColor: colors.surface, paddingBottom: insets.bottom + 80 },
      ]}
    >
      <Text style={[styles.placeholder, { color: colors.textSecondary }]}>
        Log screen coming soon
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
  },
  placeholder: {
    fontSize: 17,
    fontWeight: '400',
  },
});
