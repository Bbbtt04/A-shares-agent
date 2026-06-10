from __future__ import annotations

from datetime import date

from trading_agent_system.agents.premarket_agent.rag.schemas import RetrievalFilter, RetrievalTask


class PreMarketRAGQueryPlanner:
    def build_tasks(self, trading_day: date, premarket_window_id: str) -> list[RetrievalTask]:
        base_filter = RetrievalFilter(trading_day=trading_day, premarket_window_id=premarket_window_id)
        return [
            RetrievalTask(
                section="core_conclusion",
                query="今日盘前核心结论 S/A 级政策 公告 风险",
                filters=base_filter.model_copy(update={"importance": ["S", "A"]}),
                retrievers=["structured", "risk_event", "recency", "keyword"],
                final_top_k=8,
                max_tokens=1800,
            ),
            RetrievalTask(
                section="post_close_events",
                query="上一交易日收盘后重要消息 公告 政策 新闻",
                filters=base_filter.model_copy(update={"importance": ["S", "A", "B"]}),
                retrievers=["structured", "keyword", "vector", "recency"],
                final_top_k=12,
                max_tokens=2600,
            ),
            RetrievalTask(
                section="portfolio_risks",
                query="持仓相关监管 处罚 停牌 退市 减持 债务 亏损风险",
                filters=base_filter.model_copy(
                    update={
                        "risk_flags_include": [
                            "regulatory_penalty",
                            "regulatory_inquiry",
                            "delisting_risk",
                            "suspension",
                            "shareholder_reduction",
                            "debt_risk",
                            "litigation",
                            "performance_loss",
                        ]
                    }
                ),
                retrievers=["portfolio", "risk_event", "keyword"],
                final_top_k=10,
                max_tokens=2200,
            ),
            RetrievalTask(
                section="theme_candidates",
                query="今日主题候选 官方催化 海外映射 昨日强势题材延续",
                filters=base_filter,
                retrievers=["theme", "vector", "keyword", "recency"],
                final_top_k=12,
                max_tokens=2200,
            ),
            RetrievalTask(
                section="macro_calendar",
                query="今日宏观日历 重要会议 海外市场 经济数据",
                filters=base_filter,
                retrievers=["structured", "keyword", "recency"],
                final_top_k=6,
                max_tokens=1200,
            ),
            RetrievalTask(
                section="avoid_list",
                query="盘前回避清单 高风险 禁入 降权 人工确认",
                filters=base_filter.model_copy(update={"risk_flags_include": ["unverified", "rumor", "regulatory_inquiry"]}),
                retrievers=["risk_event", "structured"],
                final_top_k=8,
                max_tokens=1600,
            ),
        ]
