// Section 10, reduced to one composition: place required and optional stories in contract order,
// measure, and repair the first clipped slot down a fixed ladder until the page fits or a required
// story cannot be placed. Then try reserves one at a time. Every transition is recorded.
import type { EditionContractV1, Story } from "../contract/edition-contract.generated.ts";
import { publisherError, type PublisherFailure } from "../publish/errors.ts";
import type { DeviceBrowser, Measurement } from "./browser.ts";
import { CAPACITY, renderDevicePage, type BodyVariant, type DevicePlan, type Placement } from "./render.ts";

export type FitReport = {
  schema_version: 1;
  edition_id: string;
  status: "fit" | "failed";
  composition: "lead-wide" | null;
  attempts: Array<{ candidate: number; measurement: Measurement }>;
  repairs: Array<{
    candidate: number;
    slot: string | null;
    story_id: string;
    action: string;
    before: unknown;
    after: unknown;
  }>;
  off_origin_requests: Array<{ category: string; url_sha256: string }>;
};
export type FitResult = { plan: DevicePlan; html: string; measurement: Measurement; report: FitReport };
export type TitleLike = { masthead: string; publishers: Record<string, string> };

const MAX_CANDIDATES = 80;
const RUNGS: BodyVariant[] = ["extended", "standard", "short"];
const START: Record<Placement["role_as_placed"], BodyVariant | null> = {
  lead: null,
  secondary: "short",
  brief: null,
};

/** The longest supplied variant not above the starting rung, else the shortest supplied one. */
function startingVariant(story: Story, role: Placement["role_as_placed"]): BodyVariant | null {
  const start = START[role];
  if (!start) return null;
  const supplied = RUNGS.filter((v) => story.copy.body[v]);
  return supplied.find((v) => RUNGS.indexOf(v) >= RUNGS.indexOf(start)) ?? supplied.at(-1) ?? null;
}

function lowerVariant(story: Story, current: BodyVariant | null): BodyVariant | null {
  if (!current) return null;
  return RUNGS.slice(RUNGS.indexOf(current) + 1).find((v) => story.copy.body[v]) ?? null;
}

/** Assign slots in contract order; null when the role counts exceed the composition. */
function assign(stories: Story[], roles: Map<string, Placement["role_as_placed"]>): Placement[] | null {
  const counts = { secondary: 0, brief: 0 };
  const placements: Placement[] = [];
  for (const story of stories) {
    const role = roles.get(story.id) ?? story.role;
    let slot: string;
    if (role === "lead") slot = "lead";
    else {
      if (counts[role] >= CAPACITY[role]) return null;
      counts[role] += 1;
      slot = `${role}-${counts[role]}`;
    }
    placements.push({
      story_id: story.id,
      role_as_placed: role,
      slot,
      headline_variant: "headline",
      copy_variant: startingVariant(story, role),
      callout_index: role === "brief" || story.callouts.length === 0 ? null : 0,
    });
  }
  return placements;
}

