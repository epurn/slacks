/**
 * FTY-312: `Make it exact` exact-evidence panel.
 *
 * The dedicated exact-evidence surface the correction sheet shows in `make-exact`
 * mode. It renders the choice surface (scan barcode / type barcode / capture
 * label), the typed-barcode entry, the loading and error states, and the proposal
 * preview, and opens the reusable capture surfaces (FTY-311) as full-screen modals
 * from within the sheet — no Today host change and never creating a log event.
 *
 * State + async live in `useExactEvidence`; this is the view layer plus the two
 * capture modals. All new UI stays correction-owned.
 */

import {
  ActivityIndicator,
  Modal,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import type { DerivedFoodItemDTO } from "@/api/derivedItems";
import { BarcodeScannerScreen } from "@/components/BarcodeScannerScreen";
import {
  LabelCaptureScreen,
  type LabelCaptureScreenProps,
} from "@/components/LabelCaptureScreen";
import { DisplayText } from "@/components/ui/DisplayText";
import { AppIcon } from "@/components/ui/AppIcon";
import type { AppIconName } from "@/components/ui/AppIcon";
import type { CameraCaptureProps } from "@/components/CameraCapture";
import { radius, spacing, typeScale, type ColorPalette } from "@/theme";

import { ExactProposalPreview } from "./ExactProposalPreview";
import type { useExactEvidence } from "./useExactEvidence";

/** Test seams for the capture surfaces (real camera hooks by default). */
export interface ExactEvidenceCaptureInjectables {
  cameraPermissionsHook?: CameraCaptureProps["permissionsHook"];
  labelTakePhoto?: LabelCaptureScreenProps["takePhoto"];
}

export function ExactEvidencePanel({
  item,
  exact,
  onCancel,
  onChangeMatch,
  onManualEdit,
  colors,
  cameraPermissionsHook,
  labelTakePhoto,
}: {
  item: DerivedFoodItemDTO;
  exact: ReturnType<typeof useExactEvidence>;
  /** Leave the exact-evidence flow (back to the normal sheet). */
  onCancel: () => void;
  /** Fall back to the Change-match lever. */
  onChangeMatch: () => void;
  /** Fall back to a manual value edit. */
  onManualEdit: () => void;
  colors: ColorPalette;
} & ExactEvidenceCaptureInjectables) {
  const { step } = exact;

  return (
    <View style={styles.panel}>
      {/* Barcode scanner (FTY-311) — a full-screen modal presented from the sheet.
          No `onManualEntry`: the correction sheet has no composer to fall back to,
          so the "Type it instead" affordance is hidden. */}
      <Modal
        visible={exact.scannerOpen}
        animationType="slide"
        presentationStyle="fullScreen"
        onRequestClose={exact.closeScanner}
      >
        <BarcodeScannerScreen
          onBarcodeScanned={exact.handleBarcodeScanned}
          onClose={exact.closeScanner}
          permissionsHook={cameraPermissionsHook}
        />
      </Modal>

      {/* Nutrition-label capture (FTY-311) — save-photo stays off by default and
          opt-in; the capture is attached as exact evidence, never uploaded as a
          normal label log event. */}
      <Modal
        visible={exact.labelOpen}
        animationType="slide"
        presentationStyle="fullScreen"
        onRequestClose={exact.closeLabel}
      >
        <LabelCaptureScreen
          onSubmit={exact.handleLabelSubmit}
          onClose={exact.closeLabel}
          takePhoto={labelTakePhoto}
          permissionsHook={cameraPermissionsHook}
        />
      </Modal>

      {step === "preview" && exact.proposal ? (
        <ExactProposalPreview
          item={item}
          proposal={exact.proposal}
          amount={exact.amount}
          onStepAmount={exact.stepAmount}
          applying={exact.applying}
          error={exact.error}
          onApply={() => void exact.apply()}
          onTryAgain={exact.tryAgain}
          onChangeMatch={onChangeMatch}
          onManualEdit={onManualEdit}
          onCancel={onCancel}
          colors={colors}
        />
      ) : (
        <>
          <View style={styles.header}>
            <DisplayText scale="headline" style={styles.title}>
              Make it exact
            </DisplayText>
            <Pressable
              onPress={onCancel}
              accessibilityLabel="Cancel make it exact"
              accessibilityRole="button"
              style={styles.headerButton}
            >
              <Text style={[styles.headerButtonLabel, { color: colors.accentText }]}>
                Cancel
              </Text>
            </Pressable>
          </View>

          {step === "choose" ? (
            <ChoiceSurface exact={exact} colors={colors} />
          ) : step === "type-barcode" ? (
            <TypeBarcode exact={exact} colors={colors} />
          ) : step === "loading" ? (
            <View style={styles.loadingBox}>
              <ActivityIndicator
                color={colors.accent}
                accessibilityLabel="Looking up exact evidence"
              />
            </View>
          ) : (
            // error
            <ErrorState
              message={exact.error}
              onTryAgain={exact.tryAgain}
              onChangeMatch={onChangeMatch}
              onManualEdit={onManualEdit}
              colors={colors}
            />
          )}
        </>
      )}
    </View>
  );
}

function ChoiceSurface({
  exact,
  colors,
}: {
  exact: ReturnType<typeof useExactEvidence>;
  colors: ColorPalette;
}) {
  return (
    <View style={styles.choiceList}>
      <Text style={[styles.intro, { color: colors.textSecondary }]}>
        Add product evidence to replace this rough estimate.
      </Text>
      <ChoiceRow
        icon="barcode.viewfinder"
        label="Scan barcode"
        hint="Opens the camera to scan a product barcode"
        onPress={exact.chooseScanBarcode}
        colors={colors}
      />
      <ChoiceRow
        icon="keyboard"
        label="Type barcode"
        hint="Enter a barcode number by hand"
        onPress={exact.chooseTypeBarcode}
        colors={colors}
      />
      <ChoiceRow
        icon="doc.text.viewfinder"
        label="Capture nutrition label"
        hint="Opens the camera to photograph a nutrition label"
        onPress={exact.chooseCaptureLabel}
        colors={colors}
      />
    </View>
  );
}

function ChoiceRow({
  icon,
  label,
  hint,
  onPress,
  colors,
}: {
  icon: AppIconName;
  label: string;
  hint: string;
  onPress: () => void;
  colors: ColorPalette;
}) {
  return (
    <Pressable
      onPress={onPress}
      accessibilityLabel={label}
      accessibilityHint={hint}
      accessibilityRole="button"
      style={({ pressed }) => [
        styles.choiceRow,
        { backgroundColor: colors.controlBackground },
        pressed && { opacity: 0.7 },
      ]}
    >
      <AppIcon name={icon} size={20} color={colors.accent} />
      <Text style={[styles.choiceLabel, { color: colors.text }]}>{label}</Text>
      <Text style={[styles.choiceChevron, { color: colors.textMuted }]}>›</Text>
    </Pressable>
  );
}

function TypeBarcode({
  exact,
  colors,
}: {
  exact: ReturnType<typeof useExactEvidence>;
  colors: ColorPalette;
}) {
  return (
    <View style={styles.typeBox}>
      <TextInput
        accessibilityLabel="Barcode"
        placeholder="Barcode number"
        placeholderTextColor={colors.textMuted}
        value={exact.barcodeText}
        onChangeText={exact.setBarcodeText}
        onSubmitEditing={exact.submitTypedBarcode}
        keyboardType="number-pad"
        returnKeyType="search"
        autoCorrect={false}
        style={[
          styles.input,
          { backgroundColor: colors.controlBackground, color: colors.text },
        ]}
      />
      {exact.error ? (
        <Text style={[styles.errorText, { color: colors.coral }]} accessibilityRole="alert">
          {exact.error}
        </Text>
      ) : null}
      <View style={styles.typeActions}>
        <Pressable
          onPress={exact.backToChoose}
          accessibilityLabel="Back"
          accessibilityRole="button"
          style={styles.backButton}
        >
          <Text style={[styles.backLabel, { color: colors.accentText }]}>Back</Text>
        </Pressable>
        <Pressable
          onPress={exact.submitTypedBarcode}
          accessibilityLabel="Look up barcode"
          accessibilityRole="button"
          style={[styles.lookupButton, { backgroundColor: colors.accent }]}
        >
          <Text style={[styles.lookupLabel, { color: colors.accentForeground }]}>
            Look up
          </Text>
        </Pressable>
      </View>
    </View>
  );
}

function ErrorState({
  message,
  onTryAgain,
  onChangeMatch,
  onManualEdit,
  colors,
}: {
  message: string | null;
  onTryAgain: () => void;
  onChangeMatch: () => void;
  onManualEdit: () => void;
  colors: ColorPalette;
}) {
  return (
    <View style={styles.errorBox}>
      <Text
        style={[styles.errorMessage, { color: colors.textSecondary }]}
        accessibilityRole="alert"
      >
        {message ?? "We couldn't make that exact. Try again in a moment."}
      </Text>
      <View style={styles.errorActions}>
        <Pressable
          onPress={onTryAgain}
          accessibilityLabel="Try again"
          accessibilityRole="button"
          style={[styles.lookupButton, { backgroundColor: colors.accent }]}
        >
          <Text style={[styles.lookupLabel, { color: colors.accentForeground }]}>
            Try again
          </Text>
        </Pressable>
        <Pressable
          onPress={onChangeMatch}
          accessibilityLabel="Change match"
          accessibilityRole="button"
          style={styles.backButton}
        >
          <Text style={[styles.backLabel, { color: colors.accentText }]}>Change match</Text>
        </Pressable>
        <Pressable
          onPress={onManualEdit}
          accessibilityLabel="Manual edit"
          accessibilityRole="button"
          style={styles.backButton}
        >
          <Text style={[styles.backLabel, { color: colors.accentText }]}>Manual edit</Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  panel: {
    paddingHorizontal: spacing.base,
    paddingVertical: spacing.md,
    gap: spacing.md,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
  },
  title: {
    flex: 1,
  },
  headerButton: {
    minHeight: 44,
    minWidth: 44,
    alignItems: "flex-end",
    justifyContent: "center",
  },
  headerButtonLabel: {
    fontSize: typeScale.callout,
    fontWeight: "500",
  },
  intro: {
    fontSize: typeScale.subhead,
  },
  choiceList: {
    gap: spacing.sm,
  },
  choiceRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
    paddingHorizontal: spacing.base,
    paddingVertical: spacing.md,
    borderRadius: radius.md,
    minHeight: 56,
  },
  choiceLabel: {
    flex: 1,
    fontSize: typeScale.callout,
    fontWeight: "500",
  },
  choiceChevron: {
    fontSize: typeScale.title3,
    fontWeight: "300",
  },
  loadingBox: {
    paddingVertical: spacing.xl,
    alignItems: "center",
  },
  typeBox: {
    gap: spacing.sm,
  },
  input: {
    height: 44,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    fontSize: typeScale.callout,
  },
  typeActions: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
  },
  backButton: {
    minHeight: 44,
    justifyContent: "center",
    paddingHorizontal: spacing.sm,
  },
  backLabel: {
    fontSize: typeScale.callout,
    fontWeight: "500",
  },
  lookupButton: {
    minHeight: 44,
    borderRadius: radius.md,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: spacing.lg,
  },
  lookupLabel: {
    fontSize: typeScale.callout,
    fontWeight: "700",
  },
  errorBox: {
    gap: spacing.md,
  },
  errorMessage: {
    fontSize: typeScale.subhead,
  },
  errorActions: {
    flexDirection: "row",
    flexWrap: "wrap",
    alignItems: "center",
    gap: spacing.sm,
  },
  errorText: {
    fontSize: typeScale.footnote,
  },
});
