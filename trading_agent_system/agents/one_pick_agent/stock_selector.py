from __future__ import annotations

from .schemas import EffectiveOnePickStrategy, OnePickCandidate, OnePickSelection


class StockSelector:
    def select(self, candidates: list[OnePickCandidate], strategy: EffectiveOnePickStrategy) -> OnePickSelection:
        if not candidates:
            raise ValueError("at least one candidate is required")

        ranked = sorted(
            candidates[: strategy.selection.max_candidates],
            key=lambda candidate: (-self._score(candidate, strategy), candidate.source_rank, candidate.symbol),
        )
        eligible = [
            candidate for candidate in ranked if not set(candidate.risk_flags).intersection(strategy.blocked_risk_flags)
        ]
        selected = eligible[0] if eligible else ranked[0]
        score = self._score(selected, strategy)
        threshold_reasons: list[str] = []
        if selected.confidence < strategy.selection.min_confidence_to_buy:
            threshold_reasons.append("confidence_below_minimum")
        if selected.risk_reward_ratio < strategy.selection.min_risk_reward_ratio:
            threshold_reasons.append("risk_reward_below_minimum")
        if set(selected.risk_flags).intersection(strategy.blocked_risk_flags):
            threshold_reasons.append("blocked_risk_flag")

        reasons = [f"ranked_score={score:.4f}"]
        if selected.strategy_tags:
            reasons.append(f"strategy_tags={','.join(selected.strategy_tags)}")
        if selected.risk_flags:
            reasons.append(f"risk_flags={','.join(selected.risk_flags)}")

        return OnePickSelection(
            selected_symbol=selected.symbol,
            selected_name=selected.name,
            score=round(score, 6),
            confidence=selected.confidence,
            risk_reward_ratio=selected.risk_reward_ratio,
            threshold_passed=not threshold_reasons,
            threshold_reasons=threshold_reasons,
            reasons=reasons,
            evidence_ids=selected.evidence_ids,
            risk_flags=selected.risk_flags,
            feature_scores=selected.feature_scores,
            strategy_tags=selected.strategy_tags,
        )

    def _score(self, candidate: OnePickCandidate, strategy: EffectiveOnePickStrategy) -> float:
        score = 0.0
        for feature, weight in strategy.scoring_weights.items():
            score += float(weight) * float(candidate.feature_scores.get(feature, 0.0))
        for tag in candidate.strategy_tags:
            score += strategy.tag_adjustments.get(tag, 0.0)
        for risk_flag in candidate.risk_flags:
            score -= strategy.risk_penalties.get(risk_flag, 0.0)
        score += 0.10 * candidate.confidence
        score += 0.05 * min(candidate.risk_reward_ratio, 4.0)
        return score