export async function fitEdition(
  browser: DeviceBrowser,
  edition: EditionContractV1,
  config: TitleLike,
): Promise<FitResult> {
  const byId = new Map(edition.stories.map((s) => [s.id, s]));
  const report: FitReport = {
    schema_version: 1,
    edition_id: edition.edition.id,
    status: "failed",
    composition: "lead-wide",
    attempts: [],
    repairs: [],
    off_origin_requests: browser.offOrigin,
  };
  const plan: DevicePlan = { composition: "lead-wide", placements: [], omitted: [], dropped_callouts: [] };
  const roles = new Map<string, Placement["role_as_placed"]>();
  const state = new Map<string, Placement>();
  let candidate = 0;
  const fail = (type: string, message: string, details: Record<string, unknown>): PublisherFailure =>
    publisherError(type, message, { ...details, fit_report: report });
  const record = (slot: string | null, story_id: string, action: string, before: unknown, after: unknown) =>
    report.repairs.push({ candidate, slot, story_id, action, before, after });

  // Count-level selection: demote, then omit optional stories, until the role counts fit the composition.
  let active = edition.stories.filter((s) => s.device_participation !== "reserve");
  const place = (): Placement[] | null => {
    const placements = assign(active, roles);
    if (!placements) return null;
    // Repairs persist across re-placement: restore each story's selected variants.
    return placements.map((p) => {
      const prior = state.get(p.story_id);
      return prior ? { ...p, headline_variant: prior.headline_variant, copy_variant: prior.copy_variant,
        callout_index: prior.callout_index } : p;
    });
  };
  // Every edition seen so far lists omittable stories in contract order, which is prominence order, so
  // the least prominent optional story is the last one in the list and goes first.
  const omit = (reason: string): boolean => {
    const next = [...edition.fit_policy.omittable_story_ids].reverse().find((id) => active.some((s) => s.id === id));
    if (!next) return false;
    active = active.filter((s) => s.id !== next);
    plan.omitted.push({ story_id: next, reason });
    record(null, next, "omit_story", "placed", reason);
    return true;
  };
  const demote = (): boolean => {
    if (!edition.fit_policy.allow_role_fallback) return false;
    const target = [...active].reverse().find((s) => s.fallback_role && (roles.get(s.id) ?? s.role) === "secondary");
    if (!target) return false;
    roles.set(target.id, "brief");
    state.delete(target.id);
    record(null, target.id, "fallback_role", "secondary", "brief");
    return true;
  };
  /** Place the active stories, omitting optional ones until the role counts fit the composition. */
  const settle = (): Placement[] => {
    let next = place();
    while (!next) {
      if (!demote() && !omit("capacity")) {
        throw fail("composition_unavailable", "the stories do not fit the composition's slot counts", {
          composition: "lead-wide",
          capacity: CAPACITY,
          remaining_story_ids: active.map((s) => s.id),
        });
      }
      next = place();
    }
    return next;
  };
  let placements: Placement[] = settle();

  // Measured repairs. Bands size to content and the lead takes the remainder, so a too-full page
  // shows as a clipped lead; a clipped secondary or brief means sideways overflow of its own copy.
  let html = "";
  let measurement: Measurement | null = null;
  const measure = async (current: Placement[]): Promise<Measurement> => {
    candidate += 1;
    if (candidate > MAX_CANDIDATES) {
      throw fail("fit_budget_exhausted", "the fit search exceeded its candidate budget", { max: MAX_CANDIDATES });
    }
    plan.placements = current;
    for (const p of current) state.set(p.story_id, p);
    html = renderDevicePage(edition, plan, config);
    const m = await browser.measure(html);
    report.attempts.push({ candidate, measurement: m });
    return m;
  };
  type Rung = "drop_callout" | "headline_short" | "body_step";
  const canApply = (p: Placement, rung: Rung): boolean => {
    const story = byId.get(p.story_id)!;
    if (rung === "drop_callout") return p.callout_index !== null;
    if (rung === "headline_short") return p.headline_variant === "headline" && !!story.copy.headline_short;
    if (rung === "body_step") return lowerVariant(story, p.copy_variant) !== null;
    return false;
  };
  /** Apply the first rung the story can take, in the given order. */
  const repair = (p: Placement, rungs: Rung[]): boolean => {
    const story = byId.get(p.story_id)!;
    const rung = rungs.find((r) => canApply(p, r));
    if (rung === "drop_callout") {
      plan.dropped_callouts.push({ story_id: story.id, index: p.callout_index!, reason: "overflow" });
      record(p.slot, story.id, "drop_callout", p.callout_index, null);
      p.callout_index = null;
    } else if (rung === "headline_short") {
      record(p.slot, story.id, "headline_short", "headline", "headline_short");
      p.headline_variant = "headline_short";
    } else if (rung === "body_step") {
      const lower = lowerVariant(story, p.copy_variant);
      record(p.slot, story.id, "body_variant", p.copy_variant, lower);
      p.copy_variant = lower;
    } else return false;
    return true;
  };
  const OWN: Rung[] = ["drop_callout", "headline_short", "body_step"];
  const tallest = (m: Measurement, rungs: Rung[], includeLead = false): Placement | undefined =>
    [...placements]
      .filter((p) => includeLead || p.role_as_placed !== "lead")
      .sort((a, b) => m.slots[b.slot]!.natural_px - m.slots[a.slot]!.natural_px)
      .find((p) => rungs.some((r) => canApply(p, r)));
  for (;;) {
    measurement = await measure(placements);
    if (measurement.fits) break;
    const failing =
      placements.find((p) => p.slot !== "lead" && measurement!.slots[p.slot]?.clipped) ??
      placements.find((p) => measurement!.slots[p.slot]?.clipped);
    if (!failing) throw fail("fit_failed_layout", "a non-story region overflows the page", { measurement });
    const story = byId.get(failing.story_id)!;
    const slotInfo = measurement.slots[failing.slot]!;
    if (failing.role_as_placed === "lead") {
      // A clipped lead means the page is too full. Drop the tallest stories' callouts, demote
      // secondaries that carry a brief fallback, omit optional stories, take the lead's short headline,
      // then trim the tallest remaining story's headline and body.
      const calloutVictim = tallest(measurement, ["drop_callout"], true);
      if (calloutVictim && repair(calloutVictim, ["drop_callout"])) continue;
      if (demote()) {
        placements = settle();
        continue;
      }
      if (omit("overflow")) {
        placements = settle();
        continue;
      }
      if (repair(failing, ["headline_short"])) continue;
      const victim = tallest(measurement, OWN);
      if (victim && repair(victim, OWN)) continue;
    } else if (repair(failing, OWN)) {
      continue;
    } else if (
      failing.role_as_placed === "secondary" && story.fallback_role && edition.fit_policy.allow_role_fallback
    ) {
      roles.set(story.id, "brief");
      record(failing.slot, story.id, "fallback_role", "secondary", "brief");
      state.delete(story.id);
      placements = settle();
      continue;
    } else if (story.device_participation === "optional") {
      active = active.filter((s) => s.id !== story.id);
      plan.omitted.push({ story_id: story.id, reason: "overflow" });
      record(failing.slot, story.id, "omit_story", "placed", "overflow");
      placements = settle();
      continue;
    }
    throw fail("fit_failed_required_story", "a required story cannot be placed at any supplied length", {
      slot: failing.slot,
      story_id: story.id,
      overflow_px: Math.max(0, slotInfo.content_px - slotInfo.available_px),
      measurement: slotInfo,
    });
  }

  // Restoration. The greedy ladder can strip more than the page needed, so put things back one at a
  // time and keep each only if the page still fits: omitted optional stories most prominent first,
  // then reserves in their declared order, then dropped callouts in story order.
  let base = { placements, html, measurement: measurement!, active: [...active], plan: structuredClone(plan) };
  const commit = (m: Measurement) => {
    base = { placements, html, measurement: m, active: [...active], plan: structuredClone(plan) };
  };
  const revert = () => {
    placements = base.placements;
    html = base.html;
    active = [...base.active];
    plan.placements = base.plan.placements;
    plan.omitted = base.plan.omitted;
    plan.dropped_callouts = base.plan.dropped_callouts;
  };
  const tryStory = async (id: string): Promise<boolean> => {
    const story = byId.get(id)!;
    active = edition.stories.filter((s) => base.active.some((a) => a.id === s.id) || s.id === id);
    plan.omitted = plan.omitted.filter((o) => o.story_id !== id);
    const attempt = place();
    while (attempt) {
      placements = attempt;
      const m = await measure(attempt);
      if (m.fits) {
        record(null, id, "restore_story", "omitted", "placed");
        commit(m);
        return true;
      }
      // Only the story being added may be repaired; nothing already placed changes.
      const own = attempt.find((p) => p.story_id === id)!;
      if (!repair(own, OWN)) break;
    }
    state.delete(id);
    revert();
    return false;
  };
  // Demoted secondaries first: give each its role back if the counts allow and the page still fits.
  for (const story of edition.stories) {
    if (candidate >= MAX_CANDIDATES) break;
    if (roles.get(story.id) !== "brief" || !placements.some((p) => p.story_id === story.id)) continue;
    roles.delete(story.id);
    state.delete(story.id);
    const attempt = place();
    if (attempt) placements = attempt;
    const m = attempt ? await measure(attempt) : null;
    if (m?.fits) {
      record(null, story.id, "restore_role", "brief", "secondary");
      plan.dropped_callouts = plan.dropped_callouts.filter((d) => d.story_id !== story.id);
      commit(m);
    } else {
      roles.set(story.id, "brief");
      state.delete(story.id);
      revert();
    }
  }
  const candidates = [
    ...edition.stories.filter(
      (s) => s.device_participation === "optional" && plan.omitted.some((o) => o.story_id === s.id),
    ),
    ...edition.fit_policy.reserve_story_ids.map((id) => byId.get(id)!),
  ];
  for (const story of candidates) {
    if (candidate >= MAX_CANDIDATES) break;
    if (!(await tryStory(story.id))) {
      if (story.device_participation === "reserve") {
        plan.omitted.push({ story_id: story.id, reason: "reserve_did_not_fit" });
        record(null, story.id, "reserve_rejected", "tried", "discarded");
      }
    }
  }
  for (const dropped of [...plan.dropped_callouts]) {
    if (candidate >= MAX_CANDIDATES) break;
    const p = placements.find((x) => x.story_id === dropped.story_id);
    if (!p || p.callout_index !== null || p.role_as_placed === "brief") continue;
    p.callout_index = dropped.index;
    plan.dropped_callouts = plan.dropped_callouts.filter((d) => d !== dropped);
    const m = await measure(placements);
    if (m.fits) {
      record(p.slot, p.story_id, "restore_callout", null, dropped.index);
      commit(m);
    } else {
      p.callout_index = null;
      revert();
    }
  }
  plan.placements = base.placements;
  html = base.html;
  measurement = base.measurement;
  for (const s of edition.stories) {
    if (!plan.placements.some((p) => p.story_id === s.id) && !plan.omitted.some((o) => o.story_id === s.id)) {
      plan.omitted.push({ story_id: s.id, reason: "not_attempted" });
    }
  }
  report.status = "fit";
  return { plan, html, measurement, report };
}
