"""
GTO Poker Tournament Advisor
A local web-based tool for real-time GTO-approximated decisions during online tournament play.
"""

import json
import math
import itertools
from flask import Flask, render_template, request, jsonify
from collections import Counter

app = Flask(__name__)

# ─── Hand Rankings & Equity Tables ───────────────────────────────────────────

RANKS = "23456789TJQKA"
SUITS = "shdc"
RANK_VALUES = {r: i for i, r in enumerate(RANKS)}

# Preflop hand categories (simplified GTO ranges)
# Format: hand -> {position: action}
# Positions: UTG, MP, CO, BTN, SB, BB
# Actions: fold, open_raise, call, 3bet, all_in

PREMIUM_HANDS = {"AA", "KK", "QQ", "AKs", "AKo"}
STRONG_HANDS = {"JJ", "TT", "AQs", "AQo", "AJs", "KQs"}
GOOD_HANDS = {"99", "88", "ATs", "AJo", "KJs", "KQo", "QJs", "ATs"}
PLAYABLE_HANDS = {"77", "66", "55", "A9s", "A8s", "A7s", "A6s", "A5s", "A4s", "A3s", "A2s",
                  "KTs", "K9s", "QTs", "Q9s", "JTs", "J9s", "T9s", "98s", "87s", "76s", "65s", "54s",
                  "ATo", "KJo", "QJo", "JTo"}
MARGINAL_HANDS = {"44", "33", "22", "K8s", "K7s", "K6s", "K5s", "K4s", "K3s", "K2s",
                  "Q8s", "J8s", "T8s", "97s", "86s", "75s", "64s", "53s", "43s",
                  "A9o", "K9o", "Q9o", "J9o", "T9o", "98o"}


def normalize_hand(card1, card2):
    """Convert two cards to standard hand notation (e.g., AKs, QTo, JJ)."""
    r1, s1 = card1[0], card1[1]
    r2, s2 = card2[0], card2[1]

    v1, v2 = RANK_VALUES[r1], RANK_VALUES[r2]

    if v1 < v2:
        r1, r2 = r2, r1
        s1, s2 = s2, s1
        v1, v2 = v2, v1

    if r1 == r2:
        return r1 + r2  # Pair
    elif s1 == s2:
        return r1 + r2 + "s"  # Suited
    else:
        return r1 + r2 + "o"  # Offsuit


def hand_category(hand_str):
    """Categorize a hand into tiers."""
    if hand_str in PREMIUM_HANDS:
        return "premium"
    elif hand_str in STRONG_HANDS:
        return "strong"
    elif hand_str in GOOD_HANDS:
        return "good"
    elif hand_str in PLAYABLE_HANDS:
        return "playable"
    elif hand_str in MARGINAL_HANDS:
        return "marginal"
    else:
        return "trash"


# ─── Position Ranges (GTO-approximated open-raise ranges) ───────────────────

POSITION_OPEN_RANGES = {
    "UTG": {"premium", "strong"},
    "MP": {"premium", "strong", "good"},
    "CO": {"premium", "strong", "good", "playable"},
    "BTN": {"premium", "strong", "good", "playable", "marginal"},
    "SB": {"premium", "strong", "good", "playable"},
    "BB": set()  # BB doesn't open, defends
}

BB_DEFEND_VS_OPEN = {"premium", "strong", "good", "playable", "marginal"}
BB_DEFEND_VS_3BET = {"premium", "strong"}

# ─── Stack Depth / ICM Adjustments ──────────────────────────────────────────

def get_stack_category(bb_count):
    """Classify stack depth."""
    if bb_count <= 10:
        return "shove_or_fold"
    elif bb_count <= 15:
        return "short"
    elif bb_count <= 25:
        return "medium_short"
    elif bb_count <= 40:
        return "medium"
    elif bb_count <= 60:
        return "medium_deep"
    else:
        return "deep"


