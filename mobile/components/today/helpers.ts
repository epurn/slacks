import type { Dispatch, SetStateAction } from "react";

import { type DailySummaryDTO } from "@/api/dailySummary";
import {
  type DerivedItem,
  type DerivedFoodItemDTO,
} from "@/api/derivedItems";
import {
  LogEventApiError,
  type ClarificationQuestionDTO,
  type LogEventDTO,
  type LogEventEntryDTO,
} from "@/api/logEvents";
import { type SavedFoodDTO } from "@/api/savedFoods";

/** Load/poll lifecycle phase for the Today timeline. */
export type Phase = "loading" | "ready" | "error";

/** Maximum raw-text length, mirrored from the FTY-030 contract. */
export const MAX_RAW_TEXT_LENGTH = 2000;

/**
 * Composer seed for the barcode scanner's "Type it instead" fallback (FTY-194).
 * The camera can't hand us a product name, so the fallback drops the user into
 * the natural-language composer with an editable packaged-food starter — a
 * running start, never a blank dead end (design §3: "Barcode not found → fall
 * back to the NL composer (pre-filled)"). The trailing space leaves the caret
 * ready for the product name. It asserts no nutrition and counts nothing until
 * the user completes and submits it, so nothing is fabricated.
 */
export const BARCODE_MANUAL_ENTRY_SEED = "1 serving of ";

/**
 * Id prefix for the synthetic saved-food row built locally on a saved-food add
 * (FTY-053). It marks a client-built resolved row so the items-forward timeline
 * can tell a true optimistic/saved-food row from a server-fed by-date item —
 * server ids are UUIDs and never carry this prefix.
 */
const SAVED_FOOD_ITEM_ID_PREFIX = "saved-";

export function itemTimelineRowTestID(eventId: string): string {
  return `item-timeline-row-${eventId}`;
}

export function itemTimelineExtraRowTestID(
  eventId: string,
  itemId: string,
): string {
  return `item-timeline-row-${eventId}-${itemId}`;
}

/**
 * Test id for a partially-resolved event's pending-question row (FTY-330): the
 * item-scoped "needs a detail" row scoped to one still-open component. Keyed by
 * the event and the clarification question id so a mixed log with more than one
 * open component renders one stable, distinguishable row per question.
 */
export function pendingQuestionRowTestID(
  eventId: string,
  questionId: string,
): string {
  return `pending-question-row-${eventId}-${questionId}`;
}

/** Max characters of the raw phrase shown when a meal row falls back to it. */
const MEAL_RAW_TEXT_FALLBACK_MAX = 60;

/**
 * The collapsed meal-row title (FTY-420). Prefers the model-generated meal name
 * (FTY-421/422); when it is null or blank — an older entry, or the estimator
 * produced no sensible name — it falls back to a trimmed, length-capped form of
 * the raw phrase, and finally to a generic label. So a grouped meal row always
 * shows something legible, never a blank title.
 */
export function mealDisplayName(event: LogEventDTO): string {
  const name = event.name?.trim();
  if (name) return name;
  const raw = event.raw_text.trim();
  if (raw) {
    return raw.length > MEAL_RAW_TEXT_FALLBACK_MAX
      ? `${raw.slice(0, MEAL_RAW_TEXT_FALLBACK_MAX - 1).trimEnd()}…`
      : raw;
  }
  return "Meal";
}

/**
 * Sum a meal's derived-item energy for the collapsed meal-row total (FTY-420):
 * a food item contributes its `calories`, an exercise item its `active_calories`
 * (mirroring `ItemTimelineRow`'s multi-item summary). Returns `null` when any
 * item's value is still missing so the row shows an honest em dash rather than a
 * wrong partial sum. The total is the exact sum of the breakdown rows, so it
 * stays consistent after a per-item edit re-costs one row.
 */
export function sumItemKcal(items: readonly DerivedItem[]): number | null {
  let total = 0;
  for (const item of items) {
    const kcal =
      item.item_type === "food" ? item.calories : item.active_calories;
    if (kcal === null) return null;
    total += kcal;
  }
  return total;
}

/** Map an API/network failure to a plain, nonjudgmental message. */
export function messageFor(
  error: unknown,
  kind: "load" | "save" | "delete",
): string {
  if (error instanceof LogEventApiError) {
    return error.message;
  }
  switch (kind) {
    case "load":
      return "We couldn't load your day. Check your connection and try again.";
    case "delete":
      return "We couldn't delete that entry. Please try again.";
    default:
      return "We couldn't save that entry. Please try again.";
  }
}

