"""Voice command: argument registration and execution."""

from __future__ import annotations

import argparse


from archx_agent.helpers.exceptions import (
    ArchxError,
    NotFoundError,
    ValidationError,
)


from archx_agent.interfaces.cli.support import (
    emit,
    emit_json,
    table,
    fail,
    _workspace,
    EXIT_OK,
    EXIT_ERROR,
    EXIT_USAGE,
    EXIT_DEGRADED,
)


def register_parser(sub: argparse._SubParsersAction) -> None:
    voice = sub.add_parser(
        "voice",
        help="Voice and media: measure files, keep transcripts, say what cannot be heard",
    )
    vo_sub = voice.add_subparsers(dest="voice_command", required=True)
    vo_probe = vo_sub.add_parser("probe", help="measure a file's bytes (needs fs.read)")
    vo_probe.add_argument("path")
    vo_probe.add_argument(
        "--retain",
        action="store_true",
        help="keep a copy of the bytes (needs voice.retain_audio)",
    )
    vo_probe.add_argument(
        "--force",
        action="store_true",
        help="store a second row even if these bytes are already known",
    )
    vo_list = vo_sub.add_parser("list", help="measured media, newest first")
    vo_list.add_argument("--kind", choices=["image", "audio", "text", "unknown"])
    vo_list.add_argument("--limit", type=int, default=20)
    vo_show = vo_sub.add_parser(
        "show", help="one asset: what the bytes said, its words, its attempts"
    )
    vo_show.add_argument("asset")
    vo_tr = vo_sub.add_parser(
        "transcribe", help="ask for words (refused: this build has no speech model)"
    )
    vo_tr.add_argument("asset")
    vo_say = vo_sub.add_parser(
        "say", help="ask for speech (refused: this build has no speech model)"
    )
    vo_say.add_argument("text")
    vo_add = vo_sub.add_parser(
        "transcript", help="the words a person wrote for a recording"
    )
    vo_add_sub = vo_add.add_subparsers(dest="transcript_command", required=True)
    vo_add_add = vo_add_sub.add_parser("add", help="attach words you typed")
    vo_add_add.add_argument("asset")
    vo_add_add.add_argument("--text")
    vo_add_add.add_argument("--file", help="read the words from a file (needs fs.read)")
    vo_add_list = vo_add_sub.add_parser("list", help="the words attached to an asset")
    vo_add_list.add_argument("asset")
    vo_at = vo_sub.add_parser(
        "attempts", help="every attempt to hear or speak, refusals included"
    )
    vo_at.add_argument("--asset")
    vo_at.add_argument("--limit", type=int, default=30)
    vo_sub.add_parser("stats", help="what this home holds, and what it still cannot do")