def get_push_fold_range(position, bb_count):
    """Nash push/fold ranges for short stacks."""
    # Simplified Nash equilibrium push ranges
    nash_ranges = {
        10: {
            "BTN": {"premium", "strong", "good", "playable", "marginal"},
            "SB": {"premium", "strong", "good", "playable"},
            "BB": {"premium", "strong", "good", "playable", "marginal"},
            "CO": {"premium", "strong", "good", "playable"},
            "MP": {"premium", "strong", "good"},
            "UTG": {"premium", "strong"},
        },
        7: {
            "BTN": {"premium", "strong", "good", "playable", "marginal", "trash"},
            "SB": {"premium", "strong", "good", "playable", "marginal"},
            "BB": {"premium", "strong", "good", "playable", "marginal"},
            "CO": {"premium", "strong", "good", "playable", "marginal"},
            "MP": {"premium", "strong", "good", "playable"},
            "UTG": {"premium", "strong", "good"},
        },
        5: {
            "BTN": {"premium", "strong", "good", "playable", "marginal", "trash"},
            "SB": {"premium", "strong", "good", "playable", "marginal", "trash"},
            "BB": {"premium", "strong", "good", "playable", "marginal", "trash"},
            "CO": {"premium", "strong", "good", "playable", "marginal", "trash"},
            "MP": {"premium", "strong", "good", "playable", "marginal"},
            "UTG": {"premium", "strong", "good", "playable"},
        }
    }

    if bb_count <= 5:
        key = 5
    elif bb_count <= 7:
        key = 7
    else:
        key = 10

    return nash_ranges.get(key, {}).get(position, {"premium", "strong"})


# ─── Postflop Engine ────────────────────────────────────────────────────────

BOARD_TEXTURES = {
    "dry": {"description": "Rainbow, disconnected board", "cbet_freq": 0.70, "cbet_size": 0.33},
    "semi_wet": {"description": "Some draws possible", "cbet_freq": 0.55, "cbet_size": 0.50},
    "wet": {"description": "Many draws, connected, suited", "cbet_freq": 0.40, "cbet_size": 0.66},
    "monotone": {"description": "Three of one suit", "cbet_freq": 0.30, "cbet_size": 0.75},
    "paired": {"description": "Paired board", "cbet_freq": 0.65, "cbet_size": 0.33},
}


def analyze_board_texture(board_cards):
    """Analyze the board texture from community cards."""
    if not board_cards or len(board_cards) < 3:
        return None

    ranks = [RANK_VALUES[c[0]] for c in board_cards]
    suits = [c[1] for c in board_cards]
    suit_counts = Counter(suits)
    rank_sorted = sorted(ranks)

    # Check for monotone
    if max(suit_counts.values()) >= 3:
        return "monotone"

    # Check for paired
    rank_counts = Counter(ranks)
    if max(rank_counts.values()) >= 2:
        return "paired"

    # Check connectivity
    gaps = sum(1 for i in range(len(rank_sorted) - 1) if rank_sorted[i + 1] - rank_sorted[i] <= 2)
    flush_draw = max(suit_counts.values()) >= 2

    if gaps >= 2 and flush_draw:
        return "wet"
    elif gaps >= 1 or flush_draw:
        return "semi_wet"
    else:
        return "dry"


