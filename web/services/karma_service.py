"""Karma (CostumeLotteryEffect) options builder.

Each SSR costume has 3 karma slots. Each slot points at a
`CostumeLotteryEffectOddsGroupId`; the group contains 15-18 entries (one
`OddsNumber` per pickable effect). lunar-tear's `DrawLotteryEffect` rolls
randomly inside the group; `fill_karma_slots` here lets the player pick a
specific effect per slot.

Slot 1 = StatusUp effects (HP / Atk / Def / Agi / CritDmg / Pen combos).
Slots 2 + 3 = Ability effects (damage modifiers, skill cooldown, element
defense, etc.). Each slot has multiple distinct odds groups across different
costumes — picking one effect won't necessarily match every costume's group,
so the shim falls back to "pick the rarest available" when a costume's group
does not contain the user's chosen effect.

This module is responsible for:
  - Loading the master-data tables and ability text bundle.
  - Producing readable labels for every (effect_type, target_id) that
    appears in any odds group.
  - Returning per-slot option lists for the Upgrade Manager template.
  - Computing sensible default selections that approximate the player's
    preferences (favors CritDmg-heavy slot-1, chain/HP-conditional damage
    slot-2, "Damage up by 25% when HP > 70%" slot-3).
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from web import config


# StatusKindType -> short label for the UI dropdowns. Authoritative source:
# lunar-tear/server/internal/model/status.go. The earlier guesses (1=HP etc.)
# were wrong; the in-game UI showed effects that didn't match our labels
# until this was corrected.
_STATUS_KIND: dict[int, str] = {
    1: "Agi",       # StatusKindTypeAgility
    2: "Atk",       # StatusKindTypeAttack
    3: "CritDmg",   # StatusKindTypeCriticalAttack (game label: "Critical Damage")
    4: "CritRate",  # StatusKindTypeCriticalRatio  (game label: "Critical Rate")
    5: "Eva",       # StatusKindTypeEvasionRatio
    6: "HP",        # StatusKindTypeHp
    7: "Def",       # StatusKindTypeVitality       (game label: "Defense")
}


@dataclass(frozen=True)
class KarmaOption:
    slot: int
    effect_type: int
    target_id: int
    rarity: int
    label: str
    group_count: int  # how many distinct odds groups include this option


@dataclass(frozen=True)
class KarmaPoolEntry:
    """One entry in a costume slot's odds pool. The label/rarity come from
    the master data; odds_number is the value lunar-tear writes when the
    player rolls that effect."""
    odds_number: int
    effect_type: int
    target_id: int
    rarity: int
    label: str


# Cached on first call. Cleared if the masterdata files change (rare —
# they only change when setup.bat re-dumps).
_options_cache: dict[int, list[KarmaOption]] | None = None
_defaults_cache: dict[int, tuple[int, int]] | None = None
_pool_cache: dict[int, list[KarmaPoolEntry]] | None = None
_costume_slot_group_cache: dict[int, dict[int, int]] | None = None


def _load_text_by_text_id() -> dict[int, str]:
    """Map ability description text id -> long English description string.

    The bundle key is `ability.description.long.<TextId>`. Reuses
    tools/extract_names.py's bundle reader so we don't duplicate the
    binary parse. Cached internally by extract_names.
    """
    tools_dir = config.ROOT / "tools"
    if str(tools_dir) not in sys.path:
        sys.path.insert(0, str(tools_dir))
    import extract_names  # type: ignore[import-not-found]

    # Resolve the text root the same way extract_names does, so this keeps
    # working across both lunar-tear layouts and platform-nested revisions.
    revisions_dir = config.REVISIONS_DIR
    if not revisions_dir.is_dir():
        revisions_dir = extract_names.DEFAULT_REVISIONS_DIR
    roots = extract_names.available_text_roots(revisions_dir)
    if not roots:
        return {}
    text_root = roots[-1][1]
    entries = extract_names.load_bundle_entries(text_root, "ability", [""])
    out: dict[int, str] = {}
    prefix = "ability.description.long."
    for key, value in entries.items():
        if not key.startswith(prefix):
            continue
        try:
            tid = int(key[len(prefix):])
        except ValueError:
            continue
        out[tid] = value
    return out


def _build_ability_resolver() -> "callable":
    """Return a callable resolve(ability_id, level) -> description string.

    The karma target table stores (AbilityId, AbilityLevel). The actual
    description text comes from the chain:
      AbilityId (= AbilityLevelGroupId)
        -> EntityMAbilityLevelGroupTable: pick row with highest
           LevelLowerLimit <= AbilityLevel
        -> AbilityDetailId
        -> EntityMAbilityDetailTable: DescriptionAbilityTextId
        -> ability.description.long.<TextId> in the bundle

    Earlier code skipped the level-group hop and read the description by
    AbilityId directly, which only worked for L1 entries. The dropdown
    labels were wrong for L2/L3 effects (which is what most karma rolls
    actually are — R30=L2, R40=L3).
    """
    md = config.MASTERDATA_DIR
    level_group_rows = _load_json(md / "EntityMAbilityLevelGroupTable.json")
    detail_rows = _load_json(md / "EntityMAbilityDetailTable.json")
    text_by_text_id = _load_text_by_text_id()

    # group_id -> sorted [(LowerLimit, DetailId)]
    by_group: dict[int, list[tuple[int, int]]] = {}
    for r in level_group_rows:
        gid = int(r["AbilityLevelGroupId"])
        by_group.setdefault(gid, []).append((int(r["LevelLowerLimit"]), int(r["AbilityDetailId"])))
    for gid, rows in by_group.items():
        rows.sort()

    detail_by_id: dict[int, dict] = {int(r["AbilityDetailId"]): r for r in detail_rows}

    def resolve(ability_id: int, level: int) -> str:
        rows = by_group.get(ability_id)
        if not rows:
            return f"Ability {ability_id} L{level}"
        best_detail = rows[0][1]
        for lower, did in rows:
            if lower <= level:
                best_detail = did
            else:
                break
        detail = detail_by_id.get(best_detail)
        if detail is None:
            return f"Ability {ability_id} L{level}"
        text_id = int(detail.get("DescriptionAbilityTextId", 0) or 0)
        text = text_by_text_id.get(text_id)
        if not text:
            return f"Ability {ability_id} L{level} (text {text_id})"
        return text

    return resolve


def _load_json(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"missing masterdata file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


_KINDS_DISPLAYED_AS_PERCENT: frozenset[int] = frozenset({3, 4, 5})  # CritDmg, CritRate, Eva — stored flat but shown as % in-game


def _format_status_value(kind: int, calc: int, value: int) -> str:
    """Match the in-game display: HP/Atk/Def use calc=2 (pct, value/10);
    CritDmg/CritRate/Eva are stored flat but display as percent (value/10);
    Agi displays flat. The user's experimental confirmation is:
      tid=100273 (HP pct=200, Def pct=200) -> in-game "HP 20% / Defense 20%"
      tid=100063 (Agi flat=150, Atk pct=200) -> in-game "Attack 20% / Agility 150"
    """
    label = _STATUS_KIND.get(kind, f"K{kind}")
    if calc == 2 or kind in _KINDS_DISPLAYED_AS_PERCENT:
        pct = value / 10
        return f"{label}+{pct:g}%"
    return f"{label}+{value}"


def _build_status_label(rows: list[dict]) -> str:
    parts: list[str] = []
    def sort_key(r):
        kind = _STATUS_KIND.get(int(r["StatusKindType"]), f"K{r['StatusKindType']}")
        return kind
    for r in sorted(rows, key=sort_key):
        parts.append(_format_status_value(
            int(r["StatusKindType"]),
            int(r["StatusCalculationType"]),
            int(r["EffectValue"]),
        ))
    return " / ".join(parts) or "(empty)"


def _build_options() -> dict[int, list[KarmaOption]]:
    """Construct the per-slot option list. Cached after first call."""
    global _options_cache
    if _options_cache is not None:
        return _options_cache

    md = config.MASTERDATA_DIR
    odds = _load_json(md / "EntityMCostumeLotteryEffectOddsGroupTable.json")
    effects = _load_json(md / "EntityMCostumeLotteryEffectTable.json")
    status = _load_json(md / "EntityMCostumeLotteryEffectTargetStatusUpTable.json")
    abilities = _load_json(md / "EntityMCostumeLotteryEffectTargetAbilityTable.json")
    resolve_ability = _build_ability_resolver()

    # Group -> slot
    group_to_slot: dict[int, int] = {
        int(r["CostumeLotteryEffectOddsGroupId"]): int(r["SlotNumber"])
        for r in effects
    }

    # StatusUpId -> [rows] (one effect can stack multiple stats).
    status_by_target: dict[int, list[dict]] = {}
    for r in status:
        tid = int(r["CostumeLotteryEffectTargetStatusUpId"])
        status_by_target.setdefault(tid, []).append(r)

    # AbilityTargetId -> (AbilityId, AbilityLevel)
    ability_by_target: dict[int, tuple[int, int]] = {
        int(r["CostumeLotteryEffectTargetAbilityId"]): (int(r["AbilityId"]), int(r["AbilityLevel"]))
        for r in abilities
    }

    # (slot, effect_type, target_id) -> (label, rarity, group_set)
    seen: dict[tuple[int, int, int], dict] = {}
    for row in odds:
        gid = int(row["CostumeLotteryEffectOddsGroupId"])
        slot = group_to_slot.get(gid)
        if slot is None:
            continue
        et = int(row["CostumeLotteryEffectType"])
        tid = int(row["CostumeLotteryEffectTargetId"])
        rar = int(row["RarityType"])
        key = (slot, et, tid)
        if key not in seen:
            if et == 2:
                label = _build_status_label(status_by_target.get(tid, []))
            else:
                ab_id, ab_lvl = ability_by_target.get(tid, (0, 0))
                label = resolve_ability(ab_id, ab_lvl)
            seen[key] = {"label": label, "rarity": rar, "groups": set()}
        seen[key]["groups"].add(gid)

    by_slot: dict[int, list[KarmaOption]] = {1: [], 2: [], 3: []}
    for (slot, et, tid), info in seen.items():
        by_slot.setdefault(slot, []).append(KarmaOption(
            slot=slot,
            effect_type=et,
            target_id=tid,
            rarity=info["rarity"],
            label=info["label"],
            group_count=len(info["groups"]),
        ))

    # Sort each slot: highest rarity first, then most-popular (more groups
    # carrying it) first, then label alphabetically. The dropdown user-facing
    # order matches this — they see the rarest, most universally available
    # options at the top.
    for slot, opts in by_slot.items():
        opts.sort(key=lambda o: (-o.rarity, -o.group_count, o.label.lower()))

    _options_cache = by_slot
    return by_slot


def get_karma_options() -> dict[int, list[KarmaOption]]:
    """Public accessor — cached after first call."""
    return _build_options()


def _build_pools_and_costume_index() -> tuple[dict[int, list[KarmaPoolEntry]], dict[int, dict[int, int]]]:
    """Group_id -> sorted entries; costume_id -> slot -> group_id.

    The costume editor renders one dropdown per (costume, slot). Two
    costumes that share an odds group share the option list, so the JS
    payload references group_id rather than embedding the same options
    repeatedly.
    """
    global _pool_cache, _costume_slot_group_cache
    if _pool_cache is not None and _costume_slot_group_cache is not None:
        return _pool_cache, _costume_slot_group_cache

    md = config.MASTERDATA_DIR
    odds = _load_json(md / "EntityMCostumeLotteryEffectOddsGroupTable.json")
    effects = _load_json(md / "EntityMCostumeLotteryEffectTable.json")
    status = _load_json(md / "EntityMCostumeLotteryEffectTargetStatusUpTable.json")
    abilities = _load_json(md / "EntityMCostumeLotteryEffectTargetAbilityTable.json")
    resolve_ability = _build_ability_resolver()

    status_by_target: dict[int, list[dict]] = {}
    for r in status:
        tid = int(r["CostumeLotteryEffectTargetStatusUpId"])
        status_by_target.setdefault(tid, []).append(r)
    ability_by_target: dict[int, tuple[int, int]] = {
        int(r["CostumeLotteryEffectTargetAbilityId"]): (int(r["AbilityId"]), int(r["AbilityLevel"]))
        for r in abilities
    }

    pools: dict[int, list[KarmaPoolEntry]] = {}
    for row in odds:
        gid = int(row["CostumeLotteryEffectOddsGroupId"])
        et = int(row["CostumeLotteryEffectType"])
        tid = int(row["CostumeLotteryEffectTargetId"])
        if et == 2:
            label = _build_status_label(status_by_target.get(tid, []))
        else:
            ab_id, ab_lvl = ability_by_target.get(tid, (0, 0))
            label = resolve_ability(ab_id, ab_lvl)
        pools.setdefault(gid, []).append(KarmaPoolEntry(
            odds_number=int(row["OddsNumber"]),
            effect_type=et,
            target_id=tid,
            rarity=int(row["RarityType"]),
            label=label,
        ))
    # Sort each pool: rarity desc, then odds_number asc (stable).
    for gid, pool in pools.items():
        pool.sort(key=lambda e: (-e.rarity, e.odds_number))

    costume_slots: dict[int, dict[int, int]] = {}
    for r in effects:
        cid = int(r["CostumeId"])
        slot = int(r["SlotNumber"])
        gid = int(r["CostumeLotteryEffectOddsGroupId"])
        costume_slots.setdefault(cid, {})[slot] = gid

    _pool_cache = pools
    _costume_slot_group_cache = costume_slots
    return pools, costume_slots


def get_pools() -> dict[int, list[KarmaPoolEntry]]:
    """Group_id -> sorted [KarmaPoolEntry]."""
    pools, _ = _build_pools_and_costume_index()
    return pools


def get_costume_slot_groups() -> dict[int, dict[int, int]]:
    """costume_id -> slot_number -> odds_group_id."""
    _, costume_slots = _build_pools_and_costume_index()
    return costume_slots


def resolve_odds_number(costume_id: int, slot: int, effect_type: int, target_id: int) -> int | None:
    """Return the OddsNumber for the given (costume, slot, effect_type,
    target_id) or None if no entry matches.

    The costume editor sends (effect_type, target_id) pairs from the
    dropdown values; this helper converts those into the lunar-tear-native
    OddsNumber that goes into user_costume_lottery_effects.
    """
    pools, costume_slots = _build_pools_and_costume_index()
    gid = costume_slots.get(costume_id, {}).get(slot)
    if gid is None:
        return None
    pool = pools.get(gid, [])
    for entry in pool:
        if entry.effect_type == effect_type and entry.target_id == target_id:
            return entry.odds_number
    return None


# Default-preference resolution. Maps to the user's stated wishlist now that
# labels are accurate (StatusKindType corrected, ability descriptions resolve
# through the level-group chain):
#   slot 1: "Atk+20% / CritDmg+20%"  -> tid=100093 (R40, 1 group)
#           Each group has a different stat-pair pool, so most costumes
#           fall back to "rarest" — that's expected; only ~1/8 of slot-1
#           pools carry this exact combo. Costume Editor lets the player
#           override per-costume.
#   slot 2: "Damage up by 30% on chain attacks of 3 or more." -> tid=800273
#           (R40, 7 groups). Status-duration extension also scored well
#           ("Extends the duration of status-boosting effects you use by
#           15 seconds." -> tid=800513, 25 groups) but chain attack damage
#           is the user's stated top pick.
#   slot 3: "Skill cooldown time reduced by 30%." -> tid=800543 (R40, 50
#           groups — universal across slot-3 pools).
_DEFAULT_PREFERENCES: dict[int, tuple[int, int]] = {
    1: (2, 100093),
    2: (1, 800273),
    3: (1, 800543),
}


def compute_default_preferences() -> dict[int, tuple[int, int]]:
    """Return the default (effect_type, target_id) per slot, validated
    against what actually exists in the master data so a typo here doesn't
    crash the page.
    """
    global _defaults_cache
    if _defaults_cache is not None:
        return _defaults_cache
    options = get_karma_options()
    out: dict[int, tuple[int, int]] = {}
    for slot, default in _DEFAULT_PREFERENCES.items():
        slot_opts = options.get(slot, [])
        match = next(
            (o for o in slot_opts if (o.effect_type, o.target_id) == default),
            None,
        )
        if match is None and slot_opts:
            # Fallback to the slot's first option (which is the highest
            # rarity, highest popularity entry).
            match = slot_opts[0]
            out[slot] = (match.effect_type, match.target_id)
        elif match is not None:
            out[slot] = (match.effect_type, match.target_id)
    _defaults_cache = out
    return out
