#!/usr/bin/env python3



from __future__ import annotations

import argparse
import json
import os
import struct
import sys
from pathlib import Path
from typing import Any

try:
    import lz4.block
except ImportError as exc:  # pragma: no cover - import guard
    raise SystemExit("missing dependency: python package 'lz4' is required") from exc


SCRIPT_DIR = Path(__file__).resolve().parent
LUNAR_BASE_ROOT = SCRIPT_DIR.parent
DEFAULT_MASTER_DATA_DIR = (LUNAR_BASE_ROOT / "data" / "masterdata").resolve()
def _lunar_tear_roots() -> list[Path]:
    """Candidate Lunar Tear directories, most explicit first.

    Mirrors web/config.detect_lunar_tear_dir() without importing it, so
    this script stays runnable standalone. The install need not be at
    ../lunar-tear: release archives unpack under names like
    lunar-tear-server-v1.0.0-linux-amd64.
    """
    candidates: list[Path] = []

    from_env = os.environ.get("LUNAR_TEAR_DIR")
    if from_env:
        candidates.append(Path(from_env).expanduser())

    settings = LUNAR_BASE_ROOT / ".lunar-base.json"
    try:
        saved = json.loads(settings.read_text(encoding="utf-8")).get("lunar_tear_dir")
        if saved:
            candidates.append(Path(saved).expanduser())
    except (json.JSONDecodeError, OSError, AttributeError):
        pass

    candidates.append(LUNAR_BASE_ROOT.parent / "lunar-tear")

    try:
        for sibling in sorted(LUNAR_BASE_ROOT.parent.iterdir()):
            if sibling.is_dir() and sibling.resolve() != LUNAR_BASE_ROOT.resolve():
                candidates.append(sibling)
    except OSError:
        pass

    return candidates


def _default_revisions_dir() -> Path:
    """Locate lunar-tear's revisions tree.

    A source checkout nests assets under lunar-tear/server/; the prebuilt
    release keeps them flat at lunar-tear/assets/.
    """
    for root in _lunar_tear_roots():
        for candidate in (
            root / "server" / "assets" / "revisions",
            root / "assets" / "revisions",
        ):
            if candidate.is_dir():
                return candidate.resolve()
    return (LUNAR_BASE_ROOT.parent / "lunar-tear" / "assets" / "revisions").resolve()


DEFAULT_REVISIONS_DIR = _default_revisions_dir()
DEFAULT_OUTPUT_DIR = (LUNAR_BASE_ROOT / "data" / "names").resolve()
DEFAULT_TEXT_REVISION = "auto"

_BUNDLE_ENTRY_CACHE: dict[tuple[str, str, tuple[str, ...]], dict[str, str]] = {}


