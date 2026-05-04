from __future__ import annotations
from pathlib import Path
from typing import Literal
import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    reddit_client_id: str
    reddit_client_secret: str
    reddit_username: str | None = None
    reddit_password: str | None = None
    reddit_user_agent: str

    database_url: str = "postgresql://reddit:reddit@localhost:5432/reddit"
    raw_payload_uri_base: str | None = None
    log_level: str = "INFO"

    @property
    def use_password_grant(self) -> bool:
        return bool(self.reddit_username and self.reddit_password)


class Source(BaseModel):
    kind: Literal["subreddit", "search", "user"]
    name: str | None = None              # for subreddit / user
    query: str | None = None             # for search
    listing: Literal["new", "hot", "top", "rising"] = "new"
    sort: str = "new"
    timeframe: str = "day"
    poll_interval_sec: int = 300
    fetch_comments: bool = True
    comment_depth: int = 5
    max_items_per_tick: int = 1000

    @property
    def key(self) -> str:
        if self.kind == "subreddit":
            return f"subreddit:{self.name}:{self.listing}"
        if self.kind == "search":
            return f"search:{self.query}:{self.sort}:{self.timeframe}"
        return f"user:{self.name}"


class HNSource(BaseModel):
    query: str = ""
    tags: str = "story"
    pages: int = 3


class SourcesFile(BaseModel):
    sources: list[Source] = Field(default_factory=list)
    hn_sources: list[HNSource] = Field(default_factory=list)


def load_sources_file(path: str | Path) -> SourcesFile:
    text = Path(path).read_text()
    return SourcesFile(**yaml.safe_load(text))


def load_sources(path: str | Path) -> list[Source]:
    return load_sources_file(path).sources


def load_hn_sources(path: str | Path) -> list[HNSource]:
    return load_sources_file(path).hn_sources
