from __future__ import annotations

from collections import defaultdict

from trading_agent_system.schemas import (
    PremarketCatalyst,
    PremarketPricePlan,
    PremarketRecommendation,
    PremarketRecommendationSet,
    PremarketTradePlan,
)


class PremarketRecommendationEngine:
    strategy_id = "premarket_rr_v1"
    objective = "risk_reward_ratio"

    def __init__(self, strategy_version: str = "2026-06-14.1") -> None:
        self.strategy_version = strategy_version

    def build(
        self,
        watchlist: list[PremarketTradePlan],
        catalysts: list[PremarketCatalyst],
    ) -> PremarketRecommendationSet:
        by_symbol = self._catalysts_by_symbol(catalysts)
        conservative: list[PremarketRecommendation] = []
        opportunity: list[PremarketRecommendation] = []
        watch: list[PremarketRecommendation] = []
        for plan in watchlist:
            price_plan = self._price_plan(plan)
            if price_plan is None:
                continue
            related = by_symbol.get(plan.symbol, [])
            score_breakdown = self._score_breakdown(plan, related)
            trade_score = self._trade_score(score_breakdown)
            expected_r = self._expected_r(plan, score_breakdown, price_plan)
            price_plan.expected_r = expected_r
            mode = self._mode(trade_score, expected_r, price_plan, score_breakdown, related)
            if mode is None:
                continue
            recommendation = self._recommendation(plan, price_plan, score_breakdown, trade_score, mode, related)
            if mode == "conservative":
                conservative.append(recommendation)
            elif mode == "opportunity":
                opportunity.append(recommendation)
            else:
                watch.append(recommendation)
        return PremarketRecommendationSet(
            strategy_id=self.strategy_id,
            strategy_version=self.strategy_version,
            objective=self.objective,
            conservative=self._rank(conservative),
            opportunity=self._rank(opportunity),
            watch=self._rank(watch),
        )

    def _catalysts_by_symbol(self, catalysts: list[PremarketCatalyst]) -> dict[str, list[PremarketCatalyst]]:
        by_symbol: dict[str, list[PremarketCatalyst]] = defaultdict(list)
        for catalyst in catalysts:
            for symbol in catalyst.symbols:
                by_symbol[symbol].append(catalyst)
        return by_symbol

    def _price_plan(self, plan: PremarketTradePlan) -> PremarketPricePlan | None:
        if plan.reference_price is None or plan.entry_low is None or plan.entry_high is None or plan.stop_loss is None:
            return None
        entry_mid = (plan.entry_low + plan.entry_high) / 2
        risk = entry_mid - plan.stop_loss
        if risk <= 0:
            return None
        target_price_1 = entry_mid + risk * 2.0
        target_price_2 = entry_mid + risk * 2.8
        return PremarketPricePlan(
            reference_price=round(plan.reference_price, 2),
            entry_low=round(plan.entry_low, 2),
            entry_high=round(plan.entry_high, 2),
            stop_loss=round(plan.stop_loss, 2),
            target_price_1=round(target_price_1, 2),
            target_price_2=round(target_price_2, 2),
            risk_reward_1=round((target_price_1 - entry_mid) / risk, 2),
            risk_reward_2=round((target_price_2 - entry_mid) / risk, 2),
            expected_r=0.0,
        )

    def _score_breakdown(
        self,
        plan: PremarketTradePlan,
        catalysts: list[PremarketCatalyst],
    ) -> dict[str, float]:
        source_count = len({source for catalyst in catalysts for source in catalyst.sources})
        has_quote_candidate = any(catalyst.category == "quote_candidate" for catalyst in catalysts)
        negative_count = sum(1 for catalyst in catalysts if catalyst.bias == "bearish")
        risk_score = min(25.0, len(plan.risk_flags) * 12.0 + negative_count * 10.0)
        return {
            "catalyst_strength": round(min(25.0, 8.0 + len(catalysts) * 5.0 + (6.0 if has_quote_candidate else 0.0)), 2),
            "source_confirmation": round(min(15.0, source_count * 7.5), 2),
            "theme_heat": 15.0 if plan.theme else 0.0,
            "market_strength": round(plan.confidence * 20.0, 2),
            "liquidity": 8.0,
            "risk_score": round(risk_score, 2),
        }

    def _trade_score(self, score_breakdown: dict[str, float]) -> float:
        positive = (
            score_breakdown["catalyst_strength"]
            + score_breakdown["source_confirmation"]
            + score_breakdown["theme_heat"]
            + score_breakdown["market_strength"]
            + score_breakdown["liquidity"]
        )
        return round(max(0.0, min(100.0, positive - score_breakdown["risk_score"])), 2)

    def _expected_r(
        self,
        plan: PremarketTradePlan,
        score_breakdown: dict[str, float],
        price_plan: PremarketPricePlan,
    ) -> float:
        trade_score = self._trade_score(score_breakdown)
        win_probability = 0.28 + trade_score / 180.0 + plan.confidence * 0.08 - score_breakdown["risk_score"] / 200.0
        win_probability = max(0.25, min(0.72, win_probability))
        average_target_r = (price_plan.risk_reward_1 + price_plan.risk_reward_2) / 2
        expected_r = win_probability * average_target_r - (1 - win_probability) - 0.05 - score_breakdown["risk_score"] / 200.0
        return round(expected_r, 2)

    def _mode(
        self,
        trade_score: float,
        expected_r: float,
        price_plan: PremarketPricePlan,
        score_breakdown: dict[str, float],
        catalysts: list[PremarketCatalyst],
    ) -> str | None:
        source_count = len({source for catalyst in catalysts for source in catalyst.sources})
        risk_score = score_breakdown["risk_score"]
        if (
            trade_score >= 80
            and expected_r >= 0.35
            and price_plan.risk_reward_1 >= 1.8
            and risk_score <= 30
            and source_count >= 2
        ):
            return "conservative"
        if trade_score >= 60 and expected_r >= 0.20 and price_plan.risk_reward_1 >= 2.0 and risk_score <= 50:
            return "opportunity"
        if trade_score >= 45 and price_plan.risk_reward_1 >= 1.5:
            return "watch"
        return None

    def _recommendation(
        self,
        plan: PremarketTradePlan,
        price_plan: PremarketPricePlan,
        score_breakdown: dict[str, float],
        trade_score: float,
        mode: str,
        catalysts: list[PremarketCatalyst],
    ) -> PremarketRecommendation:
        return PremarketRecommendation(
            symbol=plan.symbol,
            name=plan.name,
            theme=plan.theme,
            mode=mode,
            rank=0,
            rating=self._rating(mode, trade_score),
            trade_score=trade_score,
            confidence=plan.confidence,
            reason=plan.reason,
            triggers=plan.triggers,
            invalidation=self._invalidation(mode),
            risk_flags=plan.risk_flags,
            price_plan=price_plan,
            decision_trace={
                "score_breakdown": score_breakdown,
                "evidence": [
                    {
                        "title": catalyst.title,
                        "source": catalyst.sources[0] if catalyst.sources else "",
                        "category": catalyst.category,
                    }
                    for catalyst in catalysts
                ],
                "reject_reasons": self._reject_reasons(mode, score_breakdown, catalysts),
            },
        )

    def _rating(self, mode: str, trade_score: float) -> str:
        if mode == "conservative":
            return "A" if trade_score >= 80 else "A-"
        if mode == "opportunity":
            return "B+"
        return "观察"

    def _invalidation(self, mode: str) -> list[str]:
        common = ["竞价承接弱于板块", "开盘后跌破竞价均价"]
        if mode == "conservative":
            return [*common, "出现负面公告或监管风险"]
        if mode == "opportunity":
            return [*common, "板块龙头低于预期"]
        return [*common, "风险收益比未继续改善"]

    def _reject_reasons(
        self,
        mode: str,
        score_breakdown: dict[str, float],
        catalysts: list[PremarketCatalyst],
    ) -> list[str]:
        reasons: list[str] = []
        source_count = len({source for catalyst in catalysts for source in catalyst.sources})
        if mode != "conservative" and source_count < 2:
            reasons.append("未进入稳健型：信息源确认不足 2 个")
        if mode == "watch":
            reasons.append("未进入机会型：综合分或风险收益比未达机会型阈值")
        if score_breakdown["risk_score"] > 0:
            reasons.append(f"风险扣分 {score_breakdown['risk_score']}")
        return reasons

    def _rank(self, items: list[PremarketRecommendation]) -> list[PremarketRecommendation]:
        ranked = sorted(items, key=lambda item: (item.trade_score, item.price_plan.expected_r), reverse=True)
        return [item.model_copy(update={"rank": index + 1}) for index, item in enumerate(ranked)]