def evaluate_hand_strength(hole_cards, board_cards):
    """Simplified hand strength evaluation."""
    all_cards = hole_cards + board_cards
    ranks = [RANK_VALUES[c[0]] for c in all_cards]
    suits = [c[1] for c in all_cards]

    hole_ranks = [RANK_VALUES[c[0]] for c in hole_cards]
    board_ranks = [RANK_VALUES[c[0]] for c in board_cards]

    rank_counts = Counter(ranks)
    suit_counts = Counter(suits)
    board_rank_counts = Counter(board_ranks)

    strength = "weak"
    made_hand = "high_card"
    draws = []

    # Check for made hands (simplified)
    max_count = max(rank_counts.values())
    pairs = [r for r, c in rank_counts.items() if c >= 2]
    trips = [r for r, c in rank_counts.items() if c >= 3]
    quads = [r for r, c in rank_counts.items() if c >= 4]

    # Flush check
    has_flush = False
    for suit, count in suit_counts.items():
        if count >= 5:
            has_flush = True
            break

    # Straight check (simplified)
    unique_ranks = sorted(set(ranks))
    has_straight = False
    for i in range(len(unique_ranks) - 4):
        if unique_ranks[i + 4] - unique_ranks[i] == 4:
            has_straight = True
            break
    # Wheel check
    if set([0, 1, 2, 3, 12]).issubset(set(ranks)):
        has_straight = True

    if quads:
        made_hand = "quads"
        strength = "monster"
    elif trips and len(pairs) >= 2:
        made_hand = "full_house"
        strength = "monster"
    elif has_flush:
        made_hand = "flush"
        strength = "very_strong"
    elif has_straight:
        made_hand = "straight"
        strength = "very_strong"
    elif trips:
        made_hand = "three_of_a_kind"
        # Set vs trips
        if any(r in hole_ranks for r in [rv for rv, c in rank_counts.items() if c >= 3]):
            if any(r in board_ranks for r in [rv for rv, c in rank_counts.items() if c >= 3]):
                strength = "strong"
            else:
                strength = "strong"  # pocket pair set
        else:
            strength = "medium"
    elif len(pairs) >= 2:
        made_hand = "two_pair"
        # Check if using both hole cards
        hole_pairs = [r for r in hole_ranks if r in pairs]
        if len(set(hole_pairs)) >= 1:
            strength = "strong" if max(pairs) >= 10 else "medium"
        else:
            strength = "medium"
    elif pairs:
        made_hand = "one_pair"
        pair_rank = pairs[0]
        # Overpair, top pair, middle pair, bottom pair
        if pair_rank in hole_ranks and board_rank_counts.get(pair_rank, 0) == 0:
            # Pocket pair
            if pair_rank > max(board_ranks):
                strength = "strong"  # overpair
                made_hand = "overpair"
            else:
                strength = "medium"
        elif pair_rank == max(board_ranks) and pair_rank in hole_ranks:
            strength = "medium"  # top pair
            made_hand = "top_pair"
        elif pair_rank in hole_ranks:
            strength = "weak_medium"
            made_hand = "middle/bottom_pair"
        else:
            strength = "weak"
            made_hand = "board_pair"
    else:
        # Check for overcards
        if all(r > max(board_ranks) for r in hole_ranks):
            strength = "weak_draw"
            made_hand = "overcards"
        else:
            strength = "weak"
            made_hand = "high_card"

    # Check for draws
    for suit, count in suit_counts.items():
        hole_suit_count = sum(1 for c in hole_cards if c[1] == suit)
        if count == 4 and hole_suit_count >= 1:
            draws.append("flush_draw")

    # Open-ended straight draw check (simplified)
    for r in hole_ranks:
        consecutive = 0
        for offset in range(-4, 5):
            if (r + offset) in set(ranks):
                consecutive += 1
            else:
                consecutive = 0
            if consecutive >= 4:
                draws.append("straight_draw")
                break

    return {
        "strength": strength,
        "made_hand": made_hand,
        "draws": list(set(draws)),
    }


# ─── GTO Decision Engine ────────────────────────────────────────────────────