/**
 * Whether an item is a locally-built synthetic saved-food row (FTY-053) rather
 * than a server-fed derived item (FTY-198). Used to gate the items-forward
 * fallback to true optimistic/saved-food rows so a server row can only surface
 * through the completed branch — the pending→completed transition that resolves
 * the skeleton in place (FTY-180) and arms the entry-resolve beat (FTY-181),
 * never a mid-poll swap keyed by item id.
 */
export function isSyntheticSavedFoodItem(item: DerivedItem): boolean {
  return item.id.startsWith(SAVED_FOOD_ITEM_ID_PREFIX);
}

/** Build a synthetic resolved food item from a saved food selection (FTY-053). */
export function syntheticSavedFoodItem(
  savedFood: SavedFoodDTO,
  logEventId: string,
  userId: string,
): DerivedFoodItemDTO {
  return {
    item_type: "food",
    id: `${SAVED_FOOD_ITEM_ID_PREFIX}${savedFood.id}`,
    user_id: userId,
    log_event_id: logEventId,
    name: savedFood.name,
    quantity_text: `${savedFood.serving_size} ${savedFood.serving_unit}`,
    unit: savedFood.serving_unit,
    amount: savedFood.serving_size,
    status: "resolved",
    grams: null,
    calories: savedFood.calories,
    protein_g: savedFood.protein_g,
    carbs_g: savedFood.carbs_g,
    fat_g: savedFood.fat_g,
    calories_estimated: savedFood.calories,
    protein_g_estimated: savedFood.protein_g,
    carbs_g_estimated: savedFood.carbs_g,
    fat_g_estimated: savedFood.fat_g,
    source: null,
    is_edited: false,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
}

/**
 * Build the placeholder item the clarify-mode sheet opens against for a
 * `needs_clarification` event (FTY-149). A needs-clarification event has no
 * resolved derived item — the parse stopped for a missing detail — so the sheet
 * (which is item-addressed) is fed a minimal, uncounted stand-in: the typed
 * phrase as the name, no nutrition. Clarify-mode only reads `name`/`id`; it never
 * shows or commits these null values, so the item is never counted and the
 * detail is never auto-filled.
 */
export function clarificationPlaceholderItem(
  event: LogEventDTO,
): DerivedFoodItemDTO {
  return {
    item_type: "food",
    id: `clarify-${event.id}`,
    user_id: event.user_id,
    log_event_id: event.id,
    name: event.raw_text,
    quantity_text: event.raw_text,
    unit: null,
    amount: null,
    status: "unresolved",
    grams: null,
    calories: null,
    protein_g: null,
    carbs_g: null,
    fat_g: null,
    calories_estimated: null,
    protein_g_estimated: null,
    carbs_g_estimated: null,
    fat_g_estimated: null,
    source: null,
    is_edited: false,
    created_at: event.created_at,
    updated_at: event.updated_at,
  };
}

/**
 * Build the placeholder item a partially-resolved event's pending-question row
 * renders against (FTY-330). Unlike `clarificationPlaceholderItem` (the
 * event-level `needs_clarification` case, whose name is the raw phrase), an
 * item-scoped question already names its specific component in the question
 * `text` (e.g. "Which hummus was that?") — so the row's `name` is that question
 * text, never the raw diary phrase (the privacy rule: the raw phrase appears
 * only on the user's own entry row). The item carries no nutrition and its
 * `status` is `unresolved`, so reusing the shared `ItemTimelineRow`'s
 * needs-a-detail treatment keeps it muted, tagged, and visibly uncounted — the
 * existing Today row visual language, not a new one.
 */
export function questionPlaceholderItem(
  event: LogEventDTO,
  question: ClarificationQuestionDTO,
): DerivedFoodItemDTO {
  return {
    item_type: "food",
    id: `clarify-${event.id}-${question.id}`,
    user_id: event.user_id,
    log_event_id: event.id,
    name: question.text,
    quantity_text: question.text,
    unit: null,
    amount: null,
    status: "unresolved",
    grams: null,
    calories: null,
    protein_g: null,
    carbs_g: null,
    fat_g: null,
    calories_estimated: null,
    protein_g_estimated: null,
    carbs_g_estimated: null,
    fat_g_estimated: null,
    source: null,
    is_edited: false,
    created_at: event.created_at,
    updated_at: event.updated_at,
  };
}

/**
 * Drop an optimistic event and its synthetic saved-food item from Today's state
 * by optimistic id — shared by the server-error rollback and the unreachable
 * discard paths the submit machine drives through the bridge.
 */
export function removeOptimisticEvent(
  setEvents: Dispatch<SetStateAction<readonly LogEventDTO[]>>,
  setItemsByEvent: Dispatch<
    SetStateAction<Readonly<Record<string, readonly DerivedItem[]>>>
  >,
  optimisticId: string,
): void {
  setEvents((prev) => prev.filter((event) => event.id !== optimisticId));
  setItemsByEvent((prev) => {
    if (!(optimisticId in prev)) return prev;
    const { [optimisticId]: _removed, ...rest } = prev;
    return rest;
  });
}

/**
 * Recompute the daily summary locally for an optimistically deleted event
 * (FTY-322), so the hero/day totals drop the moment the row does — never only
 * after the DELETE round-trip and summary refetch. Mirrors the backend
 * finalized-state filter (`docs/contracts/daily-summary.md`): `resolved` items
 * on a `completed` **or `partially_resolved`** (FTY-278/330), non-voided event
 * count toward intake/burn — a partial event's committed siblings count
 * immediately — while a `needs_clarification` event and each `proposed` food
 * item contribute one uncounted unit. Anything else (pending/processing/failed
 * events, unresolved items) counts nothing, so deleting it changes no figure.
 * A partial event's still-open item-scoped question is also uncounted, but that
 * count is not derivable from the resolved-sibling `items` passed here; the
 * immediate post-void summary refetch reconciles `uncounted_entries` for it.
 * Every subtraction clamps at zero so drift between the local item feed and the
 * server aggregate can never show a negative total. `has_intake` is left as-is —
 * whether *other* finalized intake remains on the day is the server's call; the
 * post-void summary refetch reconciles it.
 */
export function summaryMinusDeletedEvent(
  summary: DailySummaryDTO,
  event: LogEventDTO,
  items: readonly DerivedItem[],
): DailySummaryDTO {
  let calories = 0;
  let protein = 0;
  let carbs = 0;
  let fat = 0;
  let burn = 0;
  let uncounted = event.status === "needs_clarification" ? 1 : 0;
  if (
    event.status === "completed" ||
    event.status === "partially_resolved"
  ) {
    for (const item of items) {
      if (item.item_type === "food") {
        if (item.status === "resolved") {
          calories += item.calories ?? 0;
          protein += item.protein_g ?? 0;
          carbs += item.carbs_g ?? 0;
          fat += item.fat_g ?? 0;
        } else if (item.status === "proposed") {
          uncounted += 1;
        }
      } else if (item.status === "resolved") {
        burn += item.active_calories ?? 0;
      }
    }
  }
  const minus = (from: number, amount: number): number =>
    Math.max(0, Math.round(from - amount));
  return {
    ...summary,
    intake: {
      calories: minus(summary.intake.calories, calories),
      protein_g: minus(summary.intake.protein_g, protein),
      carbs_g: minus(summary.intake.carbs_g, carbs),
      fat_g: minus(summary.intake.fat_g, fat),
    },
    uncounted_entries: minus(summary.uncounted_entries, uncounted),
    exercise: {
      active_calories: minus(summary.exercise.active_calories, burn),
    },
  };
}

export function hasOwn(object: object, key: PropertyKey): boolean {
  return Object.prototype.hasOwnProperty.call(object, key);
}

/**
 * Fold the item-forward feed into the items map. Derived items replace prior
 * rows; completed empty entries are recorded as a settled-empty `[]` without
 * wiping existing items.
 */
export function mergeServerItems(
  prev: Readonly<Record<string, readonly DerivedItem[]>>,
  entries: readonly LogEventEntryDTO[],
): Readonly<Record<string, readonly DerivedItem[]>> {
  let next: Record<string, readonly DerivedItem[]> | null = null;
  for (const entry of entries) {
    if (entry.items.length > 0) {
      next ??= { ...prev };
      next[entry.event.id] = entry.items;
    } else if (
      entry.event.status === "completed" &&
      !hasOwn(prev, entry.event.id)
    ) {
      next ??= { ...prev };
      next[entry.event.id] = [];
    }
  }
  return next ?? prev;
}
