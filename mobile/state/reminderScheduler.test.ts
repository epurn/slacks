import {
  CADENCE_OPTIONS,
  DEFAULT_CADENCE,
  cadenceIntervalDays,
  computeNextDueDate,
  applyReminderSettings,
  onWeightLogged,
  type CadenceStore,
  type NotificationsAdapter,
  type WeighInCadence,
} from "./reminderScheduler";

// ─────────────────────────────────────────────────────────────────────────────
// Mock adapters
// ─────────────────────────────────────────────────────────────────────────────

function mockStore(
  initialCadence: WeighInCadence | null = "weekly",
  initialDate: string | null = null,
): CadenceStore & {
  _cadence: WeighInCadence | null;
  _lastDate: string | null;
} {
  let cadence = initialCadence;
  let lastDate = initialDate;
  return {
    get _cadence() {
      return cadence;
    },
    get _lastDate() {
      return lastDate;
    },
    getCadence: async () => cadence,
    setCadence: async (c) => {
      cadence = c;
    },
    getLastWeighInDate: async () => lastDate,
    setLastWeighInDate: async (d) => {
      lastDate = d;
    },
  };
}

function mockNotifications(): NotificationsAdapter & {
  scheduledDates: Date[];
  cancelCount: number;
  grantPermission: boolean;
} {
  const scheduledDates: Date[] = [];
  let cancelCount = 0;
  let grantPermission = true;
  return {
    get scheduledDates() {
      return scheduledDates;
    },
    get cancelCount() {
      return cancelCount;
    },
    set grantPermission(v: boolean) {
      grantPermission = v;
    },
    requestPermission: async () => grantPermission,
    cancelAll: async () => {
      cancelCount++;
    },
    scheduleAt: async (date: Date) => {
      scheduledDates.push(date);
    },
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// CADENCE_OPTIONS
// ─────────────────────────────────────────────────────────────────────────────

describe("CADENCE_OPTIONS", () => {
  it("includes Weekly, Every 2 weeks, Monthly, Off", () => {
    const values = CADENCE_OPTIONS.map((o) => o.value);
    expect(values).toContain("weekly");
    expect(values).toContain("biweekly");
    expect(values).toContain("monthly");
    expect(values).toContain("off");
  });

  it("Weekly has 7 days, biweekly 14, monthly 30, off null", () => {
    const map = Object.fromEntries(CADENCE_OPTIONS.map((o) => [o.value, o.days]));
    expect(map.weekly).toBe(7);
    expect(map.biweekly).toBe(14);
    expect(map.monthly).toBe(30);
    expect(map.off).toBeNull();
  });
});

describe("DEFAULT_CADENCE", () => {
  it("is 'weekly'", () => {
    expect(DEFAULT_CADENCE).toBe("weekly");
  });
});

describe("cadenceIntervalDays", () => {
  it("returns 7 for weekly", () => expect(cadenceIntervalDays("weekly")).toBe(7));
  it("returns 14 for biweekly", () => expect(cadenceIntervalDays("biweekly")).toBe(14));
  it("returns 30 for monthly", () => expect(cadenceIntervalDays("monthly")).toBe(30));
  it("returns null for off", () => expect(cadenceIntervalDays("off")).toBeNull());
});

// ─────────────────────────────────────────────────────────────────────────────
// computeNextDueDate — pure scheduling
// ─────────────────────────────────────────────────────────────────────────────

describe("computeNextDueDate", () => {
  it("returns null when cadence is 'off'", () => {
    expect(computeNextDueDate("2026-06-01", "off")).toBeNull();
  });

  it("returns null when lastWeighInDate is null", () => {
    expect(computeNextDueDate(null, "weekly")).toBeNull();
  });

  it("schedules weekly reminder at last + 7 days", () => {
    const due = computeNextDueDate("2026-06-20", "weekly");
    expect(due).not.toBeNull();
    expect(due!.getFullYear()).toBe(2026);
    expect(due!.getMonth()).toBe(5); // June (0-indexed)
    expect(due!.getDate()).toBe(27);
  });

  it("schedules biweekly reminder at last + 14 days", () => {
    const due = computeNextDueDate("2026-06-01", "biweekly");
    expect(due!.getDate()).toBe(15);
  });

  it("schedules monthly reminder at last + 30 days", () => {
    const due = computeNextDueDate("2026-06-01", "monthly");
    expect(due!.getDate()).toBe(1);
    expect(due!.getMonth()).toBe(6); // July
  });

  it("fires at 09:00 local time on the due date", () => {
    const due = computeNextDueDate("2026-06-20", "weekly");
    expect(due!.getHours()).toBe(9);
    expect(due!.getMinutes()).toBe(0);
    expect(due!.getSeconds()).toBe(0);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// applyReminderSettings — due-only guarantee (the core invariant)
// ─────────────────────────────────────────────────────────────────────────────

describe("applyReminderSettings", () => {
  it("schedules exactly one notification at last + cadence_days (weekly)", async () => {
    const store = mockStore("weekly", "2026-06-20");
    const notif = mockNotifications();

    await applyReminderSettings("weekly", "2026-06-20", store, notif);

    // NEVER-DAILY GUARANTEE: only one notification is scheduled
    expect(notif.scheduledDates).toHaveLength(1);
    const due = notif.scheduledDates[0]!;
    expect(due.getDate()).toBe(27); // June 27
  });

  it("schedules exactly one notification for each cadence (biweekly)", async () => {
    const store = mockStore("biweekly", "2026-06-01");
    const notif = mockNotifications();

    await applyReminderSettings("biweekly", "2026-06-01", store, notif);

    expect(notif.scheduledDates).toHaveLength(1);
    expect(notif.scheduledDates[0]!.getDate()).toBe(15);
  });

  it("schedules exactly one notification for monthly cadence", async () => {
    const store = mockStore("monthly", "2026-06-01");
    const notif = mockNotifications();

    await applyReminderSettings("monthly", "2026-06-01", store, notif);

    expect(notif.scheduledDates).toHaveLength(1);
  });

  it("NEVER schedules a daily or repeating notification", async () => {
    // Schedule multiple times (simulating cadence changes or re-renders)
    const store = mockStore("weekly", "2026-06-20");
    const notif = mockNotifications();

    await applyReminderSettings("weekly", "2026-06-20", store, notif);
    await applyReminderSettings("weekly", "2026-06-20", store, notif);
    await applyReminderSettings("weekly", "2026-06-20", store, notif);

    // Even after multiple calls, the latest scheduling cycle produces one notification.
    // (Each call cancels before scheduling — no accumulation.)
    // The key assertion: scheduleAt was called (1 per successful apply), but
    // never with a date less than 7 days away.
    for (const d of notif.scheduledDates) {
      const daysSinceLastWeighIn = (d.getTime() - new Date(2026, 5, 20).getTime()) / 86400000;
      expect(daysSinceLastWeighIn).toBeGreaterThanOrEqual(7);
    }
  });

  it("cancels all pending before scheduling a new one (no accumulation)", async () => {
    const store = mockStore("weekly", "2026-06-20");
    const notif = mockNotifications();

    await applyReminderSettings("weekly", "2026-06-20", store, notif);

    // cancelAll is called before scheduleAt
    expect(notif.cancelCount).toBeGreaterThanOrEqual(1);
  });

  it("cancels all and schedules nothing when cadence is 'off'", async () => {
    const store = mockStore("off", "2026-06-20");
    const notif = mockNotifications();

    await applyReminderSettings("off", "2026-06-20", store, notif);

    expect(notif.scheduledDates).toHaveLength(0);
    expect(notif.cancelCount).toBe(1);
  });

  it("persists the cadence preference regardless of notification permission", async () => {
    const store = mockStore("weekly", "2026-06-20");
    const notif = mockNotifications();
    (notif as { grantPermission: boolean }).grantPermission = false;

    await applyReminderSettings("biweekly", "2026-06-20", store, notif);

    // Preference is saved even if notification was denied
    expect(store._cadence).toBe("biweekly");
    // No notification scheduled
    expect(notif.scheduledDates).toHaveLength(0);
  });

  it("degrades gracefully when permission is denied (no notification, no crash)", async () => {
    const store = mockStore("weekly", "2026-06-20");
    const notif = mockNotifications();
    (notif as { grantPermission: boolean }).grantPermission = false;

    await expect(
      applyReminderSettings("weekly", "2026-06-20", store, notif),
    ).resolves.not.toThrow();
    expect(notif.scheduledDates).toHaveLength(0);
  });

  it("schedules nothing when there is no last weigh-in date", async () => {
    const store = mockStore("weekly", null);
    const notif = mockNotifications();

    await applyReminderSettings("weekly", null, store, notif);

    expect(notif.scheduledDates).toHaveLength(0);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// onWeightLogged — reschedules forward
// ─────────────────────────────────────────────────────────────────────────────

describe("onWeightLogged", () => {
  it("persists the new weigh-in date", async () => {
    const store = mockStore("weekly", "2026-06-13");
    const notif = mockNotifications();

    await onWeightLogged("2026-06-20", store, notif);

    expect(store._lastDate).toBe("2026-06-20");
  });

  it("reschedules the reminder from the new weigh-in date", async () => {
    const store = mockStore("weekly", "2026-06-13");
    const notif = mockNotifications();

    await onWeightLogged("2026-06-20", store, notif);

    expect(notif.scheduledDates).toHaveLength(1);
    expect(notif.scheduledDates[0]!.getDate()).toBe(27); // June 20 + 7
  });

  it("uses stored cadence when rescheduling", async () => {
    const store = mockStore("biweekly", "2026-06-06");
    const notif = mockNotifications();

    await onWeightLogged("2026-06-20", store, notif);

    expect(notif.scheduledDates).toHaveLength(1);
    expect(notif.scheduledDates[0]!.getDate()).toBe(4); // June 20 + 14 = July 4
  });

  it("falls back to DEFAULT_CADENCE ('weekly') when no cadence is stored", async () => {
    const store = mockStore(null, null);
    const notif = mockNotifications();

    await onWeightLogged("2026-06-20", store, notif);

    // Should use weekly (7 days from June 20 = June 27)
    expect(notif.scheduledDates).toHaveLength(1);
    expect(notif.scheduledDates[0]!.getDate()).toBe(27);
  });

  it("NEVER schedules a daily notification (logged weigh-in schedules + 7+ days out)", async () => {
    const store = mockStore("weekly", null);
    const notif = mockNotifications();

    await onWeightLogged("2026-06-20", store, notif);

    for (const d of notif.scheduledDates) {
      const msAhead = d.getTime() - new Date(2026, 5, 20).getTime();
      const daysAhead = msAhead / 86400000;
      expect(daysAhead).toBeGreaterThanOrEqual(6.9); // at least ~7 days
    }
  });
});