KIND_CONFIG: dict[str, dict[str, Any]] = {
    "materials": {
        "bundle_key": "material",
        "bundle_dirs": ["possession"],
        "master_data_file": "EntityMMaterialTable.json",
        "id_field": "MaterialId",
        "fallback_prefix": "Material",
        "extra_fields": [
            "MaterialType",
            "RarityType",
            "WeaponType",
            "AttributeType",
            "EffectValue",
            "SellPrice",
            "MaterialSaleObtainPossessionId",
        ],
    },
    "consumables": {
        "bundle_key": "consumable_item",
        "bundle_dirs": ["possession"],
        "master_data_file": "EntityMConsumableItemTable.json",
        "id_field": "ConsumableItemId",
        "fallback_prefix": "Consumable",
        "extra_fields": [
            "ConsumableItemType",
            "ConsumableItemTermId",
            "SortOrder",
            "SellPrice",
        ],
    },
    "weapons": {
        "bundle_key": "weapon",
        "bundle_dirs": ["possession"],
        "master_data_file": "EntityMWeaponTable.json",
        "id_field": "WeaponId",
        "fallback_prefix": "Weapon",
        "extra_fields": [
            "WeaponCategoryType",
            "WeaponType",
            "AssetVariationId",
            "RarityType",
            "AttributeType",
            "WeaponBaseStatusId",
            "WeaponStatusCalculationId",
            "WeaponSkillGroupId",
            "WeaponAbilityGroupId",
            "WeaponEvolutionMaterialGroupId",
            "WeaponEvolutionGrantPossessionGroupId",
            "WeaponStoryReleaseConditionGroupId",
            "WeaponSpecificEnhanceId",
            "WeaponSpecificLimitBreakMaterialGroupId",
            "CharacterWalkaroundRangeType",
            "IsRestrictDiscard",
            "IsRecyclable",
        ],
    },
    "characters": {
        "bundle_key": "character",
        "bundle_dirs": [""],
        "master_data_file": "EntityMCharacterTable.json",
        "id_field": "CharacterId",
        "fallback_prefix": "Character",
        "extra_fields": [
            "CharacterAssetId",
            "CharacterLevelBonusAbilityGroupId",
            "NameCharacterTextId",
            "SortOrder",
            "DefaultCostumeId",
            "DefaultWeaponId",
            "EndCostumeId",
            "EndWeaponId",
            "MaxLevelNumericalFunctionId",
            "RequiredExpForLevelUpNumericalParameterMapId",
            "ListSettingCostumeGroupType",
            "ListSettingDisplayStartDatetime",
        ],
    },
    "costumes": {
        "bundle_key": "costume",
        "bundle_dirs": ["possession"],
        "master_data_file": "EntityMCostumeTable.json",
        "id_field": "CostumeId",
        "fallback_prefix": "Costume",
        "extra_fields": [
            "CharacterId",
            "ActorId",
            "CostumeAssetCategoryType",
            "ActorSkeletonId",
            "AssetVariationId",
            "SkillfulWeaponType",
            "RarityType",
            "CostumeBaseStatusId",
            "CostumeStatusCalculationId",
            "CostumeLimitBreakMaterialGroupId",
            "CostumeAbilityGroupId",
            "CostumeActiveSkillGroupId",
            "CounterSkillDetailId",
            "CharacterMoverBattleActorAiId",
            "CostumeDefaultSkillGroupId",
            "CostumeLevelBonusId",
            "DefaultActorSkillAiId",
            "CostumeEmblemAssetId",
            "BattleActorSkillAiGroupId",
        ],
    },
    "companions": {
        "bundle_key": "companion",
        "bundle_dirs": ["possession"],
        "master_data_file": "EntityMCompanionTable.json",
        "id_field": "CompanionId",
        "fallback_prefix": "Companion",
        "extra_fields": [
            "AttributeType",
            "CompanionCategoryType",
            "CompanionBaseStatusId",
            "CompanionStatusCalculationId",
            "SkillId",
            "CompanionAbilityGroupId",
            "ActorId",
            "ActorSkeletonId",
            "AssetVariationId",
            "CharacterMoverBattleActorAiId",
        ],
    },
    "thoughts": {
        "bundle_key": "thought",
        "bundle_dirs": ["possession"],
        "master_data_file": "EntityMThoughtTable.json",
        "id_field": "ThoughtId",
        "fallback_prefix": "Thought",
        "extra_fields": [
            "RarityType",
            "AbilityId",
            "AbilityLevel",
            "ThoughtAssetId",
        ],
    },
    "parts": {
        "bundle_key": "parts",
        "bundle_dirs": ["possession"],
        "master_data_file": "EntityMPartsTable.json",
        "id_field": "PartsId",
        "fallback_prefix": "Part",
        "extra_fields": [
            "RarityType",
            "PartsGroupId",
            "PartsStatusMainLotteryGroupId",
            "PartsStatusSubLotteryGroupId",
            "PartsInitialLotteryId",
        ],
    },
    "abilities": {
        "bundle_key": "ability",
        "bundle_dirs": [""],
        "master_data_file": "m_abiliwy.json",
        "id_field": "AbilityId",
        "fallback_prefix": "Ability",
        "extra_fields": [],
    },
    "skills": {
        "bundle_key": "skill",
        "bundle_dirs": [""],
        "master_data_file": "EntityMSkillTable.json",
        "id_field": "SkillId",
        "fallback_prefix": "Skill",
        "extra_fields": [
            "SkillLevelGroupId",
        ],
    },
    "character_boards": {
        "bundle_key": "character_board",
        "bundle_dirs": [""],
        "master_data_file": "EntityMCharacterBoardTable.json",
        "id_field": "CharacterBoardId",
        "fallback_prefix": "Character Board",
        "extra_fields": [
            "CharacterBoardGroupId",
            "CharacterBoardUnlockConditionGroupId",
            "ReleaseRank",
        ],
    },
    "weapon_skills": {
        "bundle_key": "skill",
        "bundle_dirs": [""],
        "master_data_file": "EntityMWeaponTable.json",
        "id_field": "WeaponId",
        "fallback_prefix": "Weapon Skill",
        "extra_fields": [],
    },
    "weapon_abilities": {
        "bundle_key": "ability",
        "bundle_dirs": [""],
        "master_data_file": "EntityMWeaponTable.json",
        "id_field": "WeaponId",
        "fallback_prefix": "Weapon Ability",
        "extra_fields": [],
    },
    "costume_active_skills": {
        "bundle_key": "skill",
        "bundle_dirs": [""],
        "master_data_file": "EntityMCostumeTable.json",
        "id_field": "CostumeId",
        "fallback_prefix": "Costume Active Skill",
        "extra_fields": [],
    },
    "weapon_stories": {
        "bundle_key": "weapon_story",
        "bundle_dirs": ["possession"],
        "master_data_file": "EntityMWeaponTable.json",
        "id_field": "WeaponId",
        "fallback_prefix": "Weapon Story",
        "extra_fields": [],
    },
    "character_board_abilities": {
        "bundle_key": "ability",
        "bundle_dirs": [""],
        "master_data_file": "EntityMCharacterBoardAbilityTable.json",
        "id_field": "CharacterBoardAbilityId",
        "fallback_prefix": "Character Board Ability",
        "extra_fields": [],
    },
    "character_board_status_ups": {
        "bundle_key": "status",
        "bundle_dirs": [""],
        "master_data_file": "EntityMCharacterBoardStatusUpTable.json",
        "id_field": "CharacterBoardStatusUpId",
        "fallback_prefix": "Character Board Status Up",
        "extra_fields": [],
    },
    "weapon_awakens": {
        "bundle_key": "ability",
        "bundle_dirs": [""],
        "master_data_file": "EntityMWeaponAwakenTable.json",
        "id_field": "WeaponId",
        "fallback_prefix": "Weapon Awaken",
        "extra_fields": [],
    },
    "costume_awaken_status_ups": {
        "bundle_key": "status",
        "bundle_dirs": [""],
        "master_data_file": "EntityMCostumeAwakenTable.json",
        "id_field": "CostumeId",
        "fallback_prefix": "Costume Awaken Status Up",
        "extra_fields": [],
    },
    "costume_awaken_abilities": {
        "bundle_key": "ability",
        "bundle_dirs": [""],
        "master_data_file": "EntityMCostumeAwakenTable.json",
        "id_field": "CostumeId",
        "fallback_prefix": "Costume Awaken Ability",
        "extra_fields": [],
    },
    "important_items": {
        "bundle_key": "important_item",
        "bundle_dirs": ["possession"],
        "master_data_file": "EntityMImportantItemTable.json",
        "id_field": "ImportantItemId",
        "fallback_prefix": "Important Item",
        "extra_fields": [
            "NameImportantItemTextId",
            "DescriptionImportantItemTextId",
            "SortOrder",
            "AssetCategoryId",
            "AssetVariationId",
            "ImportantItemEffectId",
            "ReportId",
            "CageMemoryId",
            "ImportantItemType",
            "ExternalReferenceId",
        ],
    },
    "missions": {
        "bundle_key": "mission",
        "bundle_dirs": [""],
        "master_data_file": "EntityMMissionTable.json",
        "id_field": "MissionId",
        "fallback_prefix": "Mission",
        "extra_fields": [
            "MissionGroupId",
            "SortOrderInMissionGroup",
            "MissionUnlockConditionId",
            "NameMissionTextId",
            "MissionLinkId",
            "MissionClearConditionType",
            "MissionClearConditionGroupId",
            "ClearConditionValue",
            "MissionClearConditionOptionGroupId",
            "MissionRewardId",
            "MissionTermId",
            "RelatedMainFunctionType",
        ],
    },
    "quests": {
        "bundle_key": "quest",
        "bundle_dirs": ["quest"],
        "master_data_file": "EntityMQuestTable.json",
        "id_field": "QuestId",
        "fallback_prefix": "Quest",
        "extra_fields": [
            "NameQuestTextId",
            "PictureBookNameQuestTextId",
            "QuestReleaseConditionListId",
            "StoryQuestTextId",
            "QuestDisplayAttributeGroupId",
            "RecommendedDeckPower",
            "QuestFirstClearRewardGroupId",
            "QuestPickupRewardGroupId",
            "QuestDeckRestrictionGroupId",
            "QuestMissionGroupId",
            "Stamina",
            "UserExp",
            "CharacterExp",
            "CostumeExp",
            "Gold",
            "DailyClearableCount",
            "IsRunInTheBackground",
            "IsCountedAsQuest",
            "QuestBonusId",
            "IsNotShowAfterClear",
            "IsBigWinTarget",
            "IsUsableSkipTicket",
        ],
    },
    "quest_missions": {
        "bundle_key": "quest_mission",
        "bundle_dirs": ["quest"],
        "master_data_file": "EntityMQuestMissionTable.json",
        "id_field": "QuestMissionId",
        "fallback_prefix": "Quest Mission",
        "extra_fields": [
            "QuestMissionConditionType",
            "ConditionValue",
            "QuestMissionRewardId",
            "QuestMissionConditionValueGroupId",
        ],
    },
    "tutorials": {
        "bundle_key": "help",
        "bundle_dirs": [""],
        "master_data_file": "EntityMTutorialUnlockConditionTable.json",
        "id_field": "TutorialType",
        "fallback_prefix": "Tutorial",
        "extra_fields": [],
    },
    "shops": {
        "bundle_key": "shop",
        "bundle_dirs": [""],
        "master_data_file": "EntityMShopTable.json",
        "id_field": "ShopId",
        "fallback_prefix": "Shop",
        "extra_fields": [
            "ShopGroupType",
            "SortOrderInShopGroup",
            "ShopType",
            "NameShopTextId",
            "ShopUpdatableLabelType",
            "ShopExchangeType",
            "ShopItemCellGroupId",
            "RelatedMainFunctionType",
            "StartDatetime",
            "EndDatetime",
            "LimitedOpenId",
        ],
    },
    "shop_items": {
        "bundle_key": "shop",
        "bundle_dirs": [""],
        "master_data_file": "EntityMShopItemTable.json",
        "id_field": "ShopItemId",
        "fallback_prefix": "Shop Item",
        "extra_fields": [
            "NameShopTextId",
            "DescriptionShopTextId",
            "ShopItemContentType",
            "PriceType",
            "PriceId",
            "Price",
            "RegularPrice",
            "ShopPromotionType",
            "ShopItemLimitedStockId",
            "AssetCategoryId",
            "AssetVariationId",
            "ShopItemDecorationType",
        ],
    },
    "gacha_medals": {
        "bundle_key": "consumable_item",
        "bundle_dirs": ["possession"],
        "master_data_file": "EntityMGachaMedalTable.json",
        "id_field": "GachaMedalId",
        "fallback_prefix": "Gacha Medal",
        "extra_fields": [
            "CeilingCount",
            "ConsumableItemId",
            "ShopTransitionGachaId",
            "AutoConvertDatetime",
            "ConversionRate",
        ],
    },
    "gacha_banners": {
        "bundle_key": "gacha_title",
        "bundle_dirs": [""],
        "master_data_file": "EntityMMomBannerTable.json",
        "id_field": "MomBannerId",
        "fallback_prefix": "Gacha Banner",
        "extra_fields": [
            "SortOrderDesc",
            "DestinationDomainType",
            "DestinationDomainId",
            "BannerAssetName",
            "IsEmphasis",
            "StartDatetime",
            "EndDatetime",
            "TargetUserStatusType",
        ],
    },
    "gift_texts": {
        "bundle_key": "gift",
        "bundle_dirs": [""],
        "master_data_file": "EntityMGiftTextTable.json",
        "id_field": "GiftTextId",
        "fallback_prefix": "Gift Text",
        "extra_fields": [],
    },
    "shop_replaceable_gems": {
        "bundle_key": "shop",
        "bundle_dirs": [""],
        "master_data_file": "EntityMShopReplaceableGemTable.json",
        "id_field": "LineupUpdateCountLowerLimit",
        "fallback_prefix": "Shop Replaceable Gem",
        "extra_fields": [
            "NecessaryGem",
        ],
    },
    "premium_items": {
        "bundle_key": "",
        "bundle_dirs": [""],
        "master_data_file": "EntityMPremiumItemTable.json",
        "id_field": "PremiumItemId",
        "fallback_prefix": "Premium Item",
        "extra_fields": [
            "PremiumItemType",
            "StartDatetime",
            "EndDatetime",
        ],
    },
    "character_rebirths": {
        "bundle_key": "character",
        "bundle_dirs": [""],
        "master_data_file": "EntityMCharacterRebirthTable.json",
        "id_field": "CharacterId",
        "fallback_prefix": "Character Rebirth",
        "extra_fields": [],
    },
    "weapon_notes": {
        "bundle_key": "weapon",
        "bundle_dirs": ["possession"],
        "master_data_file": "EntityMWeaponTable.json",
        "id_field": "WeaponId",
        "fallback_prefix": "Weapon Note",
        "extra_fields": [],
    },
    "parts_group_notes": {
        "bundle_key": "parts",
        "bundle_dirs": ["possession"],
        "master_data_file": "EntityMPartsGroupTable.json",
        "id_field": "PartsGroupId",
        "fallback_prefix": "Parts Group Note",
        "extra_fields": [],
    },
    "main_quests": {
        "bundle_key": "main_quest",
        "bundle_dirs": ["quest"],
        "master_data_file": "EntityMMainQuestChapterTable.json",
        "id_field": "MainQuestChapterId",
        "fallback_prefix": "Main Quest",
        "extra_fields": [],
    },
    "event_quests": {
        "bundle_key": "event_quest",
        "bundle_dirs": ["quest"],
        "master_data_file": "EntityMEventQuestChapterTable.json",
        "id_field": "EventQuestChapterId",
        "fallback_prefix": "Event Quest",
        "extra_fields": [],
    },
    "extra_quests": {
        "bundle_key": "quest",
        "bundle_dirs": ["quest"],
        "master_data_file": "EntityMExtraQuestGroupTable.json",
        "id_field": "ExtraQuestId",
        "fallback_prefix": "Extra Quest",
        "extra_fields": [],
    },
    "side_story_quests": {
        "bundle_key": "event_quest",
        "bundle_dirs": ["quest"],
        "master_data_file": "EntityMSideStoryQuestTable.json",
        "id_field": "SideStoryQuestId",
        "fallback_prefix": "Side Story Quest",
        "extra_fields": [],
    },
    "cage_ornament_rewards": {
        "bundle_key": "",
        "bundle_dirs": [""],
        "master_data_file": "EntityMCageOrnamentTable.json",
        "id_field": "CageOrnamentId",
        "fallback_prefix": "Cage Ornament Reward",
        "extra_fields": [],
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract possession IDs and English names from the lunar-tear asset dump.",
    )
    parser.add_argument(
        "--master-data-dir",
        type=Path,
        default=DEFAULT_MASTER_DATA_DIR,
        help=f"directory containing dumped EntityM*.json master-data tables "
             f"(default: {DEFAULT_MASTER_DATA_DIR})",
    )
    parser.add_argument(
        "--revisions-dir",
        type=Path,
        default=DEFAULT_REVISIONS_DIR,
        help=f"directory containing lunar-tear's revisions/<rev>/assetbundle/text/en/ tree "
             f"(default: {DEFAULT_REVISIONS_DIR})",
    )
    parser.add_argument(
        "--revision",
        default=DEFAULT_TEXT_REVISION,
        help="asset revision to read text bundles from, or 'auto' for the newest available text revision (default: auto)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"directory for extracted JSON output (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--kinds",
        nargs="+",
        choices=sorted(KIND_CONFIG),
        default=sorted(KIND_CONFIG),
        help="one or more extractors to run",
    )
    return parser.parse_args()


def load_json_array(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path} does not contain a JSON array")
    return data


def sanitize_output_path(path: Path) -> str:
    return str(path).replace(str(Path.home()), "/home/user")


# Asset dumps come in two shapes. The raw resource_dump archive unpacks as
#   revisions/<rev>/assetbundle/...
# while lunar-tear v1.0.0 expects a platform level:
#   revisions/<rev>/<platform>/assetbundle/...
# Probe the bare form first, then any platform subdirectory.
PLATFORM_DIRS: tuple[str, ...] = ("android", "ios")


def _text_root_for_revision(revision_dir: Path) -> Path | None:
    """Return the English text root inside one revision directory, if present."""
    direct = revision_dir / "assetbundle" / "text" / "en"
    if direct.is_dir():
        return direct

    for platform in PLATFORM_DIRS:
        candidate = revision_dir / platform / "assetbundle" / "text" / "en"
        if candidate.is_dir():
            return candidate

    # Unknown platform name: accept any single child that holds the tree.
    for child in sorted(revision_dir.iterdir()):
        if not child.is_dir():
            continue
        candidate = child / "assetbundle" / "text" / "en"
        if candidate.is_dir():
            return candidate

    return None


def available_text_roots(revisions_dir: Path) -> list[tuple[int, Path]]:
    if not revisions_dir.is_dir():
        return []

    roots: list[tuple[int, Path]] = []
    for revision_dir in revisions_dir.iterdir():
        if not revision_dir.is_dir():
            continue
        try:
            revision = int(revision_dir.name)
        except ValueError:
            continue
        text_root = _text_root_for_revision(revision_dir)
        if text_root is not None:
            roots.append((revision, text_root))

    roots.sort(key=lambda item: item[0])
    return roots


def resolve_text_root(revisions_dir: Path, revision_arg: str) -> Path:
    available_roots = available_text_roots(revisions_dir)
    if not available_roots:
        raise SystemExit(f"no English text asset roots found under: {revisions_dir}")

    normalized = str(revision_arg).strip().lower()
    if normalized in {"", "auto", "latest"}:
        return available_roots[-1][1]

    try:
        requested_revision = int(normalized)
    except ValueError as exc:
        raise SystemExit(f"invalid revision '{revision_arg}': expected an integer or 'auto'") from exc

    for revision, text_root in available_roots:
        if revision == requested_revision:
            return text_root

    available = ", ".join(str(revision) for revision, _text_root in available_roots[:12])
    if len(available_roots) > 12:
        available += ", ..."
    raise SystemExit(
        f"text asset root not found for revision {requested_revision}: "
        f"available revisions with English text are {available}"
    )


def string_to_mask_bytes(mask: str) -> bytes:
    if not mask:
        return b""

    output = bytearray(len(mask) * 2)
    left_index = 0
    right_index = len(output) - 1

    for raw_char in mask.encode("utf-8"):
        output[left_index] = raw_char
        left_index += 2
        output[right_index] = (~raw_char) & 0xFF
        right_index -= 2

    mask_len = 0xBB
    for value in output:
        mask_len = ((((mask_len & 1) << 7) | (mask_len >> 1)) ^ value) & 0xFF

    for index, value in enumerate(output):
        output[index] = value ^ mask_len

    return bytes(output)


def decrypt_text_bundle(buffer: bytes, mask: str) -> bytes:
    if not buffer or buffer[0] not in (0x31, 0x32):
        return buffer

    header_length = 256 if buffer[0] == 0x31 else len(buffer)
    mask_buffer = string_to_mask_bytes(mask)
    if not mask_buffer:
        return buffer

    output = bytearray(buffer)
    for index in range(min(header_length, len(output))):
        output[index] = mask_buffer[index % len(mask_buffer)] ^ buffer[index]
    output[0] = 0x55
    return bytes(output)


class BinaryReader:
    def __init__(self, data: bytes, endian: str = ">") -> None:
        self.data = data
        self.pos = 0
        self.endian = endian

    def read(self, size: int) -> bytes:
        chunk = self.data[self.pos : self.pos + size]
        if len(chunk) != size:
            raise EOFError("unexpected end of buffer")
        self.pos += size
        return chunk

    def unpack(self, fmt: str) -> tuple[Any, ...]:
        return struct.unpack(self.endian + fmt, self.read(struct.calcsize(fmt)))

    def align(self, size: int = 4) -> None:
        self.pos = (self.pos + (size - 1)) & ~(size - 1)

    def cstring(self) -> str:
        end = self.data.index(0, self.pos)
        value = self.data[self.pos:end].decode("utf-8", errors="replace")
        self.pos = end + 1
        return value

    def bool(self) -> bool:
        return bool(self.read(1)[0])

    def uint8(self) -> int:
        return self.read(1)[0]

    def int16(self) -> int:
        return self.unpack("h")[0]

    def uint16(self) -> int:
        return self.unpack("H")[0]

    def int32(self) -> int:
        return self.unpack("i")[0]

    def uint32(self) -> int:
        return self.unpack("I")[0]

    def int64(self) -> int:
        return self.unpack("q")[0]

    def uint64(self) -> int:
        return self.unpack("Q")[0]


def decompress_lz4(data: bytes, expected_size: int) -> bytes:
    try:
        return lz4.block.decompress(data, uncompressed_size=expected_size)
    except lz4.block.LZ4BlockError:
        return lz4.block.decompress(data)


def extract_bundle_streams(bundle: bytes) -> list[bytes]:
    reader = BinaryReader(bundle, ">")
    signature = reader.cstring()
    version = reader.uint32()
    if signature != "UnityFS":
        raise ValueError(f"unsupported bundle signature: {signature}")

    reader.cstring()  # unity version string stored in the bundle header
    reader.cstring()  # unity revision string stored in the bundle header
    reader.int64()  # file size
    compressed_blocks_info_size = reader.uint32()
    uncompressed_blocks_info_size = reader.uint32()
    flags = reader.uint32()

    if version >= 7:
        reader.align(16)

    blocks_info_data = reader.read(compressed_blocks_info_size)
    compression_type = flags & 0x3F
    if compression_type in (2, 3):
        blocks_info_data = decompress_lz4(blocks_info_data, uncompressed_blocks_info_size)
    elif compression_type != 0:
        raise ValueError(f"unsupported blocks info compression type: {compression_type}")

    blocks_info_reader = BinaryReader(blocks_info_data, ">")
    blocks_info_reader.read(16)  # uncompressed data hash

    block_descriptors = []
    for _ in range(blocks_info_reader.uint32()):
        block_descriptors.append(
            (
                blocks_info_reader.uint32(),
                blocks_info_reader.uint32(),
                blocks_info_reader.uint16(),
            )
        )

    nodes = []
    for _ in range(blocks_info_reader.uint32()):
        nodes.append(
            (
                blocks_info_reader.uint64(),
                blocks_info_reader.uint64(),
                blocks_info_reader.uint32(),
                blocks_info_reader.cstring(),
            )
        )

    combined_blocks = bytearray()
    for uncompressed_size, compressed_size, block_flags in block_descriptors:
        block_data = reader.read(compressed_size)
        block_compression_type = block_flags & 0x3F
        if block_compression_type in (2, 3):
            combined_blocks.extend(decompress_lz4(block_data, uncompressed_size))
        elif block_compression_type == 0:
            combined_blocks.extend(block_data)
        else:
            raise ValueError(f"unsupported block compression type: {block_compression_type}")

    combined_bytes = bytes(combined_blocks)
    streams: list[bytes] = []
    for offset, size, _node_flags, _path in nodes:
        start = int(offset)
        end = start + int(size)
        streams.append(combined_bytes[start:end])
    return streams


def skip_serialized_type_tree(reader: BinaryReader, format_version: int) -> None:
    node_count = reader.int32()
    string_buffer_size = reader.int32()
    node_size = 32 if format_version >= 19 else 24
    reader.read(node_count * node_size)
    reader.read(string_buffer_size)


def read_serialized_type_class_id(reader: BinaryReader, format_version: int, is_ref_type: bool) -> int:
    class_id = reader.int32()

    if format_version >= 16:
        reader.bool()

    script_type_index = -1
    if format_version >= 17:
        script_type_index = reader.int16()

    if format_version >= 13:
        if is_ref_type and script_type_index >= 0:
            reader.read(16)
        elif (format_version < 16 and class_id < 0) or (format_version >= 16 and class_id == 114):
            reader.read(16)
        reader.read(16)

    if format_version >= 12 or format_version == 10:
        skip_serialized_type_tree(reader, format_version)
    else:
        raise ValueError(f"unsupported serialized type tree format version: {format_version}")

    if format_version >= 21:
        if is_ref_type:
            reader.cstring()
            reader.cstring()
            reader.cstring()
        else:
            dependency_count = reader.int32()
            reader.read(dependency_count * 4)

    return class_id


def extract_text_assets(serialized_file: bytes) -> list[tuple[str, str]]:
    reader = BinaryReader(serialized_file, ">")
    _metadata_size = reader.uint32()
    _file_size = reader.uint32()
    format_version = reader.uint32()
    data_offset = reader.uint32()

    if format_version < 9:
        raise ValueError(f"unsupported serialized file version: {format_version}")

    endianess = reader.uint8()
    reader.read(3)

    if format_version >= 22:
        _metadata_size = reader.uint32()
        _file_size = reader.int64()
        data_offset = reader.int64()
        reader.int64()

    reader.endian = "<" if endianess == 0 else ">"

    if format_version >= 7:
        reader.cstring()
    if format_version >= 8:
        reader.int32()
    if format_version >= 13:
        reader.bool()

    class_ids: list[int] = []
    for _ in range(reader.int32()):
        class_ids.append(read_serialized_type_class_id(reader, format_version, is_ref_type=False))

    if 7 <= format_version < 14:
        big_id_enabled = reader.int32()
    else:
        big_id_enabled = 0

    objects: list[tuple[int, int]] = []
    for _ in range(reader.int32()):
        if big_id_enabled != 0:
            reader.int64()
        elif format_version < 14:
            reader.int32()
        else:
            reader.align()
            reader.int64()

        byte_start = reader.int64() if format_version >= 22 else reader.uint32()
        byte_size = reader.uint32()
        type_id = reader.int32()

        if format_version < 16:
            class_id = reader.uint16()
        else:
            class_id = class_ids[type_id]

        if format_version < 11:
            reader.uint16()
        if 11 <= format_version < 17:
            reader.int16()
        if format_version in (15, 16):
            reader.uint8()

        if class_id == 49:
            objects.append((int(byte_start + data_offset), int(byte_size)))

    if format_version >= 11:
        for _ in range(reader.int32()):
            reader.int32()
            if format_version < 14:
                reader.int32()
            else:
                reader.align()
                reader.int64()

    for _ in range(reader.int32()):
        if format_version >= 6:
            reader.cstring()
        if format_version >= 5:
            reader.read(16)
            reader.int32()
        reader.cstring()

    if format_version >= 20:
        for _ in range(reader.int32()):
            read_serialized_type_class_id(reader, format_version, is_ref_type=True)

    if format_version >= 5:
        reader.cstring()

    text_assets: list[tuple[str, str]] = []
    object_reader = BinaryReader(serialized_file, "<" if endianess == 0 else ">")
    for byte_start, _byte_size in objects:
        object_reader.pos = byte_start
        name = object_reader.read(object_reader.int32()).decode("utf-8", errors="replace")
        object_reader.align()
        text = object_reader.read(object_reader.int32()).decode("utf-8", errors="replace")
        text_assets.append((name, text))

    return text_assets


def text_bundle_mask(text_root: Path, file_path: Path) -> str:
    relative_path = file_path.relative_to(text_root).with_suffix("")
    return "text)en)" + ")".join(relative_path.parts)


def parse_text_asset_lines(text: str) -> dict[str, str]:
    entries: dict[str, str] = {}
    for raw_line in text.replace("\r\n", "\n").split("\n"):
        line = raw_line.strip()
        if not line or line.startswith("//"):
            continue
        separator = line.find(":")
        if separator <= 0:
            continue
        entries[line[:separator]] = line[separator + 1 :]
    return entries


def candidate_bundle_dirs(text_root: Path, bundle_key: str, bundle_dirs: list[str] | None = None) -> list[Path]:
    requested_dirs = bundle_dirs[:] if bundle_dirs else []
    if not requested_dirs:
        requested_dirs = [""]

    # Probe likely sibling roots first, then auto-discover any other top-level
    # text folders that actually contain the requested bundle key.
    likely_dirs = ["", "possession"]
    for value in likely_dirs:
        if value not in requested_dirs:
            requested_dirs.append(value)

    for child in sorted(text_root.iterdir()):
        if not child.is_dir():
            continue
        relative_dir = child.relative_to(text_root).as_posix()
        bundle_file = child / f"{bundle_key}.assetbundle"
        bundle_folder = child / bundle_key
        if (bundle_file.exists() or bundle_folder.is_dir()) and relative_dir not in requested_dirs:
            requested_dirs.append(relative_dir)

    roots: list[Path] = []
    seen: set[Path] = set()
    for bundle_dir in requested_dirs:
        bundle_root = text_root / bundle_dir if bundle_dir else text_root
        bundle_file = bundle_root / f"{bundle_key}.assetbundle"
        bundle_folder = bundle_root / bundle_key
        if bundle_file.exists() or bundle_folder.is_dir():
            if bundle_root not in seen:
                roots.append(bundle_root)
                seen.add(bundle_root)
    return roots


def load_bundle_entries(text_root: Path, bundle_key: str, bundle_dirs: list[str] | None = None) -> dict[str, str]:
    cache_key = (
        str(text_root.resolve()),
        bundle_key,
        tuple(bundle_dirs or ()),
    )
    cached = _BUNDLE_ENTRY_CACHE.get(cache_key)
    if cached is not None:
        return dict(cached)

    entries: dict[str, str] = {}
    for bundle_root in candidate_bundle_dirs(text_root, bundle_key, bundle_dirs):
        bundle_files = [bundle_root / f"{bundle_key}.assetbundle"]
        bundle_dir_path = bundle_root / bundle_key
        if bundle_dir_path.is_dir():
            bundle_files.extend(sorted(bundle_dir_path.glob("*.assetbundle")))

        for bundle_file in bundle_files:
            if not bundle_file.exists():
                continue

            try:
                mask = text_bundle_mask(text_root, bundle_file)
                decrypted = decrypt_text_bundle(bundle_file.read_bytes(), mask)
                for serialized_file in extract_bundle_streams(decrypted):
                    for _text_asset_name, text_asset_text in extract_text_assets(serialized_file):
                        for key, value in parse_text_asset_lines(text_asset_text).items():
                            entries.setdefault(key, value)
            except (EOFError, OSError, ValueError, struct.error, lz4.block.LZ4BlockError) as exc:
                print(f"warning: skipping unreadable text bundle {bundle_file}: {exc}", file=sys.stderr)

    _BUNDLE_ENTRY_CACHE[cache_key] = dict(entries)
    return dict(entries)


def lookup_key(row: dict[str, Any]) -> str:
    return f"{int(row['AssetCategoryId']):03d}{int(row['AssetVariationId']):03d}"


def build_records(rows: list[dict[str, Any]], entries: dict[str, str], config: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    id_field = config["id_field"]
    fallback_prefix = config["fallback_prefix"]

    for row in sorted(rows, key=lambda current: int(current[id_field])):
        entity_id = int(row[id_field])
        localization_key = lookup_key(row)
        text_key = f"{config['bundle_key']}.name.{localization_key}"
        english_name = entries.get(text_key)

        record = {
            "id": entity_id,
            "name": english_name or f"{fallback_prefix} {entity_id}",
            "name_found": bool(english_name),
            "lookup_key": localization_key,
            "asset_category_id": int(row["AssetCategoryId"]),
            "asset_variation_id": int(row["AssetVariationId"]),
            "asset_name": row.get("AssetName", ""),
        }

        for field in config["extra_fields"]:
            if field in row:
                record[field] = row[field]

        records.append(record)

    return records


def split_trailing_digits(value: str) -> tuple[str, str, bool]:
    end = len(value)
    while end > 0 and value[end - 1].isdigit():
        end -= 1
    if end == len(value):
        return "", "", False
    return value[:end], value[end:], True


def load_weapon_evolution_orders(master_data_root: Path) -> dict[int, int]:
    path = master_data_root / "EntityMWeaponEvolutionGroupTable.json"
    rows = load_json_array(path)
    result: dict[int, int] = {}
    for row in rows:
        weapon_id = int(row.get("WeaponId", 0) or 0)
        order = int(row.get("EvolutionOrder", 0) or 0)
        if weapon_id <= 0 or order <= 0:
            continue
        if weapon_id not in result or order < result[weapon_id]:
            result[weapon_id] = order
    return result


def weapon_name_asset_id_override(weapon_id: int) -> str:
    overrides = {
        101001: "wp005501",
        101011: "wp001501",
        101021: "wp006001",
        101031: "wp003039",
        101041: "wp002046",
    }
    return overrides.get(weapon_id, "")


def weapon_actor_asset_id(row: dict[str, Any]) -> str:
    category_prefix = "wp" if int(row["WeaponCategoryType"]) == 1 else "mw"
    return f"{category_prefix}{int(row['WeaponType']):03d}{int(row['AssetVariationId']):03d}"


def weapon_name_asset_ids(row: dict[str, Any]) -> list[str]:
    weapon_id = int(row["WeaponId"])
    weapon_type = int(row["WeaponType"])
    asset_ids: list[str] = []

    override = weapon_name_asset_id_override(weapon_id)
    if override:
        asset_ids.append(override)

    actor_asset_id = weapon_actor_asset_id(row)
    if actor_asset_id not in asset_ids:
        asset_ids.append(actor_asset_id)

    if weapon_id > 0 and weapon_type > 0:
        category_prefix = "wp" if int(row["WeaponCategoryType"]) == 1 else "mw"
        family_asset_id = f"{category_prefix}{weapon_type:03d}{weapon_id % 1000:03d}"
        if family_asset_id not in asset_ids:
            asset_ids.append(family_asset_id)

    return asset_ids


def lookup_nearest_weapon_name(entries: dict[str, str], actor_asset_id: str, evolution_order: int) -> tuple[str, int]:
    if not actor_asset_id:
        return "", 0

    prefix, digits, ok = split_trailing_digits(actor_asset_id)
    if not ok or len(digits) != 6:
        return "", 0

    target_family = digits[:3]
    target_variation = int(digits[3:])

    best_name = ""
    best_diff = 1 << 30
    best_variation = 1 << 30

    for key, value in entries.items():
        if not key.startswith("weapon.name."):
            continue
        raw_key = key.removeprefix("weapon.name.")
        parts = raw_key.split(".")
        if len(parts) != 2:
            continue
        try:
            order = int(parts[1])
        except ValueError:
            continue
        if order != evolution_order:
            continue

        key_prefix, key_digits, ok = split_trailing_digits(parts[0])
        if not ok or key_prefix != prefix or len(key_digits) != 6 or key_digits[:3] != target_family:
            continue

        variation = int(key_digits[3:])
        diff = abs(variation - target_variation)
        if diff < best_diff or (diff == best_diff and variation < best_variation):
            best_name = value
            best_diff = diff
            best_variation = variation

    if not best_name:
        return "", 0
    return best_name, best_diff


def resolve_weapon_name(
    row: dict[str, Any],
    entries: dict[str, str],
    evolution_orders: dict[int, int],
) -> tuple[str, bool, str, int]:
    weapon_id = int(row["WeaponId"])
    evolution_order = evolution_orders.get(weapon_id, 1)
    if evolution_order <= 0:
        evolution_order = 1

    for asset_id in weapon_name_asset_ids(row):
        for prefix in ("weapon.name.", "weapon.name.replace."):
            for suffix in (str(evolution_order), f"{evolution_order:02d}"):
                key = f"{prefix}{asset_id}.{suffix}"
                if key in entries:
                    return entries[key], True, key, evolution_order

    for asset_id in weapon_name_asset_ids(row):
        nearest_name, diff = lookup_nearest_weapon_name(entries, asset_id, evolution_order)
        if nearest_name and diff <= 1:
            return nearest_name, True, f"nearest:{asset_id}:{evolution_order}", evolution_order

    return f"Weapon {weapon_id}", False, "", evolution_order


def build_weapon_records(
    rows: list[dict[str, Any]],
    entries: dict[str, str],
    evolution_orders: dict[int, int],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    for row in sorted(rows, key=lambda current: int(current["WeaponId"])):
        name, name_found, matched_key, evolution_order = resolve_weapon_name(row, entries, evolution_orders)
        record = {
            "id": int(row["WeaponId"]),
            "name": name,
            "name_found": name_found,
            "matched_text_key": matched_key,
            "evolution_order": evolution_order,
            "weapon_actor_asset_id": weapon_actor_asset_id(row),
            "weapon_name_asset_ids": weapon_name_asset_ids(row),
        }

        for field in config["extra_fields"]:
            if field in row:
                record[field] = row[field]

        records.append(record)

    return records


def build_character_records(
    rows: list[dict[str, Any]],
    entries: dict[str, str],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    for row in sorted(rows, key=lambda current: int(current["CharacterId"])):
        character_id = int(row["CharacterId"])
        name_text_id = int(row.get("NameCharacterTextId", 0) or 0)
        is_playable = any(
            int(row.get(field, 0) or 0) > 0
            for field in ("DefaultCostumeId", "DefaultWeaponId", "EndCostumeId", "EndWeaponId")
        )
        candidate_keys = [f"character.name.{name_text_id}"]
        if name_text_id > 0:
            candidate_keys.append(f"character.name.{name_text_id}.1")

        matched_key = ""
        english_name = ""
        for key in candidate_keys:
            if key in entries:
                matched_key = key
                english_name = entries[key]
                break

        record = {
            "id": character_id,
            "name": english_name or f"Character {character_id}",
            "name_found": bool(english_name),
            "matched_text_key": matched_key,
            "is_playable_character": is_playable,
        }

        for field in config["extra_fields"]:
            if field in row:
                record[field] = row[field]

        records.append(record)

    return records


def build_character_name_map(
    master_data_dir: Path,
    text_root: Path,
) -> tuple[dict[int, str], dict[int, bool]]:
    config = KIND_CONFIG["characters"]
    rows = load_json_array(master_data_dir / config["master_data_file"])
    entries = load_bundle_entries(text_root, config["bundle_key"], config.get("bundle_dirs"))
    records = build_character_records(rows, entries, config)
    name_map = {int(record["id"]): record["name"] for record in records}
    playable_map = {int(record["id"]): bool(record["is_playable_character"]) for record in records}
    return name_map, playable_map


def costume_actor_asset_id(row: dict[str, Any]) -> str:
    prefix = "ch" if int(row["CostumeAssetCategoryType"]) == 1 else "mt"
    return f"{prefix}{int(row['ActorSkeletonId']):03d}{int(row['AssetVariationId']):03d}"


def build_costume_records(
    rows: list[dict[str, Any]],
    entries: dict[str, str],
    config: dict[str, Any],
    character_names: dict[int, str],
    playable_characters: dict[int, bool],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    for row in sorted(rows, key=lambda current: int(current["CostumeId"])):
        costume_id = int(row["CostumeId"])
        character_id = int(row.get("CharacterId", 0) or 0)
        actor_asset_id = costume_actor_asset_id(row)
        text_key = f"costume.name.{actor_asset_id}"
        english_name = entries.get(text_key, "")
        character_name = character_names.get(character_id, "")

        if not english_name:
            if character_name:
                english_name = f"{character_name} Costume {costume_id}"
            else:
                english_name = f"Costume {costume_id}"

        record = {
            "id": costume_id,
            "name": english_name,
            "name_found": text_key in entries,
            "matched_text_key": text_key if text_key in entries else "",
            "costume_actor_asset_id": actor_asset_id,
            "character_name": character_name,
            "is_playable_character_costume": playable_characters.get(character_id, False),
        }

        for field in config["extra_fields"]:
            if field in row:
                record[field] = row[field]

        records.append(record)

    return records


def companion_actor_asset_id(row: dict[str, Any]) -> str:
    return f"cm{int(row['ActorSkeletonId']):03d}{int(row['AssetVariationId']):03d}"


def build_companion_records(
    rows: list[dict[str, Any]],
    entries: dict[str, str],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    for row in sorted(rows, key=lambda current: int(current["CompanionId"])):
        companion_id = int(row["CompanionId"])
        actor_asset_id = companion_actor_asset_id(row)
        text_key = f"companion.name.{actor_asset_id}"
        english_name = entries.get(text_key, "")

        record = {
            "id": companion_id,
            "name": english_name or f"Companion {companion_id}",
            "name_found": bool(english_name),
            "matched_text_key": text_key if english_name else "",
            "companion_actor_asset_id": actor_asset_id,
        }

        for field in config["extra_fields"]:
            if field in row:
                record[field] = row[field]

        records.append(record)

    return records


def load_thought_catalog_terms(master_data_root: Path) -> dict[int, int]:
    path = master_data_root / "EntityMCatalogThoughtTable.json"
    rows = load_json_array(path)
    result: dict[int, int] = {}
    for row in rows:
        thought_id = int(row.get("ThoughtId", 0) or 0)
        catalog_term_id = int(row.get("CatalogTermId", 0) or 0)
        if thought_id <= 0 or catalog_term_id <= 0:
            continue
        result[thought_id] = catalog_term_id
    return result


def load_parts_group_assets(master_data_root: Path) -> dict[int, int]:
    path = master_data_root / "EntityMPartsGroupTable.json"
    rows = load_json_array(path)
    result: dict[int, int] = {}
    for row in rows:
        group_id = int(row.get("PartsGroupId", 0) or 0)
        asset_id = int(row.get("PartsGroupAssetId", 0) or 0)
        if group_id <= 0 or asset_id <= 0:
            continue
        result[group_id] = asset_id
    return result


def build_parts_records(
    rows: list[dict[str, Any]],
    entries: dict[str, str],
    config: dict[str, Any],
    parts_group_assets: dict[int, int],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    for row in sorted(rows, key=lambda current: int(current["PartsId"])):
        parts_id = int(row["PartsId"])
        group_id = int(row.get("PartsGroupId", 0) or 0)
        asset_id = parts_group_assets.get(group_id, 0)
        text_key = f"parts.group.name.{asset_id}" if asset_id > 0 else ""
        english_name = entries.get(text_key, "") if text_key else ""

        record = {
            "id": parts_id,
            "name": english_name or f"Part {parts_id}",
            "name_found": bool(english_name),
            "matched_text_key": text_key if english_name else "",
            "parts_group_asset_id": asset_id,
        }

        for field in config["extra_fields"]:
            if field in row:
                record[field] = row[field]

        records.append(record)

    return records


def load_ability_pairs(master_data_root: Path) -> list[tuple[int, int]]:
    path = master_data_root / "m_abiliwy.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    result: list[tuple[int, int]] = []
    for pair in data:
        if not isinstance(pair, list) or len(pair) < 2:
            continue
        ability_id = int(pair[0] or 0)
        detail_id = int(pair[1] or 0)
        if ability_id <= 0 or detail_id <= 0:
            continue
        result.append((ability_id, detail_id))
    return result


def load_ability_detail_rows(master_data_root: Path) -> dict[int, dict[str, Any]]:
    rows = load_json_array(master_data_root / "EntityMAbilityDetailTable.json")
    return {int(row["AbilityDetailId"]): row for row in rows if int(row.get("AbilityDetailId", 0) or 0) > 0}


def build_ability_records(
    master_data_root: Path,
    entries: dict[str, str],
) -> list[dict[str, Any]]:
    detail_by_id = load_ability_detail_rows(master_data_root)
    records: list[dict[str, Any]] = []

    for ability_id, detail_id in sorted(load_ability_pairs(master_data_root), key=lambda pair: pair[0]):
        detail_row = detail_by_id.get(detail_id)
        if detail_row is None:
            continue

        name_text_id = int(detail_row.get("NameAbilityTextId", 0) or 0)
        description_text_id = int(detail_row.get("DescriptionAbilityTextId", 0) or 0)
        text_key = f"ability.name.{name_text_id}" if name_text_id > 0 else ""
        english_name = entries.get(text_key, "") if text_key else ""

        record = {
            "id": ability_id,
            "name": english_name or f"Ability {ability_id}",
            "name_found": bool(english_name),
            "matched_text_key": text_key if english_name else "",
            "AbilityDetailId": detail_id,
            "NameAbilityTextId": name_text_id,
            "DescriptionAbilityTextId": description_text_id,
            "AbilityBehaviourGroupId": detail_row.get("AbilityBehaviourGroupId"),
            "AssetCategoryId": detail_row.get("AssetCategoryId"),
            "AssetVariationId": detail_row.get("AssetVariationId"),
        }
        records.append(record)

    return records


def load_skill_group_to_detail(master_data_root: Path) -> dict[int, dict[str, Any]]:
    rows = load_json_array(master_data_root / "EntityMSkillLevelGroupTable.json")
    result: dict[int, dict[str, Any]] = {}
    for row in rows:
        group_id = int(row.get("SkillLevelGroupId", 0) or 0)
        if group_id <= 0:
            continue
        existing = result.get(group_id)
        if existing is None or int(row.get("LevelLowerLimit", 0) or 0) < int(existing.get("LevelLowerLimit", 0) or 0):
            result[group_id] = row
    return result


def load_skill_detail_rows(master_data_root: Path) -> dict[int, dict[str, Any]]:
    rows = load_json_array(master_data_root / "EntityMSkillDetailTable.json")
    return {int(row["SkillDetailId"]): row for row in rows if int(row.get("SkillDetailId", 0) or 0) > 0}


def build_skill_records(
    rows: list[dict[str, Any]],
    entries: dict[str, str],
    config: dict[str, Any],
    master_data_root: Path,
) -> list[dict[str, Any]]:
    group_to_detail = load_skill_group_to_detail(master_data_root)
    detail_by_id = load_skill_detail_rows(master_data_root)
    records: list[dict[str, Any]] = []

    for row in sorted(rows, key=lambda current: int(current["SkillId"])):
        skill_id = int(row["SkillId"])
        group_id = int(row.get("SkillLevelGroupId", 0) or 0)
        group_row = group_to_detail.get(group_id)
        detail_row = detail_by_id.get(int(group_row.get("SkillDetailId", 0) or 0)) if group_row else None

        english_name = ""
        text_key = ""
        if detail_row is not None:
            name_text_id = int(detail_row.get("NameSkillTextId", 0) or 0)
            if name_text_id > 0:
                text_key = f"skill.name.{name_text_id}"
                english_name = entries.get(text_key, "")

        record = {
            "id": skill_id,
            "name": english_name or f"Skill {skill_id}",
            "name_found": bool(english_name),
            "matched_text_key": text_key if english_name else "",
        }

        for field in config["extra_fields"]:
            if field in row:
                record[field] = row[field]

        if detail_row is not None:
            record["SkillDetailId"] = int(detail_row.get("SkillDetailId", 0) or 0)
            record["NameSkillTextId"] = int(detail_row.get("NameSkillTextId", 0) or 0)
            record["DescriptionSkillTextId"] = int(detail_row.get("DescriptionSkillTextId", 0) or 0)

        records.append(record)

    return records


def build_thought_records(
    rows: list[dict[str, Any]],
    entries: dict[str, str],
    config: dict[str, Any],
    catalog_terms: dict[int, int],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    for row in sorted(rows, key=lambda current: int(current["ThoughtId"])):
        thought_id = int(row["ThoughtId"])
        thought_asset_id = int(row.get("ThoughtAssetId", 0) or 0)
        direct_key = f"thought.name.{thought_asset_id:06d}" if thought_asset_id > 0 else ""
        catalog_term_id = catalog_terms.get(thought_id, 0)
        catalog_key = f"thought.name.{catalog_term_id:06d}0" if catalog_term_id > 0 else ""

        matched_key = ""
        english_name = ""
        if direct_key and direct_key in entries:
            matched_key = direct_key
            english_name = entries[direct_key]
        elif catalog_key and catalog_key in entries:
            matched_key = catalog_key
            english_name = entries[catalog_key]

        record = {
            "id": thought_id,
            "name": english_name or f"Thought {thought_id}",
            "name_found": bool(english_name),
            "matched_text_key": matched_key,
            "catalog_term_id": catalog_term_id,
            "internal_entity_type": "thought",
            "display_entity_type": "debris",
        }

        for field in config["extra_fields"]:
            if field in row:
                record[field] = row[field]

        records.append(record)

    return records


def build_character_board_records(
    master_data_dir: Path,
    text_root: Path,
) -> list[dict[str, Any]]:
    master_data_root = master_data_dir
    board_rows = load_json_array(master_data_root / "EntityMCharacterBoardTable.json")
    group_rows = load_json_array(master_data_root / "EntityMCharacterBoardGroupTable.json")
    assignment_rows = load_json_array(master_data_root / "EntityMCharacterBoardAssignmentTable.json")
    entries = load_bundle_entries(text_root, "character_board", [""])
    character_names, playable_characters = build_character_name_map(master_data_dir, text_root)

    group_by_id = {
        int(row["CharacterBoardGroupId"]): row
        for row in group_rows
        if int(row.get("CharacterBoardGroupId", 0) or 0) > 0
    }

    character_by_category_id: dict[int, int] = {}
    for row in assignment_rows:
        category_id = int(row.get("CharacterBoardCategoryId", 0) or 0)
        character_id = int(row.get("CharacterId", 0) or 0)
        if category_id <= 0 or character_id <= 0:
            continue
        character_by_category_id.setdefault(category_id, character_id)

    records: list[dict[str, Any]] = []
    for row in sorted(board_rows, key=lambda current: int(current["CharacterBoardId"])):
        board_id = int(row["CharacterBoardId"])
        group_id = int(row.get("CharacterBoardGroupId", 0) or 0)
        group_row = group_by_id.get(group_id, {})
        category_id = int(group_row.get("CharacterBoardCategoryId", 0) or 0)
        text_asset_id = int(group_row.get("TextAssetId", 0) or 0)
        text_key = f"characterBoard.group.name.{text_asset_id}" if text_asset_id > 0 else ""
        group_name = entries.get(text_key, "") if text_key else ""
        character_id = character_by_category_id.get(category_id, 0)
        character_name = character_names.get(character_id, "")

        display_name = group_name or f"Character Board {board_id}"
        if character_name and group_name:
            display_name = f"{character_name} - {group_name}"
        elif character_name:
            display_name = f"{character_name} Board"

        records.append(
            {
                "id": board_id,
                "name": display_name,
                "name_found": bool(group_name or character_name),
                "matched_text_key": text_key if group_name else "",
                "CharacterBoardGroupId": group_id,
                "CharacterBoardCategoryId": category_id,
                "CharacterBoardGroupType": int(group_row.get("CharacterBoardGroupType", 0) or 0),
                "TextAssetId": text_asset_id,
                "ReleaseRank": int(row.get("ReleaseRank", 0) or 0),
                "CharacterBoardUnlockConditionGroupId": int(row.get("CharacterBoardUnlockConditionGroupId", 0) or 0),
                "character_id": character_id,
                "character_name": character_name,
                "group_name": group_name,
                "is_playable_character_board": playable_characters.get(character_id, False),
            }
        )

    return records


def build_weapon_slot_records(
    master_data_dir: Path,
    text_root: Path,
    slot_kind: str,
) -> list[dict[str, Any]]:
    master_data_root = master_data_dir
    weapon_rows = load_json_array(master_data_root / "EntityMWeaponTable.json")
    weapon_name_entries = load_bundle_entries(text_root, "weapon", ["possession"])
    evolution_orders = load_weapon_evolution_orders(master_data_root)

    if slot_kind == "skill":
        slot_rows = load_json_array(master_data_root / "EntityMWeaponSkillGroupTable.json")
        skill_rows = load_json_array(master_data_root / "EntityMSkillTable.json")
        skill_entries = load_bundle_entries(text_root, "skill", [""])
        skill_records = build_skill_records(
            skill_rows,
            skill_entries,
            KIND_CONFIG["skills"],
            master_data_root,
        )
        named_lookup = {int(record["id"]): record for record in skill_records}
        group_field = "WeaponSkillGroupId"
        item_field = "SkillId"
        group_id_field = "WeaponSkillGroupId"
    else:
        slot_rows = load_json_array(master_data_root / "EntityMWeaponAbilityGroupTable.json")
        ability_entries = load_bundle_entries(text_root, "ability", [""])
        ability_records = build_ability_records(master_data_root, ability_entries)
        named_lookup = {int(record["id"]): record for record in ability_records}
        group_field = "WeaponAbilityGroupId"
        item_field = "AbilityId"
        group_id_field = "WeaponAbilityGroupId"

    slots_by_group: dict[int, list[dict[str, Any]]] = {}
    for row in slot_rows:
        group_id = int(row.get(group_id_field, 0) or 0)
        if group_id <= 0:
            continue
        slots_by_group.setdefault(group_id, []).append(row)

    records: list[dict[str, Any]] = []
    for weapon_row in sorted(weapon_rows, key=lambda current: int(current["WeaponId"])):
        weapon_id = int(weapon_row["WeaponId"])
        weapon_name, _, _, _ = resolve_weapon_name(weapon_row, weapon_name_entries, evolution_orders)
        group_id = int(weapon_row.get(group_field, 0) or 0)
        for row in sorted(slots_by_group.get(group_id, []), key=lambda current: int(current.get("SlotNumber", 0) or 0)):
            slot_number = int(row.get("SlotNumber", 0) or 0)
            linked_id = int(row.get(item_field, 0) or 0)
            linked_record = named_lookup.get(linked_id)
            linked_name = linked_record["name"] if linked_record else f"{slot_kind.title()} {linked_id}"
            name_found = bool(linked_record and linked_record.get("name_found"))

            record = {
                "id": int(f"{weapon_id}{slot_number:02d}"),
                "weapon_id": weapon_id,
                "weapon_name": weapon_name,
                "slot_number": slot_number,
                "name": linked_name,
                "name_found": name_found,
                "matched_text_key": linked_record.get("matched_text_key", "") if linked_record else "",
                group_field: group_id,
                item_field: linked_id,
            }

            enhancement_field = (
                "WeaponSkillEnhancementMaterialId" if slot_kind == "skill" else "WeaponAbilityEnhancementMaterialId"
            )
            if enhancement_field in row:
                record[enhancement_field] = int(row.get(enhancement_field, 0) or 0)

            records.append(record)

    return records


def build_costume_active_skill_records(
    master_data_dir: Path,
    text_root: Path,
) -> list[dict[str, Any]]:
    master_data_root = master_data_dir
    costume_rows = load_json_array(master_data_root / "EntityMCostumeTable.json")
    group_rows = load_json_array(master_data_root / "EntityMCostumeActiveSkillGroupTable.json")
    skill_rows = load_json_array(master_data_root / "EntityMSkillTable.json")
    skill_entries = load_bundle_entries(text_root, "skill", [""])
    costume_entries = load_bundle_entries(text_root, "costume", ["possession"])
    character_names, playable_characters = build_character_name_map(master_data_dir, text_root)
    costume_records = build_costume_records(
        costume_rows,
        costume_entries,
        KIND_CONFIG["costumes"],
        character_names,
        playable_characters,
    )
    costume_lookup = {int(record["id"]): record for record in costume_records}
    skill_records = build_skill_records(skill_rows, skill_entries, KIND_CONFIG["skills"], master_data_root)
    skill_lookup = {int(record["id"]): record for record in skill_records}

    rows_by_group: dict[int, list[dict[str, Any]]] = {}
    for row in group_rows:
        group_id = int(row.get("CostumeActiveSkillGroupId", 0) or 0)
        if group_id <= 0:
            continue
        rows_by_group.setdefault(group_id, []).append(row)

    records: list[dict[str, Any]] = []
    for costume_row in sorted(costume_rows, key=lambda current: int(current["CostumeId"])):
        costume_id = int(costume_row["CostumeId"])
        costume_record = costume_lookup.get(costume_id, {})
        group_id = int(costume_row.get("CostumeActiveSkillGroupId", 0) or 0)
        for row in sorted(
            rows_by_group.get(group_id, []),
            key=lambda current: int(current.get("CostumeLimitBreakCountLowerLimit", 0) or 0),
        ):
            limit_break = int(row.get("CostumeLimitBreakCountLowerLimit", 0) or 0)
            skill_id = int(row.get("CostumeActiveSkillId", 0) or 0)
            skill_record = skill_lookup.get(skill_id)
            records.append(
                {
                    "id": int(f"{costume_id}{limit_break:02d}"),
                    "costume_id": costume_id,
                    "costume_name": costume_record.get("name", f"Costume {costume_id}"),
                    "character_id": int(costume_row.get("CharacterId", 0) or 0),
                    "character_name": costume_record.get("character_name", ""),
                    "limit_break_count_lower_limit": limit_break,
                    "CostumeActiveSkillGroupId": group_id,
                    "CostumeActiveSkillId": skill_id,
                    "name": skill_record["name"] if skill_record else f"Active Skill {skill_id}",
                    "name_found": bool(skill_record and skill_record.get("name_found")),
                    "matched_text_key": skill_record.get("matched_text_key", "") if skill_record else "",
                    "CostumeActiveSkillEnhancementMaterialId": int(
                        row.get("CostumeActiveSkillEnhancementMaterialId", 0) or 0
                    ),
                }
            )

    return records


def build_weapon_story_records(
    master_data_dir: Path,
    text_root: Path,
) -> list[dict[str, Any]]:
    master_data_root = master_data_dir
    weapon_rows = load_json_array(master_data_root / "EntityMWeaponTable.json")
    condition_rows = load_json_array(master_data_root / "EntityMWeaponStoryReleaseConditionGroupTable.json")
    weapon_entries = load_bundle_entries(text_root, "weapon", ["possession"])
    story_entries = load_bundle_entries(text_root, "weapon_story", ["possession"])
    evolution_orders = load_weapon_evolution_orders(master_data_root)

    indexes_by_group: dict[int, set[int]] = {}
    for row in condition_rows:
        group_id = int(row.get("WeaponStoryReleaseConditionGroupId", 0) or 0)
        story_index = int(row.get("StoryIndex", 0) or 0)
        if group_id <= 0 or story_index <= 0:
            continue
        indexes_by_group.setdefault(group_id, set()).add(story_index)

    records: list[dict[str, Any]] = []
    for weapon_row in sorted(weapon_rows, key=lambda current: int(current["WeaponId"])):
        weapon_id = int(weapon_row["WeaponId"])
        weapon_name, _, _, evolution_order = resolve_weapon_name(weapon_row, weapon_entries, evolution_orders)
        group_id = int(weapon_row.get("WeaponStoryReleaseConditionGroupId", 0) or 0)
        story_indexes = sorted(indexes_by_group.get(group_id, {1, 2, 3, 4}))
        asset_ids = weapon_name_asset_ids(weapon_row)

        for story_index in story_indexes:
            matched_key = ""
            story_text = ""
            for asset_id in asset_ids:
                candidate_keys = [
                    f"weapon.story.{asset_id}.{story_index}",
                    f"weapon.story.replace.{asset_id}.{story_index}",
                ]
                for key in candidate_keys:
                    if key in story_entries:
                        matched_key = key
                        story_text = story_entries[key]
                        break
                if story_text:
                    break

            cleaned_text = story_text.strip()
            found_text = bool(cleaned_text and cleaned_text != "-")
            records.append(
                {
                    "id": int(f"{weapon_id}{story_index:02d}"),
                    "weapon_id": weapon_id,
                    "weapon_name": weapon_name,
                    "story_index": story_index,
                    "name": f"{weapon_name} Story {story_index}",
                    "name_found": found_text,
                    "matched_text_key": matched_key if found_text else "",
                    "story_text": cleaned_text if found_text else "",
                    "WeaponStoryReleaseConditionGroupId": group_id,
                    "evolution_order": evolution_order,
                    "weapon_name_asset_ids": asset_ids,
                }
            )

    return records


def load_character_board_target_characters(master_data_root: Path) -> dict[int, int]:
    rows = load_json_array(master_data_root / "EntityMCharacterBoardEffectTargetGroupTable.json")
    result: dict[int, int] = {}
    for row in rows:
        group_id = int(row.get("CharacterBoardEffectTargetGroupId", 0) or 0)
        target_type = int(row.get("CharacterBoardEffectTargetType", 0) or 0)
        target_value = int(row.get("TargetValue", 0) or 0)
        if group_id <= 0 or target_type != 1 or target_value <= 0:
            continue
        result.setdefault(group_id, target_value)
    return result


def build_character_board_ability_records(
    master_data_dir: Path,
    text_root: Path,
) -> list[dict[str, Any]]:
    master_data_root = master_data_dir
    board_rows = load_json_array(master_data_root / "EntityMCharacterBoardAbilityTable.json")
    ability_entries = load_bundle_entries(text_root, "ability", [""])
    ability_records = build_ability_records(master_data_root, ability_entries)
    ability_lookup = {int(record["id"]): record for record in ability_records}
    character_names, playable_characters = build_character_name_map(master_data_dir, text_root)
    target_characters = load_character_board_target_characters(master_data_root)

    records: list[dict[str, Any]] = []
    for row in sorted(board_rows, key=lambda current: int(current["CharacterBoardAbilityId"])):
        board_ability_id = int(row["CharacterBoardAbilityId"])
        target_group_id = int(row.get("CharacterBoardEffectTargetGroupId", 0) or 0)
        ability_id = int(row.get("AbilityId", 0) or 0)
        character_id = target_characters.get(target_group_id, 0)
        ability_record = ability_lookup.get(ability_id)
        records.append(
            {
                "id": board_ability_id,
                "name": ability_record["name"] if ability_record else f"Ability {ability_id}",
                "name_found": bool(ability_record and ability_record.get("name_found")),
                "matched_text_key": ability_record.get("matched_text_key", "") if ability_record else "",
                "CharacterBoardEffectTargetGroupId": target_group_id,
                "AbilityId": ability_id,
                "character_id": character_id,
                "character_name": character_names.get(character_id, ""),
                "is_playable_character_board_ability": playable_characters.get(character_id, False),
                "NameAbilityTextId": ability_record.get("NameAbilityTextId") if ability_record else 0,
                "DescriptionAbilityTextId": ability_record.get("DescriptionAbilityTextId") if ability_record else 0,
            }
        )

    return records


def build_character_board_status_up_records(
    master_data_dir: Path,
    text_root: Path,
) -> list[dict[str, Any]]:
    master_data_root = master_data_dir
    status_rows = load_json_array(master_data_root / "EntityMCharacterBoardStatusUpTable.json")
    effect_rows = load_json_array(master_data_root / "EntityMCharacterBoardPanelReleaseEffectGroupTable.json")
    panel_rows = load_json_array(master_data_root / "EntityMCharacterBoardPanelTable.json")
    status_entries = load_bundle_entries(text_root, "status", [""])
    character_names, playable_characters = build_character_name_map(master_data_dir, text_root)
    target_characters = load_character_board_target_characters(master_data_root)

    status_type_labels = {
        3: ("Attack Up", "Attack"),
        7: ("HP Up", "HP"),
        9: ("Defense Up", "Vitality"),
    }

    effect_by_status_id: dict[int, dict[str, Any]] = {}
    for row in effect_rows:
        if int(row.get("CharacterBoardEffectType", 0) or 0) != 2:
            continue
        effect_id = int(row.get("CharacterBoardEffectId", 0) or 0)
        if effect_id > 0:
            effect_by_status_id.setdefault(effect_id, row)

    panel_by_effect_group_id: dict[int, dict[str, Any]] = {}
    for row in panel_rows:
        group_id = int(row.get("CharacterBoardPanelReleaseEffectGroupId", 0) or 0)
        if group_id > 0:
            panel_by_effect_group_id.setdefault(group_id, row)

    records: list[dict[str, Any]] = []
    for row in sorted(status_rows, key=lambda current: int(current["CharacterBoardStatusUpId"])):
        status_up_id = int(row["CharacterBoardStatusUpId"])
        status_type = int(row.get("CharacterBoardStatusUpType", 0) or 0)
        target_group_id = int(row.get("CharacterBoardEffectTargetGroupId", 0) or 0)
        character_id = target_characters.get(target_group_id, 0)
        effect_row = effect_by_status_id.get(status_up_id, {})
        effect_value = int(effect_row.get("EffectValue", 0) or 0)
        panel_row = panel_by_effect_group_id.get(int(effect_row.get("CharacterBoardPanelReleaseEffectGroupId", 0) or 0), {})
        label, field_name = status_type_labels.get(status_type, (f"Status Up Type {status_type}", ""))
        status_key = ""
        if status_type == 3:
            status_key = "status.name.02.01"
        elif status_type == 7:
            status_key = "status.name.06.01"
        elif status_type == 9:
            status_key = "status.name.07.01"
        localized_label = status_entries.get(status_key, "")
        display_name = localized_label or label
        if effect_value > 0:
            display_name = f"{display_name} +{effect_value}"

        records.append(
            {
                "id": status_up_id,
                "name": display_name,
                "name_found": bool(localized_label or label),
                "matched_text_key": status_key if localized_label else "",
                "CharacterBoardStatusUpType": status_type,
                "CharacterBoardEffectTargetGroupId": target_group_id,
                "character_id": character_id,
                "character_name": character_names.get(character_id, ""),
                "is_playable_character_board_status_up": playable_characters.get(character_id, False),
                "effect_value": effect_value,
                "status_field": field_name,
                "CharacterBoardPanelReleaseEffectGroupId": int(
                    effect_row.get("CharacterBoardPanelReleaseEffectGroupId", 0) or 0
                ),
                "CharacterBoardId": int(panel_row.get("CharacterBoardId", 0) or 0),
                "CharacterBoardPanelId": int(panel_row.get("CharacterBoardPanelId", 0) or 0),
            }
        )

    return records


def load_material_name_map(master_data_dir: Path, text_root: Path) -> dict[int, str]:
    config = KIND_CONFIG["materials"]
    rows = load_json_array(master_data_dir / config["master_data_file"])
    entries = load_bundle_entries(text_root, config["bundle_key"], config.get("bundle_dirs"))
    records = build_records(rows, entries, config)
    return {int(record["id"]): record["name"] for record in records}


def status_kind_display_info(status_kind_type: int) -> tuple[str, str]:
    mapping = {
        1: ("Agility Up", "status.name.01.01"),
        2: ("Damage Up", "status.name.02.01"),
        3: ("Crit Dmg Rate Up", "status.name.03.01"),
        4: ("Crit Rate Up", "status.name.04.01"),
        5: ("Recovery Rate Up", "status.name.05.01"),
        6: ("HP Up", "status.name.06.01"),
        7: ("Defense Up", "status.name.07.01"),
    }
    return mapping.get(status_kind_type, (f"Status Kind {status_kind_type}", ""))


def build_weapon_awaken_records(
    master_data_dir: Path,
    text_root: Path,
) -> list[dict[str, Any]]:
    master_data_root = master_data_dir
    awaken_rows = load_json_array(master_data_root / "EntityMWeaponAwakenTable.json")
    awaken_ability_rows = load_json_array(master_data_root / "EntityMWeaponAwakenAbilityTable.json")
    effect_rows = load_json_array(master_data_root / "EntityMWeaponAwakenEffectGroupTable.json")
    status_group_rows = load_json_array(master_data_root / "EntityMWeaponAwakenStatusUpGroupTable.json")
    material_rows = load_json_array(master_data_root / "EntityMWeaponAwakenMaterialGroupTable.json")
    weapon_rows = load_json_array(master_data_root / "EntityMWeaponTable.json")
    weapon_entries = load_bundle_entries(text_root, "weapon", ["possession"])
    ability_entries = load_bundle_entries(text_root, "ability", [""])
    status_entries = load_bundle_entries(text_root, "status", [""])
    evolution_orders = load_weapon_evolution_orders(master_data_root)
    material_names = load_material_name_map(master_data_dir, text_root)
    ability_records = build_ability_records(master_data_root, ability_entries)
    ability_lookup = {int(record["id"]): record for record in ability_records}
    weapon_lookup = {int(row["WeaponId"]): row for row in weapon_rows}
    awaken_ability_lookup = {
        int(row["WeaponAwakenAbilityId"]): row
        for row in awaken_ability_rows
        if int(row.get("WeaponAwakenAbilityId", 0) or 0) > 0
    }

    effects_by_group: dict[int, list[dict[str, Any]]] = {}
    for row in effect_rows:
        group_id = int(row.get("WeaponAwakenEffectGroupId", 0) or 0)
        if group_id > 0:
            effects_by_group.setdefault(group_id, []).append(row)

    status_rows_by_group: dict[int, list[dict[str, Any]]] = {}
    for row in status_group_rows:
        group_id = int(row.get("WeaponAwakenStatusUpGroupId", 0) or 0)
        if group_id > 0:
            status_rows_by_group.setdefault(group_id, []).append(row)

    materials_by_group: dict[int, list[dict[str, Any]]] = {}
    for row in material_rows:
        group_id = int(row.get("WeaponAwakenMaterialGroupId", 0) or 0)
        if group_id > 0:
            materials_by_group.setdefault(group_id, []).append(row)

    records: list[dict[str, Any]] = []
    for awaken_row in sorted(awaken_rows, key=lambda current: int(current["WeaponId"])):
        weapon_id = int(awaken_row["WeaponId"])
        weapon_row = weapon_lookup.get(weapon_id)
        if weapon_row is None:
            continue
        weapon_name, _, _, _ = resolve_weapon_name(weapon_row, weapon_entries, evolution_orders)
        material_group_id = int(awaken_row.get("WeaponAwakenMaterialGroupId", 0) or 0)
        material_requirements = []
        for material_row in sorted(materials_by_group.get(material_group_id, []), key=lambda current: int(current.get("SortOrder", 0) or 0)):
            material_id = int(material_row.get("MaterialId", 0) or 0)
            material_requirements.append(
                {
                    "material_id": material_id,
                    "material_name": material_names.get(material_id, f"Material {material_id}"),
                    "count": int(material_row.get("Count", 0) or 0),
                    "sort_order": int(material_row.get("SortOrder", 0) or 0),
                }
            )

        for effect_index, effect_row in enumerate(
            sorted(effects_by_group.get(int(awaken_row.get("WeaponAwakenEffectGroupId", 0) or 0), []), key=lambda current: int(current.get("WeaponAwakenEffectType", 0) or 0)),
            start=1,
        ):
            effect_type = int(effect_row.get("WeaponAwakenEffectType", 0) or 0)
            effect_id = int(effect_row.get("WeaponAwakenEffectId", 0) or 0)

            if effect_type == 1:
                for status_index, status_row in enumerate(
                    sorted(status_rows_by_group.get(effect_id, []), key=lambda current: int(current.get("StatusKindType", 0) or 0)),
                    start=1,
                ):
                    status_kind_type = int(status_row.get("StatusKindType", 0) or 0)
                    default_label, status_key = status_kind_display_info(status_kind_type)
                    localized_label = status_entries.get(status_key, "")
                    display_name = localized_label or default_label
                    effect_value = int(status_row.get("EffectValue", 0) or 0)
                    suffix = "%" if int(status_row.get("StatusCalculationType", 0) or 0) == 2 else ""
                    if effect_value > 0:
                        display_name = f"{display_name} +{effect_value}{suffix}"
                    records.append(
                        {
                            "id": int(f"{weapon_id}{effect_index:02d}{status_index:02d}"),
                            "weapon_id": weapon_id,
                            "weapon_name": weapon_name,
                            "name": display_name,
                            "name_found": True,
                            "matched_text_key": status_key if localized_label else "",
                            "effect_type": "status_up",
                            "WeaponAwakenEffectGroupId": int(awaken_row.get("WeaponAwakenEffectGroupId", 0) or 0),
                            "WeaponAwakenEffectId": effect_id,
                            "WeaponAwakenStatusUpGroupId": effect_id,
                            "StatusKindType": status_kind_type,
                            "StatusCalculationType": int(status_row.get("StatusCalculationType", 0) or 0),
                            "EffectValue": effect_value,
                            "LevelLimitUp": int(awaken_row.get("LevelLimitUp", 0) or 0),
                            "ConsumeGold": int(awaken_row.get("ConsumeGold", 0) or 0),
                            "material_requirements": material_requirements,
                        }
                    )
            elif effect_type == 2:
                ability_record = ability_lookup.get(effect_id)
                awaken_ability_row = awaken_ability_lookup.get(effect_id, {})
                records.append(
                    {
                        "id": int(f"{weapon_id}{effect_index:02d}00"),
                        "weapon_id": weapon_id,
                        "weapon_name": weapon_name,
                        "name": ability_record["name"] if ability_record else f"Ability {effect_id}",
                        "name_found": bool(ability_record and ability_record.get("name_found")),
                        "matched_text_key": ability_record.get("matched_text_key", "") if ability_record else "",
                        "effect_type": "ability",
                        "WeaponAwakenEffectGroupId": int(awaken_row.get("WeaponAwakenEffectGroupId", 0) or 0),
                        "WeaponAwakenEffectId": effect_id,
                        "AbilityId": effect_id,
                        "AbilityLevel": int(awaken_ability_row.get("AbilityLevel", 0) or 0),
                        "LevelLimitUp": int(awaken_row.get("LevelLimitUp", 0) or 0),
                        "ConsumeGold": int(awaken_row.get("ConsumeGold", 0) or 0),
                        "material_requirements": material_requirements,
                    }
                )

    return records


def build_costume_awaken_status_up_records(
    master_data_dir: Path,
    text_root: Path,
) -> list[dict[str, Any]]:
    master_data_root = master_data_dir
    awaken_rows = load_json_array(master_data_root / "EntityMCostumeAwakenTable.json")
    effect_rows = load_json_array(master_data_root / "EntityMCostumeAwakenEffectGroupTable.json")
    status_rows = load_json_array(master_data_root / "EntityMCostumeAwakenStatusUpGroupTable.json")
    price_rows = load_json_array(master_data_root / "EntityMCostumeAwakenPriceGroupTable.json")
    costume_rows = load_json_array(master_data_root / "EntityMCostumeTable.json")
    costume_entries = load_bundle_entries(text_root, "costume", ["possession"])
    status_entries = load_bundle_entries(text_root, "status", [""])
    character_names, playable_characters = build_character_name_map(master_data_dir, text_root)
    costume_records = build_costume_records(
        costume_rows,
        costume_entries,
        KIND_CONFIG["costumes"],
        character_names,
        playable_characters,
    )
    costume_lookup = {int(record["id"]): record for record in costume_records}

    effects_by_group: dict[int, list[dict[str, Any]]] = {}
    for row in effect_rows:
        group_id = int(row.get("CostumeAwakenEffectGroupId", 0) or 0)
        if group_id > 0:
            effects_by_group.setdefault(group_id, []).append(row)

    status_rows_by_group: dict[int, list[dict[str, Any]]] = {}
    for row in status_rows:
        group_id = int(row.get("CostumeAwakenStatusUpGroupId", 0) or 0)
        if group_id > 0:
            status_rows_by_group.setdefault(group_id, []).append(row)

    price_by_group: dict[int, int] = {}
    for row in price_rows:
        group_id = int(row.get("CostumeAwakenPriceGroupId", 0) or 0)
        if group_id > 0:
            price_by_group[group_id] = int(row.get("Gold", 0) or 0)

    records: list[dict[str, Any]] = []
    for awaken_row in sorted(awaken_rows, key=lambda current: int(current["CostumeId"])):
        costume_id = int(awaken_row["CostumeId"])
        costume_record = costume_lookup.get(costume_id, {})
        effect_group_id = int(awaken_row.get("CostumeAwakenEffectGroupId", 0) or 0)
        price_group_id = int(awaken_row.get("CostumeAwakenPriceGroupId", 0) or 0)
        for effect_row in sorted(effects_by_group.get(effect_group_id, []), key=lambda current: int(current.get("AwakenStep", 0) or 0)):
            if int(effect_row.get("CostumeAwakenEffectType", 0) or 0) != 1:
                continue
            awaken_step = int(effect_row.get("AwakenStep", 0) or 0)
            status_group_id = int(effect_row.get("CostumeAwakenEffectId", 0) or 0)
            for status_index, status_row in enumerate(
                sorted(status_rows_by_group.get(status_group_id, []), key=lambda current: int(current.get("SortOrder", 0) or 0)),
                start=1,
            ):
                status_kind_type = int(status_row.get("StatusKindType", 0) or 0)
                default_label, status_key = status_kind_display_info(status_kind_type)
                localized_label = status_entries.get(status_key, "")
                display_name = localized_label or default_label
                effect_value = int(status_row.get("EffectValue", 0) or 0)
                suffix = "%" if int(status_row.get("StatusCalculationType", 0) or 0) == 2 else ""
                if effect_value > 0:
                    display_name = f"{display_name} +{effect_value}{suffix}"
                records.append(
                    {
                        "id": int(f"{costume_id}{awaken_step:02d}{status_index:02d}"),
                        "costume_id": costume_id,
                        "costume_name": costume_record.get("name", f"Costume {costume_id}"),
                        "character_id": costume_record.get("CharacterId", 0),
                        "character_name": costume_record.get("character_name", ""),
                        "name": display_name,
                        "name_found": True,
                        "matched_text_key": status_key if localized_label else "",
                        "awaken_step": awaken_step,
                        "CostumeAwakenEffectGroupId": effect_group_id,
                        "CostumeAwakenStatusUpGroupId": status_group_id,
                        "StatusKindType": status_kind_type,
                        "StatusCalculationType": int(status_row.get("StatusCalculationType", 0) or 0),
                        "EffectValue": effect_value,
                        "SortOrder": int(status_row.get("SortOrder", 0) or 0),
                        "CostumeAwakenPriceGroupId": price_group_id,
                        "Gold": price_by_group.get(price_group_id, 0),
                        "is_playable_character_costume": bool(costume_record.get("is_playable_character_costume")),
                    }
                )

    return records


def build_costume_awaken_ability_records(
    master_data_dir: Path,
    text_root: Path,
) -> list[dict[str, Any]]:
    master_data_root = master_data_dir
    awaken_rows = load_json_array(master_data_root / "EntityMCostumeAwakenTable.json")
    awaken_ability_rows = load_json_array(master_data_root / "EntityMCostumeAwakenAbilityTable.json")
    effect_rows = load_json_array(master_data_root / "EntityMCostumeAwakenEffectGroupTable.json")
    price_rows = load_json_array(master_data_root / "EntityMCostumeAwakenPriceGroupTable.json")
    costume_rows = load_json_array(master_data_root / "EntityMCostumeTable.json")
    costume_entries = load_bundle_entries(text_root, "costume", ["possession"])
    ability_entries = load_bundle_entries(text_root, "ability", [""])
    character_names, playable_characters = build_character_name_map(master_data_dir, text_root)
    costume_records = build_costume_records(
        costume_rows,
        costume_entries,
        KIND_CONFIG["costumes"],
        character_names,
        playable_characters,
    )
    costume_lookup = {int(record["id"]): record for record in costume_records}
    ability_records = build_ability_records(master_data_root, ability_entries)
    ability_lookup = {int(record["id"]): record for record in ability_records}
    awaken_ability_lookup = {
        int(row["CostumeAwakenAbilityId"]): row
        for row in awaken_ability_rows
        if int(row.get("CostumeAwakenAbilityId", 0) or 0) > 0
    }

    effects_by_group: dict[int, list[dict[str, Any]]] = {}
    for row in effect_rows:
        group_id = int(row.get("CostumeAwakenEffectGroupId", 0) or 0)
        if group_id > 0:
            effects_by_group.setdefault(group_id, []).append(row)

    price_by_group: dict[int, int] = {}
    for row in price_rows:
        group_id = int(row.get("CostumeAwakenPriceGroupId", 0) or 0)
        if group_id > 0:
            price_by_group[group_id] = int(row.get("Gold", 0) or 0)

    records: list[dict[str, Any]] = []
    for awaken_row in sorted(awaken_rows, key=lambda current: int(current["CostumeId"])):
        costume_id = int(awaken_row["CostumeId"])
        costume_record = costume_lookup.get(costume_id, {})
        effect_group_id = int(awaken_row.get("CostumeAwakenEffectGroupId", 0) or 0)
        price_group_id = int(awaken_row.get("CostumeAwakenPriceGroupId", 0) or 0)
        for effect_row in sorted(effects_by_group.get(effect_group_id, []), key=lambda current: int(current.get("AwakenStep", 0) or 0)):
            if int(effect_row.get("CostumeAwakenEffectType", 0) or 0) != 2:
                continue
            awaken_step = int(effect_row.get("AwakenStep", 0) or 0)
            awaken_ability_id = int(effect_row.get("CostumeAwakenEffectId", 0) or 0)
            awaken_ability_row = awaken_ability_lookup.get(awaken_ability_id, {})
            ability_id = int(awaken_ability_row.get("AbilityId", 0) or 0)
            ability_record = ability_lookup.get(ability_id)
            records.append(
                {
                    "id": int(f"{costume_id}{awaken_step:02d}00"),
                    "costume_id": costume_id,
                    "costume_name": costume_record.get("name", f"Costume {costume_id}"),
                    "character_id": costume_record.get("CharacterId", 0),
                    "character_name": costume_record.get("character_name", ""),
                    "name": ability_record["name"] if ability_record else f"Ability {ability_id or awaken_ability_id}",
                    "name_found": bool(ability_record and ability_record.get("name_found")),
                    "matched_text_key": ability_record.get("matched_text_key", "") if ability_record else "",
                    "awaken_step": awaken_step,
                    "CostumeAwakenEffectGroupId": effect_group_id,
                    "CostumeAwakenAbilityId": awaken_ability_id,
                    "AbilityId": ability_id,
                    "AbilityLevel": int(awaken_ability_row.get("AbilityLevel", 0) or 0),
                    "CostumeAwakenPriceGroupId": price_group_id,
                    "Gold": price_by_group.get(price_group_id, 0),
                    "is_playable_character_costume": bool(costume_record.get("is_playable_character_costume")),
                }
            )

    return records


def build_important_item_records(
    rows: list[dict[str, Any]],
    entries: dict[str, str],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda current: int(current["ImportantItemId"])):
        item_id = int(row["ImportantItemId"])
        text_id = int(row.get("NameImportantItemTextId", 0) or 0)
        desc_id = int(row.get("DescriptionImportantItemTextId", 0) or 0)
        text_key = f"important_item.name.{text_id}" if text_id > 0 else ""
        description_key = f"important_item.description.{desc_id}" if desc_id > 0 else ""
        english_name = entries.get(text_key, "") if text_key else ""
        record = {
            "id": item_id,
            "name": english_name or f"Important Item {item_id}",
            "name_found": bool(english_name),
            "matched_text_key": text_key if english_name else "",
            "description": entries.get(description_key, "") if description_key else "",
            "description_text_key": description_key if description_key in entries else "",
        }
        for field in config["extra_fields"]:
            if field in row:
                record[field] = row[field]
        records.append(record)
    return records


def build_mission_records(
    rows: list[dict[str, Any]],
    entries: dict[str, str],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda current: int(current["MissionId"])):
        mission_id = int(row["MissionId"])
        text_id = int(row.get("NameMissionTextId", 0) or 0)
        text_key = f"mission.name.{text_id}" if text_id > 0 else ""
        english_name = entries.get(text_key, "") if text_key else ""
        record = {
            "id": mission_id,
            "name": english_name or f"Mission {mission_id}",
            "name_found": bool(english_name),
            "matched_text_key": text_key if english_name else "",
        }
        for field in config["extra_fields"]:
            if field in row:
                record[field] = row[field]
        records.append(record)
    return records


def build_quest_records(
    rows: list[dict[str, Any]],
    entries: dict[str, str],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda current: int(current["QuestId"])):
        quest_id = int(row["QuestId"])
        text_id = int(row.get("NameQuestTextId", 0) or 0)
        picture_book_text_id = int(row.get("PictureBookNameQuestTextId", 0) or 0)
        text_key = f"quest.name.{text_id}" if text_id > 0 else ""
        picture_book_key = f"quest.name.{picture_book_text_id}" if picture_book_text_id > 0 else ""
        english_name = entries.get(text_key, "") if text_key else ""
        picture_book_name = entries.get(picture_book_key, "") if picture_book_key else ""
        record = {
            "id": quest_id,
            "name": english_name or picture_book_name or f"Quest {quest_id}",
            "name_found": bool(english_name or picture_book_name),
            "matched_text_key": text_key if english_name else (picture_book_key if picture_book_name else ""),
            "picture_book_name": picture_book_name,
            "picture_book_text_key": picture_book_key if picture_book_name else "",
        }
        for field in config["extra_fields"]:
            if field in row:
                record[field] = row[field]
        records.append(record)
    return records


def build_quest_mission_records(
    rows: list[dict[str, Any]],
    entries: dict[str, str],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda current: int(current["QuestMissionId"])):
        mission_id = int(row["QuestMissionId"])
        condition_type = int(row.get("QuestMissionConditionType", 0) or 0)
        text_key = f"quest.Mission.Main.Title.{condition_type}" if condition_type > 0 else ""
        english_name = entries.get(text_key, "") if text_key else ""
        record = {
            "id": mission_id,
            "name": english_name or f"Quest Mission {mission_id}",
            "name_found": bool(english_name),
            "matched_text_key": text_key if english_name else "",
        }
        for field in config["extra_fields"]:
            if field in row:
                record[field] = row[field]
        records.append(record)
    return records


def build_tutorial_records(
    master_data_dir: Path,
    text_root: Path,
) -> list[dict[str, Any]]:
    master_data_root = master_data_dir
    unlock_rows = load_json_array(master_data_root / "EntityMTutorialUnlockConditionTable.json")
    dialog_rows = load_json_array(master_data_root / "EntityMTutorialDialogTable.json")
    help_rows = load_json_array(master_data_root / "EntityMHelpTable.json")
    help_entries = load_bundle_entries(text_root, "help", [""])

    help_item_by_help_type: dict[int, int] = {}
    for row in help_rows:
        help_type = int(row.get("HelpType", 0) or 0)
        help_item_id = int(row.get("HelpItemId", 0) or 0)
        if help_type > 0 and help_item_id > 0:
            help_item_by_help_type[help_type] = help_item_id

    dialog_by_tutorial_type: dict[int, dict[str, Any]] = {}
    for row in dialog_rows:
        tutorial_type = int(row.get("TutorialType", 0) or 0)
        if tutorial_type > 0 and tutorial_type not in dialog_by_tutorial_type:
            dialog_by_tutorial_type[tutorial_type] = row

    records: list[dict[str, Any]] = []
    for row in sorted(unlock_rows, key=lambda current: int(current["TutorialType"])):
        tutorial_type = int(row["TutorialType"])
        dialog_row = dialog_by_tutorial_type.get(tutorial_type, {})
        help_type = int(dialog_row.get("HelpType", 0) or 0)
        help_item_id = help_item_by_help_type.get(help_type, 0)
        text_key = f"help.item.name.{help_item_id}" if help_item_id > 0 else ""
        english_name = help_entries.get(text_key, "") if text_key else ""
        records.append(
            {
                "id": tutorial_type,
                "name": english_name or f"Tutorial {tutorial_type}",
                "name_found": bool(english_name),
                "matched_text_key": text_key if english_name else "",
                "HelpType": help_type,
                "HelpItemId": help_item_id,
                "TutorialUnlockConditionType": int(row.get("TutorialUnlockConditionType", 0) or 0),
                "ConditionValue": int(row.get("ConditionValue", 0) or 0),
            }
        )

    return records


def build_shop_records(
    rows: list[dict[str, Any]],
    entries: dict[str, str],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda current: int(current["ShopId"])):
        shop_id = int(row["ShopId"])
        text_id = int(row.get("NameShopTextId", 0) or 0)
        text_key = f"shop.name.{text_id}" if text_id > 0 else ""
        english_name = entries.get(text_key, "") if text_key else ""
        record = {
            "id": shop_id,
            "name": english_name or f"Shop {shop_id}",
            "name_found": bool(english_name),
            "matched_text_key": text_key if english_name else "",
        }
        for field in config["extra_fields"]:
            if field in row:
                record[field] = row[field]
        records.append(record)
    return records


def build_shop_item_records(
    master_data_dir: Path,
    text_root: Path,
) -> list[dict[str, Any]]:
    master_data_root = master_data_dir
    rows = load_json_array(master_data_root / "EntityMShopItemTable.json")
    content_rows = load_json_array(master_data_root / "EntityMShopItemContentPossessionTable.json")
    entries = load_bundle_entries(text_root, "shop", [""])
    consumable_names = load_consumable_name_map(master_data_dir, text_root)
    material_names = load_material_name_map(master_data_dir, text_root)
    important_item_names = load_important_item_name_map(master_data_dir, text_root)

    content_by_shop_item_id: dict[int, list[dict[str, Any]]] = {}
    for row in content_rows:
        shop_item_id = int(row.get("ShopItemId", 0) or 0)
        if shop_item_id <= 0:
            continue
        content_by_shop_item_id.setdefault(shop_item_id, []).append(row)

    def possession_name(possession_type: int, possession_id: int) -> str:
        if possession_type == 5:
            return consumable_names.get(possession_id, f"Consumable {possession_id}")
        if possession_type == 11:
            return material_names.get(possession_id, f"Material {possession_id}")
        if possession_type == 14:
            return important_item_names.get(possession_id, f"Important Item {possession_id}")
        return f"Possession {possession_id}"

    records: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda current: int(current["ShopItemId"])):
        shop_item_id = int(row["ShopItemId"])
        text_id = int(row.get("NameShopTextId", 0) or 0)
        desc_id = int(row.get("DescriptionShopTextId", 0) or 0)
        text_key = f"shop.item.name.{text_id}" if text_id > 0 else ""
        description_key = f"shop.item.description.{desc_id}" if desc_id > 0 else ""
        english_name = entries.get(text_key, "") if text_key else ""
        record = {
            "id": shop_item_id,
            "name": english_name or f"Shop Item {shop_item_id}",
            "name_found": bool(english_name),
            "matched_text_key": text_key if english_name else "",
            "description": entries.get(description_key, "") if description_key else "",
            "description_text_key": description_key if description_key in entries else "",
        }
        for field in KIND_CONFIG["shop_items"]["extra_fields"]:
            if field in row:
                record[field] = row[field]

        contents = []
        for content_row in sorted(content_by_shop_item_id.get(shop_item_id, []), key=lambda current: int(current.get("SortOrder", 0) or 0)):
            possession_type = int(content_row.get("PossessionType", 0) or 0)
            possession_id = int(content_row.get("PossessionId", 0) or 0)
            contents.append(
                {
                    "possession_type": possession_type,
                    "possession_id": possession_id,
                    "count": int(content_row.get("Count", 0) or 0),
                    "sort_order": int(content_row.get("SortOrder", 0) or 0),
                    "possession_name": possession_name(possession_type, possession_id),
                }
            )
        record["contents"] = contents
        records.append(record)

    return records


def load_consumable_name_map(master_data_dir: Path, text_root: Path) -> dict[int, str]:
    config = KIND_CONFIG["consumables"]
    rows = load_json_array(master_data_dir / config["master_data_file"])
    entries = load_bundle_entries(text_root, config["bundle_key"], config.get("bundle_dirs"))
    records = build_records(rows, entries, config)
    return {int(record["id"]): record["name"] for record in records}


def load_important_item_name_map(master_data_dir: Path, text_root: Path) -> dict[int, str]:
    config = KIND_CONFIG["important_items"]
    rows = load_json_array(master_data_dir / config["master_data_file"])
    entries = load_bundle_entries(text_root, config["bundle_key"], config.get("bundle_dirs"))
    records = build_important_item_records(rows, entries, config)
    return {int(record["id"]): record["name"] for record in records}


def load_weapon_record_map(
    master_data_dir: Path,
    text_root: Path,
) -> dict[int, dict[str, Any]]:
    config = KIND_CONFIG["weapons"]
    rows = load_json_array(master_data_dir / config["master_data_file"])
    entries = load_bundle_entries(text_root, config["bundle_key"], config.get("bundle_dirs"))
    evolution_orders = load_weapon_evolution_orders(master_data_dir)
    records = build_weapon_records(rows, entries, evolution_orders, config)
    return {int(record["id"]): record for record in records}


def load_parts_group_record_map(
    master_data_dir: Path,
    text_root: Path,
) -> dict[int, dict[str, Any]]:
    master_data_root = master_data_dir
    group_rows = load_json_array(master_data_root / "EntityMPartsGroupTable.json")
    entries = load_bundle_entries(text_root, "parts", ["possession"])
    records: dict[int, dict[str, Any]] = {}
    for row in sorted(group_rows, key=lambda current: int(current["PartsGroupId"])):
        group_id = int(row.get("PartsGroupId", 0) or 0)
        asset_id = int(row.get("PartsGroupAssetId", 0) or 0)
        text_key = f"parts.group.name.{asset_id}" if asset_id > 0 else ""
        english_name = entries.get(text_key, "") if text_key else ""
        records[group_id] = {
            "id": group_id,
            "name": english_name or f"Parts Group {group_id}",
            "name_found": bool(english_name),
            "matched_text_key": text_key if english_name else "",
            "parts_group_asset_id": asset_id,
        }
    return records


def load_quest_record_map(
    master_data_dir: Path,
    text_root: Path,
) -> dict[int, dict[str, Any]]:
    config = KIND_CONFIG["quests"]
    rows = load_json_array(master_data_dir / config["master_data_file"])
    entries = load_bundle_entries(text_root, config["bundle_key"], config.get("bundle_dirs"))
    records = build_quest_records(rows, entries, config)
    return {int(record["id"]): record for record in records}


def difficulty_label(difficulty_type: int) -> str:
    labels = {
        1: "Difficulty 1",
        2: "Difficulty 2",
        3: "Difficulty 3",
    }
    return labels.get(difficulty_type, f"Difficulty {difficulty_type}")


def build_premium_item_records(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda current: int(current["PremiumItemId"])):
        premium_item_id = int(row["PremiumItemId"])
        premium_item_type = int(row.get("PremiumItemType", 0) or 0)
        records.append(
            {
                "id": premium_item_id,
                "name": f"Premium Item {premium_item_id}",
                "name_found": False,
                "matched_text_key": "",
                "PremiumItemType": premium_item_type,
                "StartDatetime": int(row.get("StartDatetime", 0) or 0),
                "EndDatetime": int(row.get("EndDatetime", 0) or 0),
            }
        )
    return records


def build_character_rebirth_records(
    master_data_dir: Path,
    text_root: Path,
) -> list[dict[str, Any]]:
    master_data_root = master_data_dir
    rebirth_rows = load_json_array(master_data_root / "EntityMCharacterRebirthTable.json")
    step_rows = load_json_array(master_data_root / "EntityMCharacterRebirthStepGroupTable.json")
    material_rows = load_json_array(master_data_root / "EntityMCharacterRebirthMaterialGroupTable.json")
    character_names, _ = build_character_name_map(master_data_dir, text_root)
    material_names = load_material_name_map(master_data_dir, text_root)

    steps_by_group_id: dict[int, list[dict[str, Any]]] = {}
    for row in step_rows:
        group_id = int(row.get("CharacterRebirthStepGroupId", 0) or 0)
        if group_id <= 0:
            continue
        steps_by_group_id.setdefault(group_id, []).append(row)
    for group_steps in steps_by_group_id.values():
        group_steps.sort(key=lambda current: int(current.get("BeforeRebirthCount", 0) or 0))

    materials_by_group_id: dict[int, list[dict[str, Any]]] = {}
    for row in material_rows:
        group_id = int(row.get("CharacterRebirthMaterialGroupId", 0) or 0)
        if group_id <= 0:
            continue
        materials_by_group_id.setdefault(group_id, []).append(row)
    for group_materials in materials_by_group_id.values():
        group_materials.sort(key=lambda current: int(current.get("SortOrder", 0) or 0))

    records: list[dict[str, Any]] = []
    for row in sorted(rebirth_rows, key=lambda current: int(current["CharacterId"])):
        character_id = int(row["CharacterId"])
        step_group_id = int(row.get("CharacterRebirthStepGroupId", 0) or 0)
        character_name = character_names.get(character_id, "")
        step_payload = []
        for step_row in steps_by_group_id.get(step_group_id, []):
            material_group_id = int(step_row.get("CharacterRebirthMaterialGroupId", 0) or 0)
            materials = []
            for material_row in materials_by_group_id.get(material_group_id, []):
                material_id = int(material_row.get("MaterialId", 0) or 0)
                materials.append(
                    {
                        "material_id": material_id,
                        "material_name": material_names.get(material_id, f"Material {material_id}"),
                        "count": int(material_row.get("Count", 0) or 0),
                        "sort_order": int(material_row.get("SortOrder", 0) or 0),
                    }
                )
            step_payload.append(
                {
                    "before_rebirth_count": int(step_row.get("BeforeRebirthCount", 0) or 0),
                    "costume_level_limit_up": int(step_row.get("CostumeLevelLimitUp", 0) or 0),
                    "character_rebirth_material_group_id": material_group_id,
                    "materials": materials,
                }
            )

        records.append(
            {
                "id": character_id,
                "name": character_name or f"Character Rebirth {character_id}",
                "name_found": bool(character_name),
                "matched_text_key": "",
                "character_id": character_id,
                "character_name": character_name,
                "CharacterRebirthStepGroupId": step_group_id,
                "CharacterAssignmentType": int(row.get("CharacterAssignmentType", 0) or 0),
                "SortOrder": int(row.get("SortOrder", 0) or 0),
                "max_rebirth_count": len(step_payload),
                "steps": step_payload,
            }
        )

    return records


def build_weapon_note_records(
    master_data_dir: Path,
    text_root: Path,
) -> list[dict[str, Any]]:
    weapon_records = load_weapon_record_map(master_data_dir, text_root)
    records: list[dict[str, Any]] = []
    for weapon_id in sorted(weapon_records):
        weapon_record = weapon_records[weapon_id]
        records.append(
            {
                "id": weapon_id,
                "name": weapon_record["name"],
                "name_found": bool(weapon_record.get("name_found")),
                "matched_text_key": weapon_record.get("matched_text_key", ""),
                "weapon_id": weapon_id,
                "weapon_name": weapon_record["name"],
                "derived_from": "weapons",
                "note_table_rows_present": False,
            }
        )
    return records


def build_parts_group_note_records(
    master_data_dir: Path,
    text_root: Path,
) -> list[dict[str, Any]]:
    group_records = load_parts_group_record_map(master_data_dir, text_root)
    records: list[dict[str, Any]] = []
    for group_id in sorted(group_records):
        group_record = group_records[group_id]
        records.append(
            {
                "id": group_id,
                "name": group_record["name"],
                "name_found": bool(group_record.get("name_found")),
                "matched_text_key": group_record.get("matched_text_key", ""),
                "parts_group_id": group_id,
                "parts_group_asset_id": group_record.get("parts_group_asset_id", 0),
                "derived_from": "parts_groups",
                "note_table_rows_present": False,
            }
        )
    return records


def build_main_quest_records(
    master_data_dir: Path,
    text_root: Path,
) -> list[dict[str, Any]]:
    master_data_root = master_data_dir
    chapter_rows = load_json_array(master_data_root / "EntityMMainQuestChapterTable.json")
    route_rows = load_json_array(master_data_root / "EntityMMainQuestRouteTable.json")
    sequence_group_rows = load_json_array(master_data_root / "EntityMMainQuestSequenceGroupTable.json")
    sequence_rows = load_json_array(master_data_root / "EntityMMainQuestSequenceTable.json")
    entries = load_bundle_entries(text_root, "main_quest", ["quest"])
    character_names, _ = build_character_name_map(master_data_dir, text_root)
    quest_records = load_quest_record_map(master_data_dir, text_root)

    route_by_id = {int(row["MainQuestRouteId"]): row for row in route_rows}
    sequence_group_map: dict[int, list[dict[str, Any]]] = {}
    for row in sequence_group_rows:
        group_id = int(row.get("MainQuestSequenceGroupId", 0) or 0)
        if group_id <= 0:
            continue
        sequence_group_map.setdefault(group_id, []).append(row)
    sequence_rows_map: dict[int, list[dict[str, Any]]] = {}
    for row in sequence_rows:
        sequence_id = int(row.get("MainQuestSequenceId", 0) or 0)
        if sequence_id <= 0:
            continue
        sequence_rows_map.setdefault(sequence_id, []).append(row)

    records: list[dict[str, Any]] = []
    for row in sorted(chapter_rows, key=lambda current: int(current["MainQuestChapterId"])):
        chapter_id = int(row["MainQuestChapterId"])
        route_id = int(row.get("MainQuestRouteId", 0) or 0)
        route_row = route_by_id.get(route_id, {})
        season_id = int(route_row.get("MainQuestSeasonId", 0) or 0)
        route_sort = int(route_row.get("SortOrder", 0) or 0)
        chapter_sort = int(row.get("SortOrder", 0) or 0)
        text_key = (
            f"quest.main.chapter_title.{season_id}.{route_sort}.{chapter_sort}"
            if season_id > 0 and route_sort > 0 and chapter_sort >= 0
            else ""
        )
        english_name = entries.get(text_key, "") if text_key else ""
        season_title_key = f"quest.main.season_title.{season_id}" if season_id > 0 else ""
        season_title = entries.get(season_title_key, "") if season_title_key else ""
        character_id = int(route_row.get("CharacterId", 0) or 0)

        sequence_group_id = int(row.get("MainQuestSequenceGroupId", 0) or 0)
        difficulties = []
        for group_row in sorted(
            sequence_group_map.get(sequence_group_id, []),
            key=lambda current: int(current.get("DifficultyType", 0) or 0),
        ):
            difficulty_type = int(group_row.get("DifficultyType", 0) or 0)
            sequence_id = int(group_row.get("MainQuestSequenceId", 0) or 0)
            quests = []
            for sequence_row in sorted(
                sequence_rows_map.get(sequence_id, []),
                key=lambda current: int(current.get("SortOrder", 0) or 0),
            ):
                quest_id = int(sequence_row.get("QuestId", 0) or 0)
                quest_record = quest_records.get(quest_id, {})
                quests.append(
                    {
                        "quest_id": quest_id,
                        "quest_name": quest_record.get("name", f"Quest {quest_id}"),
                        "sort_order": int(sequence_row.get("SortOrder", 0) or 0),
                    }
                )
            difficulties.append(
                {
                    "difficulty_type": difficulty_type,
                    "difficulty_label": difficulty_label(difficulty_type),
                    "main_quest_sequence_id": sequence_id,
                    "quests": quests,
                }
            )

        records.append(
            {
                "id": chapter_id,
                "name": english_name or f"Main Quest Chapter {chapter_id}",
                "name_found": bool(english_name),
                "matched_text_key": text_key if english_name else "",
                "MainQuestChapterId": chapter_id,
                "MainQuestRouteId": route_id,
                "MainQuestSeasonId": season_id,
                "season_title": season_title,
                "season_title_text_key": season_title_key if season_title else "",
                "route_sort_order": route_sort,
                "chapter_sort_order": chapter_sort,
                "character_id": character_id,
                "character_name": character_names.get(character_id, ""),
                "MainQuestSequenceGroupId": sequence_group_id,
                "difficulties": difficulties,
                "StartDatetime": int(row.get("StartDatetime", 0) or 0),
                "IsInvisibleInLibrary": bool(row.get("IsInvisibleInLibrary", False)),
            }
        )

    return records


def build_event_quest_records(
    master_data_dir: Path,
    text_root: Path,
) -> list[dict[str, Any]]:
    master_data_root = master_data_dir
    chapter_rows = load_json_array(master_data_root / "EntityMEventQuestChapterTable.json")
    sequence_group_rows = load_json_array(master_data_root / "EntityMEventQuestSequenceGroupTable.json")
    sequence_rows = load_json_array(master_data_root / "EntityMEventQuestSequenceTable.json")
    entries = load_bundle_entries(text_root, "event_quest", ["quest"])
    quest_records = load_quest_record_map(master_data_dir, text_root)

    sequence_group_map: dict[int, list[dict[str, Any]]] = {}
    for row in sequence_group_rows:
        group_id = int(row.get("EventQuestSequenceGroupId", 0) or 0)
        if group_id <= 0:
            continue
        sequence_group_map.setdefault(group_id, []).append(row)

    sequence_rows_map: dict[int, list[dict[str, Any]]] = {}
    for row in sequence_rows:
        sequence_id = int(row.get("EventQuestSequenceId", 0) or 0)
        if sequence_id <= 0:
            continue
        sequence_rows_map.setdefault(sequence_id, []).append(row)

    records: list[dict[str, Any]] = []
    for row in sorted(chapter_rows, key=lambda current: int(current["EventQuestChapterId"])):
        chapter_id = int(row["EventQuestChapterId"])
        text_key = f"quest.event.chapter_title.{chapter_id}"
        english_name = entries.get(text_key, "")
        sequence_group_id = int(row.get("EventQuestSequenceGroupId", 0) or 0)
        difficulties = []
        for group_row in sorted(
            sequence_group_map.get(sequence_group_id, []),
            key=lambda current: int(current.get("DifficultyType", 0) or 0),
        ):
            difficulty_type = int(group_row.get("DifficultyType", 0) or 0)
            sequence_id = int(group_row.get("EventQuestSequenceId", 0) or 0)
            quests = []
            for sequence_row in sorted(
                sequence_rows_map.get(sequence_id, []),
                key=lambda current: int(current.get("SortOrder", 0) or 0),
            ):
                quest_id = int(sequence_row.get("QuestId", 0) or 0)
                quest_record = quest_records.get(quest_id, {})
                quests.append(
                    {
                        "quest_id": quest_id,
                        "quest_name": quest_record.get("name", f"Quest {quest_id}"),
                        "sort_order": int(sequence_row.get("SortOrder", 0) or 0),
                    }
                )
            difficulties.append(
                {
                    "difficulty_type": difficulty_type,
                    "difficulty_label": difficulty_label(difficulty_type),
                    "event_quest_sequence_id": sequence_id,
                    "quests": quests,
                }
            )

        records.append(
            {
                "id": chapter_id,
                "name": english_name or f"Event Quest Chapter {chapter_id}",
                "name_found": bool(english_name),
                "matched_text_key": text_key if english_name else "",
                "EventQuestChapterId": chapter_id,
                "EventQuestType": int(row.get("EventQuestType", 0) or 0),
                "BannerAssetId": int(row.get("BannerAssetId", 0) or 0),
                "EventQuestLinkId": int(row.get("EventQuestLinkId", 0) or 0),
                "EventQuestDisplayItemGroupId": int(row.get("EventQuestDisplayItemGroupId", 0) or 0),
                "EventQuestSequenceGroupId": sequence_group_id,
                "DisplaySortOrder": int(row.get("DisplaySortOrder", 0) or 0),
                "StartDatetime": int(row.get("StartDatetime", 0) or 0),
                "EndDatetime": int(row.get("EndDatetime", 0) or 0),
                "difficulties": difficulties,
            }
        )

    return records


def build_extra_quest_records(
    master_data_dir: Path,
    text_root: Path,
) -> list[dict[str, Any]]:
    master_data_root = master_data_dir
    rows = load_json_array(master_data_root / "EntityMExtraQuestGroupTable.json")
    quest_records = load_quest_record_map(master_data_dir, text_root)
    records: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda current: int(current["ExtraQuestId"])):
        extra_quest_id = int(row["ExtraQuestId"])
        quest_id = int(row.get("QuestId", 0) or 0)
        quest_record = quest_records.get(quest_id, {})
        english_name = quest_record.get("name", "")
        records.append(
            {
                "id": extra_quest_id,
                "name": english_name or f"Extra Quest {extra_quest_id}",
                "name_found": bool(english_name),
                "matched_text_key": quest_record.get("matched_text_key", "") if english_name else "",
                "ExtraQuestId": extra_quest_id,
                "ExtraQuestIndex": int(row.get("ExtraQuestIndex", 0) or 0),
                "QuestId": quest_id,
                "quest_name": english_name or f"Quest {quest_id}",
            }
        )
    return records


def build_side_story_quest_records(
    master_data_dir: Path,
    text_root: Path,
) -> list[dict[str, Any]]:
    master_data_root = master_data_dir
    rows = load_json_array(master_data_root / "EntityMSideStoryQuestTable.json")
    limit_rows = load_json_array(master_data_root / "EntityMSideStoryQuestLimitContentTable.json")
    scene_rows = load_json_array(master_data_root / "EntityMSideStoryQuestSceneTable.json")
    entries = load_bundle_entries(text_root, "event_quest", ["quest"])
    character_names, _ = build_character_name_map(master_data_dir, text_root)

    limit_by_id = {
        int(row.get("SideStoryQuestLimitContentId", 0) or 0): row
        for row in limit_rows
        if int(row.get("SideStoryQuestLimitContentId", 0) or 0) > 0
    }
    scenes_by_quest_id: dict[int, list[dict[str, Any]]] = {}
    for row in scene_rows:
        quest_id = int(row.get("SideStoryQuestId", 0) or 0)
        if quest_id <= 0:
            continue
        scenes_by_quest_id.setdefault(quest_id, []).append(row)

    records: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda current: int(current["SideStoryQuestId"])):
        side_story_quest_id = int(row["SideStoryQuestId"])
        target_id = int(row.get("TargetId", 0) or 0)
        limit_row = limit_by_id.get(target_id, {})
        character_id = int(limit_row.get("CharacterId", 0) or 0)
        event_chapter_id = int(limit_row.get("EventQuestChapterId", 0) or 0)
        difficulty_type = int(limit_row.get("DifficultyType", 0) or 0)
        event_text_key = f"quest.event.chapter_title.{event_chapter_id}" if event_chapter_id > 0 else ""
        event_chapter_name = entries.get(event_text_key, "") if event_text_key else ""
        character_name = character_names.get(character_id, "")
        english_name_parts = [part for part in (character_name, event_chapter_name, difficulty_label(difficulty_type)) if part]
        english_name = " - ".join(english_name_parts)
        scene_ids = [
            int(scene_row.get("SideStoryQuestSceneId", 0) or 0)
            for scene_row in sorted(scenes_by_quest_id.get(side_story_quest_id, []), key=lambda current: int(current.get("SortOrder", 0) or 0))
        ]
        records.append(
            {
                "id": side_story_quest_id,
                "name": english_name or f"Side Story Quest {side_story_quest_id}",
                "name_found": bool(character_name or event_chapter_name),
                "matched_text_key": event_text_key if event_chapter_name else "",
                "SideStoryQuestId": side_story_quest_id,
                "SideStoryQuestType": int(row.get("SideStoryQuestType", 0) or 0),
                "TargetId": target_id,
                "character_id": character_id,
                "character_name": character_name,
                "event_quest_chapter_id": event_chapter_id,
                "event_quest_chapter_name": event_chapter_name,
                "difficulty_type": difficulty_type,
                "difficulty_label": difficulty_label(difficulty_type),
                "scene_ids": scene_ids,
                "head_scene_id": scene_ids[0] if scene_ids else 0,
                "scene_count": len(scene_ids),
                "next_side_story_quest_id": int(limit_row.get("NextSideStoryQuestId", 0) or 0),
            }
        )
    return records


def build_cage_ornament_reward_records(
    master_data_dir: Path,
    text_root: Path,
) -> list[dict[str, Any]]:
    master_data_root = master_data_dir
    ornament_rows = load_json_array(master_data_root / "EntityMCageOrnamentTable.json")
    reward_rows = load_json_array(master_data_root / "EntityMCageOrnamentRewardTable.json")
    consumable_names = load_consumable_name_map(master_data_dir, text_root)
    character_names, _ = build_character_name_map(master_data_dir, text_root)

    reward_by_id = {
        int(row.get("CageOrnamentRewardId", 0) or 0): row
        for row in reward_rows
        if int(row.get("CageOrnamentRewardId", 0) or 0) > 0
    }

    records: list[dict[str, Any]] = []
    for row in sorted(ornament_rows, key=lambda current: int(current["CageOrnamentId"])):
        ornament_id = int(row["CageOrnamentId"])
        reward_id = int(row.get("CageOrnamentRewardId", 0) or 0)
        reward_row = reward_by_id.get(reward_id, {})
        possession_type = int(reward_row.get("PossessionType", 0) or 0)
        possession_id = int(reward_row.get("PossessionId", 0) or 0)
        if possession_type == 5:
            reward_name = consumable_names.get(possession_id, "")
        elif possession_type == 6:
            reward_name = character_names.get(possession_id, "")
        else:
            reward_name = ""
        records.append(
            {
                "id": ornament_id,
                "name": reward_name or f"Cage Ornament {ornament_id}",
                "name_found": bool(reward_name),
                "matched_text_key": "",
                "CageOrnamentId": ornament_id,
                "CageOrnamentRewardId": reward_id,
                "reward_possession_type": possession_type,
                "reward_possession_id": possession_id,
                "reward_count": int(reward_row.get("Count", 0) or 0),
                "reward_name": reward_name or f"Possession {possession_id}",
                "StartDatetime": int(row.get("StartDatetime", 0) or 0),
                "EndDatetime": int(row.get("EndDatetime", 0) or 0),
            }
        )
    return records


def build_gacha_medal_records(
    master_data_dir: Path,
    text_root: Path,
) -> list[dict[str, Any]]:
    master_data_root = master_data_dir
    rows = load_json_array(master_data_root / "EntityMGachaMedalTable.json")
    consumable_names = load_consumable_name_map(master_data_dir, text_root)
    records: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda current: int(current["GachaMedalId"])):
        medal_id = int(row["GachaMedalId"])
        consumable_item_id = int(row.get("ConsumableItemId", 0) or 0)
        english_name = consumable_names.get(consumable_item_id, "")
        records.append(
            {
                "id": medal_id,
                "name": english_name or f"Gacha Medal {medal_id}",
                "name_found": bool(english_name),
                "matched_text_key": "",
                "ConsumableItemId": consumable_item_id,
                "consumable_name": english_name or f"Consumable {consumable_item_id}",
                "CeilingCount": int(row.get("CeilingCount", 0) or 0),
                "ShopTransitionGachaId": int(row.get("ShopTransitionGachaId", 0) or 0),
                "AutoConvertDatetime": int(row.get("AutoConvertDatetime", 0) or 0),
                "ConversionRate": int(row.get("ConversionRate", 0) or 0),
            }
        )
    return records


def build_gacha_banner_records(
    master_data_dir: Path,
    text_root: Path,
) -> list[dict[str, Any]]:
    master_data_root = master_data_dir
    rows = load_json_array(master_data_root / "EntityMMomBannerTable.json")
    entries = load_bundle_entries(text_root, "gacha_title", [""])
    records: list[dict[str, Any]] = []
    gacha_rows = [row for row in rows if int(row.get("DestinationDomainType", 0) or 0) == 1]
    for row in sorted(gacha_rows, key=lambda current: int(current["MomBannerId"])):
        banner_id = int(row["MomBannerId"])
        asset_name = str(row.get("BannerAssetName", "") or "")
        destination_id = int(row.get("DestinationDomainId", 0) or 0)
        candidate_keys = []
        if asset_name:
            candidate_keys.append(f"gacha.title.{asset_name}")
        if destination_id > 0:
            candidate_keys.append(f"gacha.title.limited_{destination_id}")
            candidate_keys.append(f"gacha.title.limited_{destination_id:02d}")
        matched_key = ""
        english_name = ""
        for key in candidate_keys:
            if key in entries:
                matched_key = key
                english_name = entries[key]
                break
        record = {
            "id": banner_id,
            "name": english_name or f"Gacha Banner {banner_id}",
            "name_found": bool(english_name),
            "matched_text_key": matched_key,
        }
        for field in KIND_CONFIG["gacha_banners"]["extra_fields"]:
            if field in row:
                record[field] = row[field]
        records.append(record)
    return records


def build_gift_text_records(
    master_data_dir: Path,
) -> list[dict[str, Any]]:
    rows = load_json_array(master_data_dir / "EntityMGiftTextTable.json")
    records: list[dict[str, Any]] = []
    for row in rows:
        if int(row.get("LanguageType", 0) or 0) != 2:
            continue
        text_id = int(row.get("GiftTextId", 0) or 0)
        text = str(row.get("Text", "") or "").strip()
        records.append(
            {
                "id": text_id,
                "name": text or f"Gift Text {text_id}",
                "name_found": bool(text and text != "-"),
                "matched_text_key": f"gift.comment.{text_id}" if text and text != "-" else "",
                "LanguageType": 2,
                "Text": text,
            }
        )
    records.sort(key=lambda current: int(current["id"]))
    return records


def build_shop_replaceable_gem_records(
    rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda current: int(current["LineupUpdateCountLowerLimit"])):
        lower_limit = int(row["LineupUpdateCountLowerLimit"])
        necessary_gem = int(row.get("NecessaryGem", 0) or 0)
        records.append(
            {
                "id": lower_limit,
                "name": f"Refresh Cost {necessary_gem} Gems",
                "name_found": True,
                "matched_text_key": "",
                "LineupUpdateCountLowerLimit": lower_limit,
                "NecessaryGem": necessary_gem,
            }
        )
    return records


def extract_kind(
    kind: str,
    master_data_dir: Path,
    text_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    config = KIND_CONFIG[kind]
    master_data_path = master_data_dir / config["master_data_file"]
    bundle_key = config.get("bundle_key", "")
    bundle_entries = load_bundle_entries(text_root, bundle_key, config.get("bundle_dirs")) if bundle_key else {}
    rows = load_json_array(master_data_path)
    if kind == "weapons":
        evolution_orders = load_weapon_evolution_orders(master_data_dir)
        records = build_weapon_records(rows, bundle_entries, evolution_orders, config)
    elif kind == "characters":
        records = build_character_records(rows, bundle_entries, config)
    elif kind == "costumes":
        character_names, playable_characters = build_character_name_map(master_data_dir, text_root)
        records = build_costume_records(rows, bundle_entries, config, character_names, playable_characters)
    elif kind == "companions":
        records = build_companion_records(rows, bundle_entries, config)
    elif kind == "thoughts":
        catalog_terms = load_thought_catalog_terms(master_data_dir)
        records = build_thought_records(rows, bundle_entries, config, catalog_terms)
    elif kind == "parts":
        parts_group_assets = load_parts_group_assets(master_data_dir)
        records = build_parts_records(rows, bundle_entries, config, parts_group_assets)
    elif kind == "abilities":
        records = build_ability_records(master_data_dir, bundle_entries)
    elif kind == "skills":
        records = build_skill_records(rows, bundle_entries, config, master_data_dir)
    elif kind == "character_boards":
        records = build_character_board_records(master_data_dir, text_root)
    elif kind == "weapon_skills":
        records = build_weapon_slot_records(master_data_dir, text_root, "skill")
    elif kind == "weapon_abilities":
        records = build_weapon_slot_records(master_data_dir, text_root, "ability")
    elif kind == "costume_active_skills":
        records = build_costume_active_skill_records(master_data_dir, text_root)
    elif kind == "weapon_stories":
        records = build_weapon_story_records(master_data_dir, text_root)
    elif kind == "character_board_abilities":
        records = build_character_board_ability_records(master_data_dir, text_root)
    elif kind == "character_board_status_ups":
        records = build_character_board_status_up_records(master_data_dir, text_root)
    elif kind == "weapon_awakens":
        records = build_weapon_awaken_records(master_data_dir, text_root)
    elif kind == "costume_awaken_status_ups":
        records = build_costume_awaken_status_up_records(master_data_dir, text_root)
    elif kind == "costume_awaken_abilities":
        records = build_costume_awaken_ability_records(master_data_dir, text_root)
    elif kind == "important_items":
        records = build_important_item_records(rows, bundle_entries, config)
    elif kind == "missions":
        records = build_mission_records(rows, bundle_entries, config)
    elif kind == "quests":
        records = build_quest_records(rows, bundle_entries, config)
    elif kind == "quest_missions":
        records = build_quest_mission_records(rows, bundle_entries, config)
    elif kind == "tutorials":
        records = build_tutorial_records(master_data_dir, text_root)
    elif kind == "shops":
        records = build_shop_records(rows, bundle_entries, config)
    elif kind == "shop_items":
        records = build_shop_item_records(master_data_dir, text_root)
    elif kind == "gacha_medals":
        records = build_gacha_medal_records(master_data_dir, text_root)
    elif kind == "gacha_banners":
        records = build_gacha_banner_records(master_data_dir, text_root)
    elif kind == "gift_texts":
        records = build_gift_text_records(master_data_dir)
    elif kind == "shop_replaceable_gems":
        records = build_shop_replaceable_gem_records(rows)
    elif kind == "premium_items":
        records = build_premium_item_records(rows)
    elif kind == "character_rebirths":
        records = build_character_rebirth_records(master_data_dir, text_root)
    elif kind == "weapon_notes":
        records = build_weapon_note_records(master_data_dir, text_root)
    elif kind == "parts_group_notes":
        records = build_parts_group_note_records(master_data_dir, text_root)
    elif kind == "main_quests":
        records = build_main_quest_records(master_data_dir, text_root)
    elif kind == "event_quests":
        records = build_event_quest_records(master_data_dir, text_root)
    elif kind == "extra_quests":
        records = build_extra_quest_records(master_data_dir, text_root)
    elif kind == "side_story_quests":
        records = build_side_story_quest_records(master_data_dir, text_root)
    elif kind == "cage_ornament_rewards":
        records = build_cage_ornament_reward_records(master_data_dir, text_root)
    else:
        records = build_records(rows, bundle_entries, config)

    name_found_count = sum(1 for record in records if record["name_found"])
    payload = {
        "kind": kind,
        "master_data_dir": sanitize_output_path(master_data_dir),
        "text_revision": text_root.parent.parent.parent.name,
        "source_files": {
            "master_data": sanitize_output_path(master_data_path),
            "text_root": sanitize_output_path(text_root),
        },
        "summary": {
            "total_records": len(records),
            "resolved_names": name_found_count,
            "unresolved_names": len(records) - name_found_count,
        },
        "records": records,
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{kind}.json"
    output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    undefined_records = [record for record in records if not record.get("name_found")]
    undefined_payload = {
        "kind": f"undefined_{kind}",
        "source_kind": kind,
        "master_data_dir": sanitize_output_path(master_data_dir),
        "text_revision": text_root.parent.parent.parent.name,
        "source_files": {
            "master_data": sanitize_output_path(master_data_path),
            "text_root": sanitize_output_path(text_root),
        },
        "summary": {
            "total_records": len(undefined_records),
        },
        "records": undefined_records,
    }
    undefined_output_path = output_dir / f"undefined_{kind}.json"
    undefined_output_path.write_text(
        json.dumps(undefined_payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    print(f"undefined_{kind}: wrote {undefined_output_path} ({len(undefined_records)} unresolved records)")

    if kind == "characters":
        playable_records = [record for record in records if record.get("is_playable_character")]
        playable_payload = {
            "kind": "playable_characters",
            "master_data_dir": sanitize_output_path(master_data_dir),
            "text_revision": text_root.parent.parent.parent.name,
            "source_files": {
                "master_data": sanitize_output_path(master_data_path),
                "text_root": sanitize_output_path(text_root),
            },
            "summary": {
                "total_records": len(playable_records),
                "resolved_names": sum(1 for record in playable_records if record["name_found"]),
                "unresolved_names": sum(1 for record in playable_records if not record["name_found"]),
            },
            "records": playable_records,
        }
        playable_output_path = output_dir / "playable_characters.json"
        playable_output_path.write_text(
            json.dumps(playable_payload, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        print(
            f"playable_characters: wrote {playable_output_path} "
            f"({playable_payload['summary']['resolved_names']}/{len(playable_records)} names resolved from text bundles)"
        )
    elif kind == "costumes":
        playable_records = [record for record in records if record.get("is_playable_character_costume")]
        playable_payload = {
            "kind": "playable_costumes",
            "master_data_dir": sanitize_output_path(master_data_dir),
            "text_revision": text_root.parent.parent.parent.name,
            "source_files": {
                "master_data": sanitize_output_path(master_data_path),
                "text_root": sanitize_output_path(text_root),
            },
            "summary": {
                "total_records": len(playable_records),
                "resolved_names": sum(1 for record in playable_records if record["name_found"]),
                "unresolved_names": sum(1 for record in playable_records if not record["name_found"]),
            },
            "records": playable_records,
        }
        playable_output_path = output_dir / "playable_costumes.json"
        playable_output_path.write_text(
            json.dumps(playable_payload, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        print(
            f"playable_costumes: wrote {playable_output_path} "
            f"({playable_payload['summary']['resolved_names']}/{len(playable_records)} names resolved from text bundles)"
        )

    print(
        f"{kind}: wrote {output_path} "
        f"({name_found_count}/{len(records)} names resolved from text bundles)"
    )
    return payload


def main() -> int:
    args = parse_args()
    master_data_dir = args.master_data_dir.resolve()
    revisions_dir = args.revisions_dir.resolve()

    if not master_data_dir.is_dir():
        raise SystemExit(f"master-data directory not found: {master_data_dir}")
    if not revisions_dir.is_dir():
        raise SystemExit(f"revisions directory not found: {revisions_dir}")

    text_root = resolve_text_root(revisions_dir, args.revision)

    skipped: list[tuple[str, str]] = []
    for kind in args.kinds:
        try:
            extract_kind(kind, master_data_dir, text_root, args.output_dir.resolve())
        except (json.JSONDecodeError, FileNotFoundError) as e:
            msg = f"{type(e).__name__}: {e}"
            print(f"WARN: skipping kind '{kind}' ({msg})", file=sys.stderr)
            skipped.append((kind, msg))

    if skipped:
        print(f"\n{len(skipped)} kind(s) skipped:", file=sys.stderr)
        for kind, msg in skipped:
            print(f"  - {kind}: {msg}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
