"""Workflow execution and outcome recording for evidence-based research."""

from __future__ import annotations

from typing import Any, Sequence

from archx_agent.helpers.exceptions import (
    ValidationError,
)
from archx_agent.managers.research import MODES
from archx_agent.application.researcher.records import ResearchBlocked, SourceDoc
from archx_agent.application.researcher.text import _settings_of
from archx_agent.application.researcher.formatting import _to_html
from archx_agent.application.researcher.planning import ResearchRunnerPlanningMixin
from archx_agent.application.researcher.sources import ResearchRunnerSourcesMixin
from archx_agent.application.researcher.judgement import ResearchRunnerJudgementMixin
from archx_agent.application.researcher.reporting import ResearchRunnerReportingMixin


class ResearchRunner(
    ResearchRunnerPlanningMixin,
    ResearchRunnerSourcesMixin,
    ResearchRunnerJudgementMixin,
    ResearchRunnerReportingMixin,
):
    """Runs a research question end to end, persisting every step as it goes."""

    def __init__(self, ws) -> None:
        self.ws = ws
        self.manager = ws.research

    def _cfg(self, key: str, default: Any) -> Any:
        try:
            return self.ws.config.get(key)
        except Exception:  # noqa: BLE001 - a missing key must not break a run
            return default

    def run(
        self,
        question: str,
        *,
        mode: str | None = None,
        urls: Sequence[str] = (),
        max_subquestions: int | None = None,
        subquestions: Sequence[str] | None = None,
        model_id: str | None = None,
        out: str | None = None,
        report_format: str | None = None,
        use_model: bool = True,
        allow_private_hosts: bool | None = None,
        task_id: str | None = None,
        project_id: str | None = None,
    ) -> dict[str, Any]:
        question = (question or "").strip()
        if len(question) < 4:
            raise ValidationError("a research question needs at least four characters")
        mode = mode or str(self._cfg("research.default_mode", "local"))
        if mode not in MODES:
            raise ValidationError(f"mode must be one of {', '.join(MODES)}")
        urls = [str(url).strip() for url in urls if str(url).strip()]
        if mode in {"web", "mixed"} and not urls:
            raise ValidationError(
                f"mode {mode!r} needs at least one --url: Archx does not crawl and does not "
                "query a search engine, so the seeds must come from you"
            )
        if mode == "local" and urls:
            raise ValidationError(
                "--url needs --mode web or --mode mixed (otherwise it is ignored)"
            )
        report_format = report_format or str(
            self._cfg("research.report_format", "markdown")
        )
        if report_format not in {"markdown", "md", "html"}:
            raise ValidationError("report format must be markdown or html")

        own_task = task_id is None
        if own_task:
            task = self.ws.tasks.create("research", question[:120], start=True)
            task_id = task.id
        run = self.manager.create(
            question,
            mode=mode,
            report_format="html" if report_format == "html" else "markdown",
            model_id=model_id,
            task_id=task_id,
            settings={
                "urls": urls,
                "max_subquestions": max_subquestions,
                "use_model": use_model,
                "out": out,
            },
        )
        try:
            return self._execute(
                run.id,
                question,
                mode=mode,
                urls=urls,
                max_subquestions=max_subquestions,
                subquestions=subquestions,
                model_id=model_id,
                out=out,
                report_format=report_format,
                use_model=use_model,
                allow_private_hosts=allow_private_hosts,
                task_id=task_id,
                project_id=project_id,
            )
        except ResearchBlocked as blocked:
            self._finish_blocked(run.id, blocked, task_id=task_id)
            raise
        except Exception as exc:  # noqa: BLE001 - a failed run is a record, not a crash
            message = getattr(exc, "message", None) or str(exc)
            try:
                self.manager.finish(
                    run.id,
                    status="failed",
                    error=message,
                    limitations=[f"the run failed: {message}"],
                )
            except Exception:  # noqa: BLE001
                pass
            if task_id:
                self._log(task_id, "research_failed", message)
                try:
                    self.ws.tasks.fail(task_id, message)
                except Exception:  # noqa: BLE001
                    pass
            raise

    def _execute(
        self,
        run_id: str,
        question: str,
        *,
        mode: str,
        urls: Sequence[str],
        max_subquestions: int | None,
        subquestions: Sequence[str] | None,
        model_id: str | None,
        out: str | None,
        report_format: str,
        use_model: bool,
        allow_private_hosts: bool | None,
        task_id: str | None,
        project_id: str | None,
    ) -> dict[str, Any]:
        conversation_id = None
        if use_model:
            conversation = self.ws.conversations.create(
                title=f"research: {question[:80]}"
            )
            conversation_id = conversation.id
            self.manager.update(
                run_id,
                settings={
                    **_settings_of(self.manager, run_id),
                    "conversation_id": conversation_id,
                },
            )

        plan, planned_by, plan_notes, plan_meta = self.plan(
            question,
            max_subquestions=max_subquestions,
            conversation_id=conversation_id,
            model_id=model_id,
            subquestions=subquestions,
        )
        self.manager.update(
            run_id, plan=plan, planned_by=planned_by, status="gathering"
        )
        self._log(
            task_id,
            "research_planned",
            f"{len(plan)} subquestion(s), planned by {planned_by}",
        )

        docs: list[SourceDoc] = []
        if mode in {"local", "mixed"}:
            docs.extend(
                self.gather_local(
                    question,
                    plan,
                    exclude_task_id=task_id,
                    exclude_conversation_id=conversation_id,
                )
            )
        if mode in {"web", "mixed"}:
            docs.extend(
                self.gather_web(
                    urls,
                    question,
                    plan,
                    task_id=task_id,
                    run_id=run_id,
                    allow_private_hosts=allow_private_hosts,
                )
            )
        self.manager.update(run_id, status="reading")
        self._log(task_id, "research_gathered", f"{len(docs)} candidate source(s)")

        judge_notes = self.judge(
            docs,
            question,
            plan,
            conversation_id=conversation_id,
            model_id=model_id,
            use_model=use_model,
        )

        # Persist every source: successes in reading order (which fixes [S<n>]), failures too.
        for doc in docs:
            stored = self.manager.add_source(
                run_id,
                url=doc.url or doc.ref,
                kind=doc.kind,
                title=doc.title,
                publisher=doc.publisher,
                excerpt=doc.excerpt or None,
                ref=doc.ref,
                status=doc.status,
                error=doc.error,
                checksum=doc.checksum,
                bytes_=doc.bytes,
                relevance=round(doc.relevance, 4),
                credibility=doc.credibility,
                stance=doc.stance,
                claims=doc.claims,
                subquestion=doc.subquestion,
                limitations=None,
            )
            doc.number = stored.id
        usable = [doc for doc in docs if doc.usable]
        for position, doc in enumerate(
            sorted(usable, key=lambda item: item.number), start=1
        ):
            # [S<n>] is the citation label *within this run*; the row id stays in the table.
            doc.number = position

        self.manager.update(run_id, status="synthesizing")
        report, coverage, limitations, meta = self.synthesize(
            question,
            plan,
            docs,
            mode=mode,
            run_id=run_id,
            planned_by=planned_by,
            model_id=model_id,
            notes=[*plan_notes, *judge_notes],
            conversation_id=conversation_id,
            use_model=use_model,
        )
        numbers = [doc.number for doc in usable]
        verification = self.verify(report, numbers)
        if verification["unknown_citations"]:
            limitations.append(
                "the report cited sources that do not exist: "
                + ", ".join(
                    f"S{number}" for number in verification["unknown_citations"]
                )
            )
            report = report.replace(
                "## Sources",
                "_Citation check failed for: "
                + ", ".join(
                    f"S{number}" for number in verification["unknown_citations"]
                )
                + "_\n\n## Sources",
            )

        path = self._write_report(run_id, report, report_format=report_format, out=out)
        status = "completed" if usable else "incomplete"
        finished = self.manager.finish(
            run_id,
            status=status,
            report=report,
            report_path=path,
            coverage=coverage,
            evidence_count=len(usable),
            limitations=limitations,
        )
        if task_id:
            try:
                self.ws.tasks.attach_artifact(
                    task_id, path, kind="report", name=f"research-{run_id}"
                )
            except Exception as exc:  # noqa: BLE001 - the report still exists on disk
                self._log(task_id, "research_artifact_failed", str(exc))
            self._log(
                task_id,
                "research_reported",
                f"{len(usable)} source(s), coverage {coverage:.0%}, report {path}",
            )
            try:
                self.ws.tasks.complete(
                    task_id,
                    summary=(
                        f"research {run_id}: {len(usable)} source(s), coverage {coverage:.0%}"
                    ),
                    outputs=[path],
                )
            except Exception:  # noqa: BLE001 - completed is best-effort here
                pass
        return {
            "run": finished.to_dict(),
            "report_path": path,
            "verification": verification,
            "plan_meta": plan_meta,
            "model_reading": meta,
            "report": report,
        }

    def _finish_blocked(
        self, run_id: str, blocked: ResearchBlocked, *, task_id: str | None
    ) -> None:
        try:
            self.manager.finish(
                run_id,
                status="failed",
                error=blocked.message,
                limitations=[blocked.message],
            )
        except Exception:  # noqa: BLE001
            pass
        if task_id:
            self._log(task_id, "research_blocked", blocked.message)
            try:
                self.ws.tasks.fail(task_id, blocked.message)
            except Exception:  # noqa: BLE001
                pass

    def _write_report(
        self, run_id: str, report: str, *, report_format: str, out: str | None
    ) -> str:
        from pathlib import Path

        if out:
            target = Path(out).expanduser()
            if target.suffix == "":
                target = target.with_suffix(
                    ".html" if report_format == "html" else ".md"
                )
        else:
            base = Path(self.ws.config.path("paths.research"))
            base.mkdir(parents=True, exist_ok=True)
            target = base / f"{run_id}.{'html' if report_format == 'html' else 'md'}"
        target.parent.mkdir(parents=True, exist_ok=True)
        body = _to_html(report) if report_format == "html" else report
        target.write_text(body, encoding="utf-8")
        return str(target)

    def _log(self, task_id: str | None, kind: str, detail: str) -> None:
        if not task_id:
            return
        try:
            self.ws.tasks.log(task_id, kind, detail=detail[:2000])
        except Exception:  # noqa: BLE001 - logging must never break a run
            pass
