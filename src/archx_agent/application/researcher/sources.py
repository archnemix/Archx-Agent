"""Sources operations for evidence-based research."""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from archx_agent.helpers.exceptions import (
    ApprovalRequiredError,
    ArchxError,
    NotFoundError,
)
from archx_agent.managers.tools import ToolContext
from archx_agent.application.researcher.constants import EVIDENCE_KINDS
from archx_agent.application.researcher.records import ResearchBlocked, SourceDoc
from archx_agent.application.researcher.text import (
    _host,
    _sha256,
    _query_for,
    _assign_subquestion,
    _best_subquestion,
)


class ResearchRunnerSourcesMixin:
    """Sources responsibility for ResearchRunner."""

    def gather_local(
        self,
        question: str,
        plan: Sequence[Mapping[str, Any]],
        *,
        per_source: int | None = None,
        max_sources: int | None = None,
        exclude_task_id: str | None = None,
        exclude_conversation_id: str | None = None,
    ) -> list[SourceDoc]:
        budget = int(max_sources or self._cfg("research.max_sources", 24))
        per_source = int(per_source or self._cfg("research.per_source_hits", 5))
        merge_limit = int(self._cfg("research.gather_limit", 12))
        docs: list[SourceDoc] = []
        by_ref: dict[str, SourceDoc] = {}
        for index, item in enumerate(plan):
            query = _query_for(question, str(item.get("question") or ""))
            report = self.ws.search.search(
                query,
                kinds=list(EVIDENCE_KINDS),
                limit=max(per_source, merge_limit),
                per_source=per_source,
            )
            for hit in report.hits:
                # A run is not its own evidence: the task it created and the conversation its
                # planning used are bookkeeping, not sources.
                if exclude_task_id and hit.kind == "task" and hit.id == exclude_task_id:
                    continue
                if (
                    exclude_conversation_id
                    and hit.kind == "conversation"
                    and hit.id == exclude_conversation_id
                ):
                    continue
                doc = self._load_hit(hit, index)
                if doc is None:
                    continue
                existing = by_ref.get(doc.ref)
                if existing is not None:
                    if index not in existing.also_relevant:
                        existing.also_relevant.append(index)
                    continue
                if len(docs) >= budget:
                    break
                # The subquestion that *found* a document is not necessarily the one it
                # answers: assign by best term match so the plan's gaps mean something.
                doc.subquestion = _assign_subquestion(
                    f"{doc.title}\n{doc.text}", plan, question
                )
                docs.append(doc)
                by_ref[doc.ref] = doc
            if len(docs) >= budget:
                break
        return docs

    def _load_hit(self, hit, subquestion: int) -> SourceDoc | None:
        """Turn a search hit into a document, reading the real content where possible."""
        max_bytes = int(self._cfg("research.max_source_bytes", 262144))
        try:
            if hit.kind == "file":
                path = str((hit.meta or {}).get("path") or "")
                if not path:
                    path = (
                        hit.ref.replace("file://", "")
                        if hit.ref.startswith("file://")
                        else ""
                    )
                resolved = self._inside_roots(path)
                if resolved is None:
                    return None
                with open(resolved, "rb") as handle:
                    raw = handle.read(max_bytes + 1)
                truncated = len(raw) > max_bytes
                body = raw[:max_bytes].decode("utf-8", errors="replace")
                return SourceDoc(
                    kind="file",
                    ref=hit.ref,
                    url=hit.ref,
                    title=hit.title or resolved,
                    text=body,
                    excerpt="",
                    status="fetched",
                    checksum=_sha256(raw[:max_bytes]),
                    bytes=len(raw[:max_bytes]),
                    truncated=truncated,
                    subquestion=subquestion,
                    credibility="internal",
                    publisher="workspace",
                )
            if hit.kind == "memory":
                stored = self.ws.memory.get(hit.id)
                if stored.is_err:
                    raise stored.error
                memory = stored.value
                body = memory.content
                return SourceDoc(
                    kind="memory",
                    ref=hit.ref,
                    url=f"archx:memory/{memory.id}",
                    title=memory.title,
                    text=body,
                    checksum=_sha256(body.encode()),
                    bytes=len(body.encode()),
                    subquestion=subquestion,
                    credibility="internal",
                    publisher="memory",
                )
            if hit.kind == "conversation":
                messages = self.ws.conversations.messages(hit.id)
                body = "\n\n".join(f"{m.role}: {m.content}" for m in messages)
                body = body[:max_bytes]
                return SourceDoc(
                    kind="conversation",
                    ref=hit.ref,
                    url=f"archx:conversation/{hit.id}",
                    title=hit.title or "conversation",
                    text=body,
                    checksum=_sha256(body.encode()),
                    bytes=len(body.encode()),
                    subquestion=subquestion,
                    credibility="internal",
                    publisher="conversation",
                )
            if hit.kind == "task":
                task = self.ws.tasks.get(hit.id)
                if task.type == "research":
                    # A research task is the record of a run, not a source: its findings live
                    # in that run's report, and citing the task would be citing ourselves.
                    return None
                body = "\n\n".join(
                    part
                    for part in [
                        task.title,
                        str((task.metadata or {}).get("summary") or ""),
                        task.error or "",
                    ]
                    if part
                )
                return SourceDoc(
                    kind="task",
                    ref=hit.ref,
                    url=f"archx:task/{task.id}",
                    title=hit.title or task.title,
                    text=body,
                    checksum=_sha256(body.encode()),
                    bytes=len(body.encode()),
                    subquestion=subquestion,
                    credibility="internal",
                    publisher="tasks",
                )
            if hit.kind == "workflow":
                workflow = self.ws.workflows.get(hit.id)
                body = "\n\n".join(
                    part
                    for part in [
                        workflow.name,
                        workflow.goal or "",
                        str((workflow.metadata or {}).get("summary") or ""),
                    ]
                    if part
                )
                return SourceDoc(
                    kind="workflow",
                    ref=hit.ref,
                    url=f"archx:workflow/{workflow.id}",
                    title=hit.title or workflow.name,
                    text=body,
                    checksum=_sha256(body.encode()),
                    bytes=len(body.encode()),
                    subquestion=subquestion,
                    credibility="internal",
                    publisher="workflows",
                )
        except (NotFoundError, ArchxError, OSError) as exc:
            return SourceDoc(
                kind=hit.kind,
                ref=hit.ref,
                url=hit.ref,
                title=hit.title or hit.ref,
                status="failed",
                error=getattr(exc, "message", str(exc)),
                subquestion=subquestion,
                credibility="unknown",
                publisher=hit.kind,
            )
        return None

    def _inside_roots(self, path: str) -> str | None:
        from pathlib import Path

        if not path:
            return None
        candidate = Path(path).expanduser()
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            return None
        for root in self.ws.tool_roots():
            try:
                resolved.relative_to(Path(root).resolve())
                return str(resolved)
            except ValueError:
                continue
        return None

    def gather_web(
        self,
        urls: Sequence[str],
        question: str,
        plan: Sequence[Mapping[str, Any]],
        *,
        task_id: str | None = None,
        run_id: str | None = None,
        allow_private_hosts: bool | None = None,
    ) -> list[SourceDoc]:
        max_bytes = int(self._cfg("research.max_source_bytes", 262144))
        docs: list[SourceDoc] = []
        for url in urls:
            args: dict[str, Any] = {"url": url, "max_bytes": max_bytes}
            if allow_private_hosts is not None:
                args["allow_private_hosts"] = bool(allow_private_hosts)
            try:
                run = self.ws.tools.execute(
                    "net.fetch",
                    args,
                    context=ToolContext(
                        task_id=task_id, purpose=f"research: {question[:120]}"
                    ),
                )
            except ApprovalRequiredError as exc:
                raise ResearchBlocked(
                    "web research needs the net.fetch capability: "
                    f"{getattr(exc, 'message', exc)}",
                    run_id=run_id,
                    approval_id=getattr(exc, "approval_id", None),
                ) from exc
            except ArchxError as exc:
                docs.append(
                    SourceDoc(
                        kind="url",
                        ref=url,
                        url=url,
                        title=url,
                        status="failed",
                        error=getattr(exc, "message", str(exc)),
                        publisher=_host(url),
                        credibility="unknown",
                        subquestion=_best_subquestion(url, plan),
                    )
                )
                continue
            if run.status != "succeeded" or not run.result:
                docs.append(
                    SourceDoc(
                        kind="url",
                        ref=url,
                        url=url,
                        title=url,
                        status="failed",
                        error=run.error or "fetch failed",
                        publisher=_host(url),
                        credibility="unknown",
                        subquestion=_best_subquestion(url, plan),
                    )
                )
                continue
            result = run.result
            text = str(result.get("text") or "")
            title = str(result.get("title") or "") or _host(url)
            doc = SourceDoc(
                kind="url",
                ref=str(result.get("final_url") or url),
                url=url,
                title=title,
                text=text,
                status="fetched",
                checksum=result.get("sha256"),
                bytes=int(result.get("bytes") or 0),
                truncated=bool(result.get("truncated")),
                publisher=_host(url),
                credibility="unknown",
                subquestion=_best_subquestion(text or title, plan),
            )
            if not doc.text.strip():
                doc.status = "failed"
                doc.error = "the page contained no readable text"
            docs.append(doc)
        return docs
