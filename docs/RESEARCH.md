# Researcher Mode (M28)

A research run answers a question from documents it actually read, and shows its work. The
three things it will not do are the three things an "AI researcher" usually does:
present a plan it did not follow, cite a source it did not read, and state a conclusion the
evidence does not support.

```
research run "how does sqlite locking work"
   │
   ├─ plan        model (validated JSON) or deterministic rules  -> planned_by: model|rules|user
   │              first subquestion is always the question you asked
   ├─ gather      local: SearchService over memory/conversations/tasks/workflows/files
   │              web:   net.fetch (a capability: the first attempt is refused)
   │              every source is a row - including the ones that could not be read
   ├─ read        file text is read inside the tool roots, hashed, and excerpted
   ├─ judge       relevance is term overlap; stance needs a model and a *quoted* justification
   ├─ synthesise  an extractive answer where every line carries [S<n>]
   │              model prose is kept only for paragraphs whose citations resolve
   ├─ verify      every citation must name a source that exists; every claim must cite one
   └─ record      run + sources + report (row and file) + a research task with the report artifact
```

## The five honesty rules

**1. The plan says who made it.** `planned_by` is `model` only when a model returned JSON
that parsed *and* validated (non-empty questions, no duplicates, capped at
`research.max_subquestions`). Anything else is `rules` - a deterministic plan whose first
subquestion is your own question - or `user`, when you passed `--subquestion`. The report's
`What I could not establish` section states which, because "a model planned this" and "a
rule planned this" are different claims about the same document.

**2. A source that could not be read stays in the record.** Fetches that return 404, hit a
binary content type, or fail to connect become rows with `status = 'failed'` and the error.
They appear in `research sources`, in the limitations, and in the report's source list under
"not usable". They never count towards coverage. An omitted failure reads as "nothing was
there"; a recorded one reads as "I tried and it did not work".

**3. A quote is checked against the document it came from.** When a model judges a source it
must return `{"stance": ..., "relevance": ..., "claims": [{"quote": ..., "why": ...}]}`.
Every quote is matched against the excerpt it was given; a quote that is not a substring is
dropped, not softened. A stance outside `supports|contradicts|background|mixed` invalidates
the judgement, which leaves the source at `unknown` and adds a limitation.

**4. Prose without a citation is demoted, not trusted.** The "Short answer" is assembled
from quoted excerpts, one line per subquestion, each with `[S<n>]`. When a model writes a
reading of the evidence, each paragraph must cite a source that exists; paragraphs that do
not are moved into *Statements I could not tie to a source*. With the simulated runtime this
happens on every run - which is exactly the point: the guard works even when the model is
saying something plausible.

**5. Coverage is computed, not asserted.** `coverage` is the fraction of subquestions with at
least one usable source. A run that found nothing has `status = "incomplete"`, a report whose
second line is **I found no evidence for this question**, and exit code `3`. There is no path
by which an empty run reports success.

## Where evidence comes from

**Local (default).** `SearchService` over the memory systems, conversations, tasks,
workflows and files inside `ws.tool_roots()`. Each subquestion is searched with the
question's terms plus its own, so a facet like "what commonly goes wrong" still finds the
documents about the topic. A document is then assigned to the subquestion it *answers* - a
facet wins only if the document uses vocabulary the facet added (words not already in the
question). That keeps "no source addresses this facet" a real statement instead of a coin
flip between headings.

The run's own task and its planning conversation are excluded: a research run is not its own
evidence.

**Web (opt-in, `--mode web|mixed --url ...`).** Archx does not crawl and does not query a
search engine, so the seed URLs are yours. Each URL goes through the `net.fetch` tool, which
means through the permission centre: the first attempt creates an approval request, prints
`archx-agent approvals approve ap_...`, exits `4`, and fetches nothing. A `net.fetch` grant is
not a licence to reach the machine: loopback, private, link-local and reserved addresses are
refused unless `tools.fetch_allow_private_hosts=true` is set deliberately.

## The report

```
# Research: <question>
- run rs_... - mode local|web|mixed - plan by rules|model|user - coverage 67% (2/3) - N sources

## Short answer (extractive, every line cited)
- **<subquestion>** - [S1] states: "…"

## Evidence by subquestion
### 1. <subquestion>
_<why this subquestion>_
- [S2] "quoted excerpt"
  - source: <title> (<ref>), stance unknown, relevance 0.67

## A model's reading (cited paragraphs only)          # only when a model ran
## Statements I could not tie to a source             # only when the model wrote uncited prose
## Where the sources disagree
## What I could not establish
## Sources
1. [S1] <title> - <ref>
   - kind url, publisher host, sha256 …, N bytes
```

It is written to `<home>/research/<run>.md` (or `--out`), stored in the run row as markdown
as well, and attached to the run's task as an artifact with a checksum - so `tasks show`,
`versions list artifact <path>` and `research report` all describe the same document.

## CLI

```bash
archx-agent research run "how does sqlite locking work"                 # plan, read, report
archx-agent research run "..." --no-model                               # extractive, no model calls
archx-agent research run "..." --subquestion "..." --subquestion "..."  # you set the plan
archx-agent research run "..." --mode web --url https://… --url-file urls.txt
archx-agent research run "..." --format html --out report.html
archx-agent research list [--status] / show RUN / sources RUN / report RUN [--write PATH]
archx-agent research verify RUN          # exit 3 if a citation or a claim fails the check
archx-agent research search QUERY / stats / delete RUN --yes
archx-agent jobs submit research "…" --no-model      # the same run, queued (M26)
```

Exit codes: `0` completed, `3` incomplete or a verification problem, `4` a capability is
needed, `2` bad usage, `1` failed.

## Configuration

| key | default | meaning |
|-----|---------|---------|
| `research.default_mode` | `local` | look locally, on the web, or both |
| `research.max_subquestions` | 8 | plan cap |
| `research.per_source_hits` | 5 | hits per source kind per subquestion |
| `research.gather_limit` | 12 | merged hits considered per subquestion |
| `research.max_sources` | 24 | stop gathering after this many |
| `research.max_source_bytes` | 262144 | read at most this much of one source |
| `research.excerpt_chars` | 600 | how much of a source is quoted |
| `research.max_judged_sources` | 12 | how many sources a model may judge |
| `research.report_format` | `markdown` | stored/written format (`html` available) |
| `tools.fetch_timeout_seconds` | 15 | request timeout |
| `tools.fetch_max_bytes` | 1000000 | fetch byte cap |
| `tools.fetch_max_redirects` | 3 | redirects, each re-checked |
| `tools.fetch_allow_private_hosts` | false | allow loopback/private targets |
| `tools.fetch_store_chars` | 20000 | fetched text kept in the tool run record |

## What this does not do

* It does not search the web on its own: no crawler, no search-engine scraping, no API key
  assumptions. Seed URLs are the user's.
* It does not rate publishers. Credibility is `internal` for your own material and `unknown`
  for web pages; the report says so instead of inventing a ranking.
* It does not read PDFs or binary documents yet (M35 dataset prep brings extraction).
* It does not chain runs or keep a "research project"; each run is a record you can cite.
* It cannot make a model cite honestly - only check whether it did, and demote what it did
  not. A model that quotes accurately and reasons badly is still a bad model.