def get_preflop_advice(hand_str, position, stack_bb, facing_action, villain_position=None, pot_bb=1.5, raise_size_bb=0):
    """Generate preflop GTO-approximated advice."""
    cat = hand_category(hand_str)
    stack_cat = get_stack_category(stack_bb)

    advice = {
        "hand": hand_str,
        "category": cat,
        "position": position,
        "stack_depth": f"{stack_bb} BB ({stack_cat})",
        "action": "",
        "sizing": "",
        "reasoning": "",
        "confidence": "",
        "alternative": "",
    }

    # ── Shove or Fold Zone ──
    if stack_cat == "shove_or_fold":
        push_range = get_push_fold_range(position, stack_bb)
        if cat in push_range:
            advice["action"] = "ALL-IN"
            advice["sizing"] = f"{stack_bb} BB"
            advice["reasoning"] = f"With {stack_bb}BB, Nash push/fold charts recommend shoving {hand_str} from {position}. Your fold equity + showdown equity make this +EV."
            advice["confidence"] = "HIGH" if cat in {"premium", "strong"} else "MEDIUM"
        else:
            advice["action"] = "FOLD"
            advice["sizing"] = "—"
            advice["reasoning"] = f"At {stack_bb}BB, {hand_str} is not in the Nash push range from {position}. Wait for a better spot."
            advice["confidence"] = "HIGH"
        return advice

    # ── Short Stack (11-15 BB) ──
    if stack_cat == "short":
        if facing_action == "unopened":
            if cat in {"premium", "strong"}:
                advice["action"] = "ALL-IN"
                advice["sizing"] = f"{stack_bb} BB"
                advice["reasoning"] = f"Short-stacked with a strong hand. Open-shoving maximizes fold equity and avoids difficult postflop spots."
                advice["confidence"] = "HIGH"
            elif cat in {"good", "playable"} and position in {"CO", "BTN", "SB"}:
                advice["action"] = "ALL-IN"
                advice["sizing"] = f"{stack_bb} BB"
                advice["reasoning"] = f"In late position with {stack_bb}BB, open-shoving {hand_str} exploits fold equity."
                advice["confidence"] = "MEDIUM"
            else:
                advice["action"] = "FOLD"
                advice["reasoning"] = f"{hand_str} is not strong enough to commit with {stack_bb}BB from {position}."
                advice["confidence"] = "MEDIUM"
        elif facing_action == "raised":
            if cat in {"premium"}:
                advice["action"] = "ALL-IN (3-bet shove)"
                advice["sizing"] = f"{stack_bb} BB"
                advice["reasoning"] = "Premium hand facing a raise—shove for maximum value."
                advice["confidence"] = "HIGH"
            elif cat in {"strong"} and stack_bb <= 13:
                advice["action"] = "ALL-IN (3-bet shove)"
                advice["sizing"] = f"{stack_bb} BB"
                advice["reasoning"] = f"Strong hand with only {stack_bb}BB, 3-bet shoving is the most +EV play vs the opener's range."
                advice["confidence"] = "MEDIUM-HIGH"
            else:
                advice["action"] = "FOLD"
                advice["reasoning"] = f"With {stack_bb}BB facing a raise, {hand_str} doesn't have enough equity to call or shove profitably from {position}."
                advice["confidence"] = "MEDIUM"
        return advice

    # ── Medium to Deep Stacks ──
    if facing_action == "unopened":
        if cat in POSITION_OPEN_RANGES.get(position, set()):
            open_size = 2.2 if position in {"BTN", "SB"} else 2.5
            if stack_bb <= 25:
                open_size = 2.0
            advice["action"] = "RAISE"
            advice["sizing"] = f"{open_size}x BB ({round(open_size * (pot_bb / 1.5), 1)} BB)"
            advice["reasoning"] = f"{hand_str} is in the GTO open-raise range from {position}. Standard sizing applies."
            advice["confidence"] = "HIGH" if cat in {"premium", "strong"} else "MEDIUM"
            if cat in {"premium"}:
                advice["alternative"] = "Consider a smaller open (2x) to keep villain's calling range wider, extracting more value long-term."
        else:
            advice["action"] = "FOLD"
            advice["reasoning"] = f"{hand_str} ({cat}) is outside the recommended open range from {position} at this stack depth."
            advice["confidence"] = "HIGH" if cat == "trash" else "MEDIUM"

    elif facing_action == "raised":
        raiser_pos = villain_position or "unknown"
        if cat == "premium":
            three_bet_size = round(raise_size_bb * 3, 1) if raise_size_bb else round(2.5 * 3, 1)
            if position == "BB":
                three_bet_size = round(raise_size_bb * 3.5, 1) if raise_size_bb else round(2.5 * 3.5, 1)
            advice["action"] = "3-BET"
            advice["sizing"] = f"{three_bet_size} BB"
            advice["reasoning"] = f"Premium hand facing a raise—3-bet for value. Against a {raiser_pos} open, this is always a 3-bet."
            advice["confidence"] = "HIGH"
        elif cat == "strong":
            if position in {"BTN", "SB", "BB"}:
                three_bet_size = round(raise_size_bb * 3, 1) if raise_size_bb else 7.5
                advice["action"] = "3-BET"
                advice["sizing"] = f"{three_bet_size} BB"
                advice["reasoning"] = f"Strong hand in position—3-bet to isolate and take initiative."
                advice["confidence"] = "MEDIUM-HIGH"
                advice["alternative"] = "Calling is also viable, especially vs tight UTG/MP opens."
            else:
                advice["action"] = "CALL"
                advice["reasoning"] = f"Strong but out of position. Flatting keeps the pot manageable and avoids bloating it OOP."
                advice["confidence"] = "MEDIUM"
        elif cat in {"good", "playable"}:
            if position in {"BTN", "BB"} and cat == "good":
                advice["action"] = "CALL"
                advice["reasoning"] = f"{hand_str} plays well postflop. Call in position to realize equity."
                advice["confidence"] = "MEDIUM"
                advice["alternative"] = f"Can mix in 3-bets with suited combos as bluffs at ~15-20% frequency."
            elif position == "BB" and cat == "playable":
                advice["action"] = "CALL (defend BB)"
                advice["reasoning"] = f"Getting a discount from the BB. {hand_str} has enough equity to defend vs a standard open."
                advice["confidence"] = "MEDIUM"
            else:
                advice["action"] = "FOLD"
                advice["reasoning"] = f"{hand_str} doesn't have enough equity to continue from {position} facing a raise."
                advice["confidence"] = "MEDIUM"
        else:
            advice["action"] = "FOLD"
            advice["reasoning"] = f"{hand_str} is too weak to continue facing a raise."
            advice["confidence"] = "HIGH" if cat == "trash" else "MEDIUM"

    elif facing_action == "3bet":
        if cat == "premium":
            if hand_str in {"AA", "KK"}:
                advice["action"] = "4-BET / ALL-IN"
                four_bet = round(raise_size_bb * 2.2, 1) if raise_size_bb else 20
                if stack_bb <= 40:
                    advice["action"] = "ALL-IN"
                    advice["sizing"] = f"{stack_bb} BB"
                else:
                    advice["sizing"] = f"~{four_bet} BB"
                advice["reasoning"] = "Top of range facing a 3-bet. 4-bet for value, stack off happily."
                advice["confidence"] = "HIGH"
            else:
                advice["action"] = "CALL"
                advice["reasoning"] = f"{hand_str} is strong enough to flat the 3-bet and play postflop."
                advice["confidence"] = "MEDIUM-HIGH"
                advice["alternative"] = "4-betting is fine at mixed frequency, especially AKs."
        elif cat == "strong" and position in {"BTN", "CO"}:
            advice["action"] = "CALL"
            advice["reasoning"] = f"{hand_str} has enough equity to see a flop in position."
            advice["confidence"] = "MEDIUM"
        else:
            advice["action"] = "FOLD"
            advice["reasoning"] = f"{hand_str} doesn't have enough equity to continue vs a 3-bet at this stack depth."
            advice["confidence"] = "MEDIUM-HIGH"

    elif facing_action == "all_in":
        # Facing an all-in
        if cat == "premium":
            advice["action"] = "CALL"
            advice["reasoning"] = "Premium hand—call the all-in. You're ahead of most shoving ranges."
            advice["confidence"] = "HIGH"
        elif cat == "strong" and stack_bb <= 20:
            advice["action"] = "CALL"
            advice["reasoning"] = f"With {stack_bb}BB and a strong hand, you're likely ahead of villain's push range from {raiser_pos if villain_position else 'their position'}."
            advice["confidence"] = "MEDIUM"
        else:
            advice["action"] = "FOLD"
            advice["reasoning"] = f"{hand_str} doesn't have enough equity to call an all-in."
            advice["confidence"] = "MEDIUM"

    return advice


