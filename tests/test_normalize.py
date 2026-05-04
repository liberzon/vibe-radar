from reddit_collector.normalize import normalize_post, flatten_comment_tree


def test_normalize_post_minimum():
    api = {
        "name": "t3_abc123", "id": "abc123",
        "subreddit": "Programming",
        "title": "hi", "selftext": "body",
        "url": "https://x.test/", "permalink": "/r/Programming/comments/abc123/hi/",
        "score": 5, "upvote_ratio": 0.95, "num_comments": 2,
        "created_utc": 1700000000, "edited": False,
        "author": "alice", "author_fullname": "t2_alice",
    }
    row = normalize_post(api)
    assert row["id"] == "t3_abc123"
    assert row["subreddit"] == "programming"
    assert row["author_id"] == "t2_alice"
    assert row["deleted_at"] is None
    assert row["content_hash"]


def test_normalize_post_deleted():
    api = {
        "name": "t3_x", "id": "x", "subreddit": "x", "title": "t",
        "selftext": "[deleted]", "author": "[deleted]",
        "created_utc": 1700000000, "edited": False,
    }
    row = normalize_post(api)
    assert row["deleted_at"] is not None
    assert row["removed"] is True


def test_flatten_comment_tree():
    api = [
        {"data": {"children": []}},  # post listing — ignored
        {"data": {"children": [
            {"kind": "t1", "data": {
                "name": "t1_a", "id": "a", "link_id": "t3_p", "parent_id": "t3_p",
                "subreddit": "x", "body": "hi", "score": 1, "depth": 0,
                "author": "u1", "author_fullname": "t2_u1", "created_utc": 1700000000,
                "edited": False,
                "replies": {"data": {"children": [
                    {"kind": "t1", "data": {
                        "name": "t1_b", "id": "b", "link_id": "t3_p", "parent_id": "t1_a",
                        "subreddit": "x", "body": "yo", "score": 2, "depth": 1,
                        "author": "u2", "author_fullname": "t2_u2", "created_utc": 1700000001,
                        "edited": False, "replies": "",
                    }},
                ]}},
            }},
            {"kind": "more", "data": {"children": ["c1", "c2"]}},  # ignored
        ]}},
    ]
    rows = flatten_comment_tree(api)
    assert [r["id"] for r in rows] == ["t1_a", "t1_b"]
    assert rows[1]["depth"] == 1
    assert rows[1]["parent_id"] == "t1_a"
