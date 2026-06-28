import { StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { useTheme } from '@/theme';

/**
 * Trends tab — placeholder.
 * The weight trend chart and intake history are implemented in their own story.
 * This screen keeps the tab reachable without regressing shipped features.
 */
export default function TrendsTab() {
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
        Trends screen coming soon
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
