import json
from datetime import datetime, timedelta

import requests


BASE = "http://127.0.0.1:8000"


def fake_data():
    video_id = "7499999999999990001"
    videos = [
        {
            "video_id": video_id,
            "title": "AI剪辑工作流到底值不值得学？",
            "desc": "分享一套我常用的短视频AI提效方案",
            "author_name": "AI运营实验室",
            "author_id": "author_001",
            "duration": 58,
            "digg_count": 38120,
            "comment_count": 240,
            "collect_count": 1280,
            "share_count": 530,
            "create_time": datetime.now().isoformat(),
            "music_name": "trend_bgm",
            "video_url": "https://www.douyin.com/video/7499999999999990001"
        }
    ]

    base_time = datetime.now() - timedelta(days=2)
    comments_text = [
        "这个流程太实用了，马上收藏。",
        "感觉你这套方法有点广告味道。",
        "我试了下，效率确实提升了。",
        "说实话不太适合新手，步骤太多了。",
        "标题可以再直接一点，会更吸引人。",
        "内容很好，但开头节奏有点慢。",
        "这是不是虚假宣传啊，效果没那么夸张吧。",
        "支持，多发这类实操内容。",
        "评论区有人说被骗，建议你回应一下。",
        "希望下次讲讲具体工具参数。",
    ]

    comments = []
    for i in range(120):
        txt = comments_text[i % len(comments_text)]
        comments.append(
            {
                "comment_id": f"c_{i+1:04d}",
                "video_id": video_id,
                "user_name": f"user_{i%27}",
                "content": txt,
                "digg_count": (i * 3) % 200,
                "reply_count": i % 8,
                "create_time": (base_time + timedelta(hours=i % 36)).isoformat(),
                "ip_label": "上海" if i % 2 == 0 else "北京",
            }
        )

    return {"videos": videos, "comments": comments}


if __name__ == "__main__":
    payload = fake_data()
    r = requests.post(f"{BASE}/api/ingest", json=payload, timeout=30)
    print(r.status_code, r.text)

    r = requests.post(f"{BASE}/api/analyze", json={"video_id": payload["videos"][0]["video_id"]}, timeout=120)
    print(r.status_code)
    print(json.dumps(r.json(), ensure_ascii=False, indent=2))
