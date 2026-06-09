from __future__ import annotations

from dataclasses import dataclass, field


DEFAULT_THEME_SYMBOLS: dict[str, list[str]] = {
    "半导体": ["688981.SH", "002371.SZ", "688256.SH", "601138.SH"],
    "机器人": ["300750.SZ", "002031.SZ", "002050.SZ", "688017.SH"],
    "算力": ["601138.SH", "000977.SZ", "300308.SZ", "688256.SH"],
    "新能源": ["300750.SZ", "002594.SZ", "601012.SH", "300274.SZ"],
    "券商": ["300059.SZ", "600030.SH", "601688.SH", "000776.SZ"],
    "消费": ["600519.SH", "000858.SZ", "600887.SH", "601888.SH"],
}

DEFAULT_ALIASES: dict[str, str] = {
    "芯片": "半导体",
    "光刻机": "半导体",
    "晶圆": "半导体",
    "人形机器人": "机器人",
    "减速器": "机器人",
    "AI服务器": "算力",
    "液冷": "算力",
    "锂电": "新能源",
    "储能": "新能源",
    "证券": "券商",
    "白酒": "消费",
}


@dataclass(frozen=True)
class ThemeRegistry:
    theme_symbols: dict[str, list[str]] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)

    @classmethod
    def default(cls) -> "ThemeRegistry":
        return cls(theme_symbols=DEFAULT_THEME_SYMBOLS, aliases=DEFAULT_ALIASES)

    def resolve_theme(self, value: str) -> str | None:
        if value in self.theme_symbols:
            return value
        return self.aliases.get(value)

    def symbols_for_theme(self, theme: str) -> list[str]:
        canonical = self.resolve_theme(theme)
        if canonical is None:
            return []
        return list(self.theme_symbols.get(canonical, []))

    def themes_for_symbol(self, symbol: str) -> list[str]:
        return [theme for theme, symbols in self.theme_symbols.items() if symbol in symbols]

    def primary_theme_for_symbol(self, symbol: str, preferred_themes: list[str] | None = None) -> str | None:
        symbol_themes = self.themes_for_symbol(symbol)
        if not symbol_themes:
            return None
        for theme in preferred_themes or []:
            canonical = self.resolve_theme(theme)
            if canonical in symbol_themes:
                return canonical
        return symbol_themes[0]
