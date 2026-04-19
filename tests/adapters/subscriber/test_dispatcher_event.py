import httpx
from a2sdlc.adapters.subscriber.dispatcher_event import DispatcherEventSubscriber
from a2sdlc.domain.progress import Metrics, StageEnd, StageStart
from a2sdlc.domain.models import StageName


class FakeHttp:
    def __init__(self):
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})

        class R:
            status_code = 202

            def raise_for_status(self_):
                pass

        return R()


async def test_stage_start_posts_stage_started():
    http = FakeHttp()
    sub = DispatcherEventSubscriber(
        dispatcher_url="https://d.example",
        run_id="r1",
        run_hmac="tok",
        http=http,
    )
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="s1", started_at=0.0))
    # Exactly one POST — stage_started. No run_started emitted by the engine;
    # the dispatcher itself flips "Ready → In Progress" on the first stage_started it sees.
    assert len(http.calls) == 1
    body = http.calls[0]["json"]
    assert body["kind"] == "stage_started"
    assert body["stage"] == "spec"
    assert http.calls[0]["headers"]["Authorization"] == "Bearer tok"
    assert http.calls[0]["url"] == "https://d.example/runs/r1/events"


async def test_stage_start_never_emits_run_started():
    http = FakeHttp()
    sub = DispatcherEventSubscriber(
        dispatcher_url="https://d.example",
        run_id="r1",
        run_hmac="tok",
        http=http,
    )
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="s1", started_at=0.0))
    await sub.handle(
        StageStart(stage=StageName.IMPLEMENT, session_id="s1", started_at=1.0)
    )
    kinds = [c["json"]["kind"] for c in http.calls]
    assert "run_started" not in kinds
    assert kinds == ["stage_started", "stage_started"]


async def test_stage_end_failure_posts_stage_completed_failed():
    http = FakeHttp()
    sub = DispatcherEventSubscriber(
        dispatcher_url="https://d.example",
        run_id="r1",
        run_hmac="tok",
        http=http,
    )
    await sub.handle(
        StageEnd(
            stage=StageName.IMPLEMENT,
            success=False,
            error="boom",
            final_metrics=Metrics(0, 0, 0.0, 0, 0.0),
        )
    )
    body = http.calls[0]["json"]
    assert body["kind"] == "stage_completed"
    assert body["ok"] is False
    assert body["summary"] == "boom"


async def test_http_failure_is_swallowed():
    class BadHttp:
        def post(self, *a, **kw):
            raise httpx.ConnectError("no route")

    sub = DispatcherEventSubscriber(
        dispatcher_url="https://d.example",
        run_id="r1",
        run_hmac="tok",
        http=BadHttp(),
    )
    # Must not raise — dispatcher outage cannot break the pipeline.
    await sub.handle(StageStart(stage=StageName.SPEC, session_id="s1", started_at=0.0))


async def test_chatty_events_are_not_forwarded():
    from a2sdlc.domain.progress import GroupOpen, Milestone, ToolEntry

    http = FakeHttp()
    sub = DispatcherEventSubscriber(
        dispatcher_url="https://d.example",
        run_id="r1",
        run_hmac="tok",
        http=http,
    )
    # Metrics, Milestone, ToolEntry, and anything non-Stage are dropped —
    # MLflow captures per-token telemetry; only lifecycle events hit Jira.
    await sub.handle(Metrics(0, 0, 0.0, 0, 0.0))
    await sub.handle(Milestone(timestamp=0.0, label="x"))
    await sub.handle(ToolEntry(timestamp=0.0, name="Read", target="file"))
    await sub.handle(GroupOpen(title="noise"))
    assert http.calls == []
