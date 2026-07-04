import { act, type ReactTestRenderer } from "react-test-renderer";

const activeTrees: ReactTestRenderer[] = [];

export function trackReactTestRenderer(tree: ReactTestRenderer): ReactTestRenderer {
  activeTrees.push(tree);
  return tree;
}

export function cleanupReactTestRenderers(): void {
  for (const tree of activeTrees.splice(0)) {
    try {
      act(() => tree.unmount());
    } catch {
      // The tree may already have been unmounted by the test.
    }
  }
}