def get_postflop_advice(hole_cards, board_cards, position, stack_bb, pot_bb, facing_action,
                        bet_size_bb=0, street="flop", is_aggressor=True):
    """Generate postflop GTO-approximated advice."""
    hand_eval = evaluate_hand_strength(hole_cards, board_cards)
    texture = analyze_board_texture(board_cards)
    texture_info = BOARD_TEXTURES.get(texture, BOARD_TEXTURES["semi_wet"])

    advice = {
        "hand_eval": hand_eval,
        "board_texture": texture,
        "texture_description": texture_info["description"],
        "action": "",
        "sizing": "",
        "reasoning": "",
        "confidence": "",
        "alternative": "",
    }

    strength = hand_eval["strength"]
    draws = hand_eval["draws"]
    has_draw = len(draws) > 0

    spr = stack_bb / pot_bb if pot_bb > 0 else 999

    # ── As Aggressor (IP or OOP) ──
    if is_aggressor and facing_action == "check_to_you":
        if strength == "monster":
            bet_pct = 0.75
            advice["action"] = "BET (Value)"
            advice["sizing"] = f"{round(pot_bb * bet_pct, 1)} BB ({int(bet_pct * 100)}% pot)"
            advice["reasoning"] = f"Monster hand ({hand_eval['made_hand']}) on a {texture} board. Bet large for value—you want to build the pot."
            advice["confidence"] = "HIGH"
            advice["alternative"] = "Can slow-play on very dry boards at low frequency."
        elif strength == "very_strong":
            bet_pct = 0.66
            advice["action"] = "BET (Value)"
            advice["sizing"] = f"{round(pot_bb * bet_pct, 1)} BB ({int(bet_pct * 100)}% pot)"
            advice["reasoning"] = f"Very strong hand. Bet for value and protection on a {texture} board."
            advice["confidence"] = "HIGH"
        elif strength == "strong":
            bet_pct = texture_info["cbet_size"]
            advice["action"] = "BET (Value/Protection)"
            advice["sizing"] = f"{round(pot_bb * bet_pct, 1)} BB ({int(bet_pct * 100)}% pot)"
            advice["reasoning"] = f"Strong hand on a {texture} board. C-bet for value and to deny equity."
            advice["confidence"] = "MEDIUM-HIGH"
        elif strength == "medium":
            if texture in {"dry", "paired"}:
                bet_pct = 0.33
                advice["action"] = "BET (Thin value / Protection)"
                advice["sizing"] = f"{round(pot_bb * bet_pct, 1)} BB ({int(bet_pct * 100)}% pot)"
                advice["reasoning"] = f"Medium-strength hand on a {texture} board. Small c-bet to get value from worse and fold out overcards."
                advice["confidence"] = "MEDIUM"
                advice["alternative"] = "Check-back is also fine to control pot size."
            else:
                advice["action"] = "CHECK"
                advice["sizing"] = "—"
                advice["reasoning"] = f"Medium hand on a {texture} board. Check to control pot and avoid getting blown off your hand."
                advice["confidence"] = "MEDIUM"
        elif has_draw:
            if "flush_draw" in draws and "straight_draw" in draws:
                bet_pct = 0.66
                advice["action"] = "BET (Semi-bluff)"
                advice["sizing"] = f"{round(pot_bb * bet_pct, 1)} BB ({int(bet_pct * 100)}% pot)"
                advice["reasoning"] = "Combo draw—semi-bluff aggressively. You have massive equity even if called."
                advice["confidence"] = "HIGH"
            elif "flush_draw" in draws:
                bet_pct = texture_info["cbet_size"]
                advice["action"] = "BET (Semi-bluff)"
                advice["sizing"] = f"{round(pot_bb * bet_pct, 1)} BB ({int(bet_pct * 100)}% pot)"
                advice["reasoning"] = "Flush draw—good semi-bluff candidate with ~35% equity."
                advice["confidence"] = "MEDIUM"
                advice["alternative"] = "Check-call can also work to realize equity cheaply."
            else:
                advice["action"] = "BET (Semi-bluff)" if street == "flop" else "CHECK"
                bet_pct = 0.33
                advice["sizing"] = f"{round(pot_bb * bet_pct, 1)} BB" if street == "flop" else "—"
                advice["reasoning"] = "Straight draw. Small semi-bluff on the flop; check turn if still drawing."
                advice["confidence"] = "MEDIUM"
        else:
            # Air / weak hand
            cbet_appropriate = (texture in {"dry", "paired"}) and (street == "flop")
            if cbet_appropriate and position in {"BTN", "CO", "SB"}:
                bet_pct = 0.33
                advice["action"] = "BET (C-bet bluff)"
                advice["sizing"] = f"{round(pot_bb * bet_pct, 1)} BB (33% pot)"
                advice["reasoning"] = f"Dry/paired board favors the preflop aggressor. Small c-bet as a bluff at ~{int(texture_info['cbet_freq'] * 100)}% frequency."
                advice["confidence"] = "MEDIUM"
                advice["alternative"] = "Check-fold is fine—you're bluffing here, so don't over-invest."
            else:
                advice["action"] = "CHECK"
                advice["sizing"] = "—"
                advice["reasoning"] = f"Weak hand on a {texture} board. Give up and check—the board doesn't favor a bluff here."
                advice["confidence"] = "MEDIUM-HIGH"

    # ── Facing a Bet ──
    elif facing_action == "bet" and bet_size_bb > 0:
        pot_odds = bet_size_bb / (pot_bb + bet_size_bb)
        bet_pct_of_pot = bet_size_bb / pot_bb if pot_bb > 0 else 0

        if strength in {"monster", "very_strong"}:
            if spr <= 2:
                advice["action"] = "ALL-IN (Raise)"
                advice["sizing"] = f"{stack_bb} BB"
                advice["reasoning"] = f"Very strong hand with low SPR ({round(spr, 1)}). Get it all in now."
            else:
                raise_size = round(bet_size_bb * 2.5, 1)
                advice["action"] = "RAISE"
                advice["sizing"] = f"{raise_size} BB"
                advice["reasoning"] = f"Strong hand—raise for value. You're ahead of villain's betting range."
            advice["confidence"] = "HIGH"
        elif strength == "strong":
            advice["action"] = "CALL"
            advice["sizing"] = f"{bet_size_bb} BB"
            advice["reasoning"] = f"Strong hand, but raising could fold out worse hands. Call and let villain keep barreling."
            advice["confidence"] = "MEDIUM-HIGH"
            advice["alternative"] = "Raise is viable on wet boards for protection."
        elif strength == "medium":
            if pot_odds <= 0.33:
                advice["action"] = "CALL"
                advice["sizing"] = f"{bet_size_bb} BB"
                advice["reasoning"] = f"Getting decent odds ({int(pot_odds * 100)}% needed). Your hand has showdown value—call and reassess."
                advice["confidence"] = "MEDIUM"
            elif street == "river":
                advice["action"] = "FOLD"
                advice["reasoning"] = f"Medium hand facing a river bet of {int(bet_pct_of_pot * 100)}% pot. Without strong reads, folding is disciplined."
                advice["confidence"] = "MEDIUM"
                advice["alternative"] = "Call if you have a strong read that villain bluffs at high frequency."
            else:
                advice["action"] = "CALL"
                advice["reasoning"] = "Medium hand with streets left. Call to see if the turn/river improves or clarifies."
                advice["confidence"] = "MEDIUM"
        elif has_draw:
            draw_equity = 0.35 if "flush_draw" in draws else 0.17
            if "flush_draw" in draws and "straight_draw" in draws:
                draw_equity = 0.50
            
            if draw_equity >= pot_odds:
                advice["action"] = "CALL"
                advice["sizing"] = f"{bet_size_bb} BB"
                advice["reasoning"] = f"Drawing hand with ~{int(draw_equity * 100)}% equity, needing {int(pot_odds * 100)}% to call. Math says call."
                advice["confidence"] = "MEDIUM-HIGH"
                if draw_equity > pot_odds + 0.1 and spr > 3:
                    advice["alternative"] = "Semi-bluff raise is viable with this much equity + fold equity."
            else:
                if street != "river" and spr > 3:
                    raise_size = round(bet_size_bb * 2.5, 1)
                    advice["action"] = "RAISE (Semi-bluff)"
                    advice["sizing"] = f"{raise_size} BB"
                    advice["reasoning"] = f"Drawing hand without direct odds, but fold equity makes a raise profitable."
                    advice["confidence"] = "MEDIUM"
                    advice["alternative"] = f"Fold is also acceptable—you need ~{int(pot_odds * 100)}% equity and have ~{int(draw_equity * 100)}%."
                else:
                    advice["action"] = "FOLD"
                    advice["reasoning"] = f"Drawing hand on the river—you missed. No more cards to come."
                    advice["confidence"] = "HIGH"
        else:
            advice["action"] = "FOLD"
            advice["reasoning"] = f"Weak hand facing a bet. You don't have the odds or equity to continue."
            advice["confidence"] = "HIGH"

    # ── Check-check scenario ──
    elif facing_action == "check":
        if strength in {"monster", "very_strong", "strong"}:
            bet_pct = 0.66
            advice["action"] = "BET (Delayed value)"
            advice["sizing"] = f"{round(pot_bb * bet_pct, 1)} BB ({int(bet_pct * 100)}% pot)"
            advice["reasoning"] = "Strong hand after villain checks. Bet for value—don't give free cards."
            advice["confidence"] = "HIGH"
        elif has_draw:
            advice["action"] = "BET (Semi-bluff)"
            bet_pct = 0.50
            advice["sizing"] = f"{round(pot_bb * bet_pct, 1)} BB (50% pot)"
            advice["reasoning"] = "Drawing hand with fold equity—semi-bluff when checked to."
            advice["confidence"] = "MEDIUM"
        else:
            advice["action"] = "CHECK"
            advice["sizing"] = "—"
            advice["reasoning"] = "Weak hand. Check behind to see a free card or get to showdown."
            advice["confidence"] = "MEDIUM"

    return advice