def cmd_voice(args: argparse.Namespace) -> int:
    """`voice ...` - measure media, keep human transcripts, and refuse speech by name.

    Exit codes: 0 the command did what it was asked; 2 the input made no sense (an empty file, a
    transcript with no words, an image asked for words) or an attempt was refused by the mode
    itself. A refusal is `EXIT_DEGRADED` (3) for `transcribe`/`say`, because nothing broke: the
    build genuinely cannot hear, and a script needs to tell that apart from "you typed nothing".
    """
    command = args.voice_command
    try:
        with _workspace(args) as ws:
            service = ws.voice

            if command == "probe":
                asset = service.probe(args.path, retain=args.retain, force=args.force)
                if args.json:
                    emit_json(asset)
                    return EXIT_OK
                if asset.get("duplicate"):
                    emit(f"already measured: {asset['id']}  ({asset['created_at']})")
                    emit(
                        f"  measured  {asset['this_probe']['path']}  {asset['bytes']} bytes"
                    )
                else:
                    emit(f"measured {asset['id']}  {asset['described']}")
                emit(f"  format    {asset['format']}   bytes {asset['bytes']}")
                emit(
                    f"  sha256    {asset['sha256'][:32]}...  ({asset['facts'].get('hash_scope', '-')})"
                )
                if asset["kind"] == "audio" and asset["duration_ms"] is not None:
                    emit(f"  duration  {asset['duration_ms']} ms")
                if asset["name_mismatch"]:
                    emit(f"  note      {asset['name_mismatch']}")
                for note in asset["facts"].get("notes", []):
                    emit(f"  note      {note}")
                if asset.get("metadata", {}).get("retained_path"):
                    emit(f"  retained  {asset['metadata']['retained_path']}")
                emit(f"  next      archx-agent voice show {asset['id']}")
                return EXIT_OK

            if command == "list":
                assets = service.assets(kind=args.kind, limit=args.limit)
                if args.json:
                    emit_json(assets)
                    return EXIT_OK
                if not assets:
                    emit("nothing measured yet (archx-agent voice probe PATH)")
                    return EXIT_OK
                rows = []
                for asset in assets:
                    size = (
                        f"{asset['width']}x{asset['height']}"
                        if asset.get("width")
                        else f"{asset['duration_ms']} ms"
                        if asset.get("duration_ms") is not None
                        else "-"
                    )
                    rows.append(
                        [
                            asset["id"],
                            asset["kind"],
                            asset["format"],
                            size,
                            asset["bytes"],
                            "yes" if asset["name_mismatch"] else "no",
                            asset["created_at"],
                        ]
                    )
                emit(
                    table(
                        rows,
                        [
                            "id",
                            "kind",
                            "format",
                            "size",
                            "bytes",
                            "mislabelled",
                            "created",
                        ],
                    )
                )
                return EXIT_OK

            if command == "show":
                shown = service.view(args.asset)
                if args.json:
                    emit_json(shown)
                    return EXIT_OK
                emit(f"{shown['id']}  {shown['described']}")
                emit(f"  path      {shown['path']}")
                emit(f"  sha256    {shown['sha256']}")
                if shown["name_mismatch"]:
                    emit(f"  note      {shown['name_mismatch']}")
                for note in shown["facts"].get("notes", []):
                    emit(f"  note      {note}")
                if shown["transcripts"]:
                    emit("")
                    emit("  words:")
                    for transcript in shown["transcripts"]:
                        emit(f"    [{transcript['source']}] {transcript['text'][:100]}")
                else:
                    emit("")
                    emit("  words     none - this build cannot recognise speech")
                if shown["attempts"]:
                    emit("")
                    for attempt in shown["attempts"][:6]:
                        line = f"  {attempt['status']:<9} {attempt['action']:<10} {attempt['created_at']}"
                        emit(line)
                        if attempt["reason"]:
                            emit(f"    {attempt['reason'][:140]}")
                return EXIT_OK

            if command == "transcribe":
                result = service.transcribe(args.asset)
                if args.json:
                    emit_json(result)
                    return EXIT_DEGRADED
                emit(f"refused {result['asset_id']}  (attempt {result['attempt_id']})")
                for reason in result["reasons"]:
                    emit(f"  - {reason}")
                emit("")
                emit(f"  what you can do: {result['fix']}")
                return EXIT_DEGRADED

            if command == "say":
                result = service.say(args.text)
                if args.json:
                    emit_json(result)
                    return EXIT_DEGRADED
                emit(
                    f"refused: nothing was synthesised  ({result['chars']} characters asked for)"
                )
                for reason in result["reasons"]:
                    emit(f"  - {reason}")
                return EXIT_DEGRADED

            if command == "transcript":
                if args.transcript_command == "list":
                    transcripts = service.transcripts(args.asset)
                    if args.json:
                        emit_json(transcripts)
                        return EXIT_OK
                    if not transcripts:
                        emit("no words recorded for that asset")
                        return EXIT_OK
                    for transcript in transcripts:
                        emit(
                            f"{transcript['id']}  [{transcript['source']}]  "
                            f"{transcript['chars']} chars  {transcript['created_at']}"
                        )
                        emit(f"  {transcript['text'][:200]}")
                    return EXIT_OK
                transcript = service.add_transcript(
                    args.asset, text=args.text, path=args.file
                )
                if args.json:
                    emit_json(transcript)
                    return EXIT_OK
                emit(
                    f"recorded {transcript['id']}  [{transcript['source']}]  "
                    f"{transcript['chars']} chars"
                )
                emit("  these are the words a person wrote; nothing recognised them")
                return EXIT_OK

            if command == "attempts":
                attempts = service.attempts(asset_id=args.asset, limit=args.limit)
                if args.json:
                    emit_json(attempts)
                    return EXIT_OK
                if not attempts:
                    emit("no attempts yet")
                    return EXIT_OK
                rows = [
                    [
                        a["id"],
                        a["action"],
                        a["status"],
                        a["asset_id"] or "-",
                        a["engine"] or "-",
                        (a["reason"] or "")[:40],
                        a["created_at"],
                    ]
                    for a in attempts
                ]
                emit(
                    table(
                        rows,
                        ["id", "action", "status", "asset", "engine", "why", "when"],
                    )
                )
                return EXIT_OK

            if command == "stats":
                data = service.stats()
                if args.json:
                    emit_json(data)
                    return EXIT_OK
                emit(
                    f"assets      {data['assets']} ({data['images']} image, "
                    f"{data['audio']} audio, {data['audio_ms']} ms of audio)"
                )
                emit(
                    f"mislabelled {data['mislabelled']} (the name disagrees with the bytes)"
                )
                emit(f"transcripts {data['transcripts']} (all written by a person)")
                emit(f"attempts    {data['attempts']} ({data['refused']} refused)")
                emit(
                    f"voice       {'on' if data['enabled'] else 'off'}; "
                    f"stt {data['stt_model'] or 'none'}, tts {data['tts_model'] or 'none'}"
                )
                emit(f"can hear    {'yes' if data['can_transcribe'] else 'no'}")
                emit(f"can speak   {'yes' if data['can_speak'] else 'no'}")
                return EXIT_OK

    except NotFoundError as exc:
        return fail(exc.message, EXIT_ERROR)
    except ValidationError as exc:
        return fail(exc.message, EXIT_USAGE)
    except ArchxError as exc:
        return fail(exc.message, EXIT_ERROR)

    return fail(f"unknown voice command: {command}", EXIT_USAGE)