# ─── Flask Routes ────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/preflop", methods=["POST"])
def api_preflop():
    data = request.json
    card1 = data.get("card1", "").strip().upper()
    card2 = data.get("card2", "").strip().upper()
    position = data.get("position", "BTN")
    stack_bb = float(data.get("stack_bb", 30))
    facing = data.get("facing_action", "unopened")
    villain_pos = data.get("villain_position", None)
    pot_bb = float(data.get("pot_bb", 1.5))
    raise_size = float(data.get("raise_size_bb", 0))

    hand_str = normalize_hand(card1, card2)
    advice = get_preflop_advice(hand_str, position, stack_bb, facing, villain_pos, pot_bb, raise_size)
    return jsonify(advice)


@app.route("/api/postflop", methods=["POST"])
def api_postflop():
    data = request.json
    hole_cards = [c.strip().upper() for c in data.get("hole_cards", [])]
    board_cards = [c.strip().upper() for c in data.get("board_cards", [])]
    position = data.get("position", "BTN")
    stack_bb = float(data.get("stack_bb", 30))
    pot_bb = float(data.get("pot_bb", 10))
    facing = data.get("facing_action", "check_to_you")
    bet_size = float(data.get("bet_size_bb", 0))
    street = data.get("street", "flop")
    is_agg = data.get("is_aggressor", True)

    advice = get_postflop_advice(hole_cards, board_cards, position, stack_bb, pot_bb,
                                  facing, bet_size, street, is_agg)
    return jsonify(advice)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
