"""cc-retrospect learn — Behavioral profiling and learnings generation."""
from __future__ import annotations

import logging
import sys
from collections import Counter, defaultdict
from datetime import datetime

from cc_retrospect.config import Config, load_config
from cc_retrospect.models import UserProfile
from cc_retrospect.parsers import iter_project_sessions, iter_jsonl, _pricing_for_model
from cc_retrospect.utils import _fmt_duration

logger = logging.getLogger("cc_retrospect")


def analyze_user_messages(config: Config) -> UserProfile:
    """Scan all JSONL files and build a behavioral profile."""
    lengths = []
    openers = Counter()
    approvals = Counter()
    corrections = 0
    frustrations = 0
    frust_words = Counter()
    gratitude = 0
    rapid_fire = 0
    consec_user = 0
    total_user = 0
    total_gaps = 0
    mega = 0

    # Efficiency tracking
    read_edit_read = 0
    tool_after_frust = Counter()

    # Work patterns
    hour_counts = Counter()
    daily_projects = defaultdict(set)

    # Session-level
    session_durations = []
    session_msg_counts = []

    # Cost
    total_input = 0
    total_output = 0
    total_cache_create = 0
    total_cache_read = 0
    model_costs = Counter()

    mega_threshold = config.thresholds.mega_prompt_chars
    frust_keywords = [k.lower() for k in config.thresholds.frustration_keywords]
    approval_words = {"yes", "y", "ok", "do it", "go", "proceed", "continue", "yep",
                      "yeah", "sure", "go ahead", "lets go", "let's go", "ship it", "lgtm"}

    for proj_name, jsonl_path in iter_project_sessions(config.claude_dir):
        if "subagents" in str(jsonl_path):
            continue

        prev_type = None
        prev_user_ts = None
        prev_tool = None
        prev_file_read = None
        was_frustrated = False
        sess_first_ts = None
        sess_last_ts = None
        sess_msgs = 0
        local_consec = 0

        for entry in iter_jsonl(jsonl_path):
            etype = entry.get("type", "")
            ts_str = entry.get("timestamp", "")
            ts = None
            if ts_str:
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    if not sess_first_ts:
                        sess_first_ts = ts
                    sess_last_ts = ts
                except (ValueError, TypeError):
                    pass

            if etype == "user":
                total_user += 1
                sess_msgs += 1
                content = entry.get("message", {}).get("content", "")
                if isinstance(content, list):
                    content = " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
                if not isinstance(content, str) or len(content) < 2:
                    prev_type = "user"
                    continue
                if content.startswith("This session is being continued"):
                    prev_type = "user"
                    continue

                clen = len(content)
                lengths.append(clen)
                words = content.split()

                # Openers
                if words:
                    opener = words[0].lower().strip(".,!?:;\"'()[]{}< >")
                    if (opener
                        and not opener.startswith("<")
                        and not opener.startswith("/")
                        and ">" not in opener
                        and opener not in ("task-notification", "local-command-caveat", "local-command-stdout",
                                           "command-name", "status", "system-reminder")):
                        openers[opener] += 1

                # Mega
                if clen > mega_threshold:
                    mega += 1

                # Approvals
                cl = content.lower().strip()
                if cl in approval_words:
                    approvals[cl] += 1

                # Corrections
                if cl.startswith(("no ", "not ", "i mean", "wrong", "that's not", "no,")):
                    corrections += 1

                # Frustration
                if clen < 100:
                    for kw in frust_keywords:
                        if kw in cl:
                            frustrations += 1
                            frust_words[kw.strip()] += 1
                            was_frustrated = True
                            break
                    else:
                        was_frustrated = False
                else:
                    was_frustrated = False

                # Gratitude
                if any(w in cl for w in ["thanks", "thank you", "thx", "great", "perfect", "nice", "awesome"]):
                    gratitude += 1

                # Rapid fire
                if ts and prev_user_ts:
                    gap = (ts - prev_user_ts).total_seconds()
                    total_gaps += 1
                    if gap < 5:
                        rapid_fire += 1

                # Consecutive user
                if prev_type == "user":
                    local_consec += 1
                    if local_consec >= 2:
                        consec_user += 1
                else:
                    local_consec = 0

                # Hour
                if ts:
                    hour_counts[ts.hour] += 1
                    if ts_str:
                        daily_projects[ts_str[:10]].add(proj_name)

                prev_user_ts = ts
                prev_type = "user"

            elif etype == "assistant":
                sess_msgs += 1
                msg = entry.get("message", {})
                usage = msg.get("usage", {})
                model = msg.get("model", "")

                if usage:
                    total_input += usage.get("input_tokens", 0)
                    total_output += usage.get("output_tokens", 0)
                    total_cache_create += usage.get("cache_creation_input_tokens", 0)
                    total_cache_read += usage.get("cache_read_input_tokens", 0)
                    if model:
                        pricing = _pricing_for_model(model, config.pricing)
                        c = usage.get("input_tokens", 0) / 1e6 * pricing.input_per_mtok + usage.get("output_tokens", 0) / 1e6 * pricing.output_per_mtok
                        model_costs[model] += c

                # Tool extraction
                content_blocks = msg.get("content", [])
                if isinstance(content_blocks, list):
                    for block in content_blocks:
                        if isinstance(block, dict) and block.get("type") == "tool_use":
                            tool = block.get("name", "")

                            if was_frustrated and tool:
                                tool_after_frust[tool] += 1

                            # Read-edit-read
                            tool_input = block.get("input", {})
                            if isinstance(tool_input, dict):
                                if tool == "Read":
                                    fp = tool_input.get("file_path", "")
                                    if prev_tool == "Edit" and prev_file_read and fp == prev_file_read:
                                        read_edit_read += 1
                                    prev_file_read = fp

                            prev_tool = tool

                prev_type = "assistant"
                was_frustrated = False

        # Session summary
        if sess_first_ts and sess_last_ts:
            dur = (sess_last_ts - sess_first_ts).total_seconds() / 60
            session_durations.append(dur)
            session_msg_counts.append(sess_msgs)

    # Build profile
    lengths.sort()
    total_all_input = total_input + total_cache_create + total_cache_read
    cache_rate = (total_cache_read / total_all_input * 100) if total_all_input > 0 else 0

    # Top cost driver
    if session_durations and sum(session_durations) / len(session_durations) > 120:
        top_driver = "session_length"
    elif model_costs and model_costs.get("claude-opus-4-6", 0) > sum(model_costs.values()) * 0.8:
        top_driver = "model_choice"
    else:
        top_driver = "subagents"

    peak = sorted(hour_counts.items(), key=lambda x: x[1], reverse=True)[:3]
    ppd = sum(len(v) for v in daily_projects.values()) / max(len(daily_projects), 1)

    return UserProfile(
        total_messages=total_user,
        median_length=lengths[len(lengths) // 2] if lengths else 0,
        avg_length=sum(lengths) / len(lengths) if lengths else 0,
        single_word_pct=len([l for l in lengths if l < 15]) / max(total_user, 1) * 100,
        mega_prompt_pct=mega / max(total_user, 1) * 100,
        top_openers=sorted(openers.items(), key=lambda x: x[1], reverse=True)[:10],
        approval_signals=dict(approvals.most_common(10)),
        correction_count=corrections,
        frustration_rate=frustrations / max(total_user, 1) * 100,
        frustration_words=dict(frust_words.most_common(10)),
        gratitude_rate=gratitude / max(total_user, 1) * 100,
        rapid_fire_pct=rapid_fire / max(total_gaps, 1) * 100,
        consecutive_user_msgs=consec_user,
        read_edit_read_count=read_edit_read,
        peak_hours=[h for h, _ in peak],
        projects_per_day_avg=ppd,
        avg_session_duration=sum(session_durations) / len(session_durations) if session_durations else 0,
        avg_session_messages=sum(session_msg_counts) / len(session_msg_counts) if session_msg_counts else 0,
        top_cost_driver=top_driver,
        cache_hit_rate=cache_rate,
        total_sessions=len(session_durations),
        model_breakdown=dict(model_costs.most_common()),
        tool_after_frustration=dict(tool_after_frust.most_common(5)),
    )


def generate_style(profile: UserProfile, config=None) -> str:
    """Generate a STYLE.md based on detected patterns."""
    if config is None:
        from cc_retrospect.config import default_config
        config = default_config()
    sc = config.style

    # Template mode: if user provides a template, use it
    if sc.template_path:
        from pathlib import Path
        template_file = Path(sc.template_path)
        if template_file.exists():
            try:
                return template_file.read_text(encoding="utf-8").format_map(profile.model_dump())
            except (KeyError, ValueError):
                pass  # Fall through to rule-based generation

    enabled = set(sc.enabled_rules)
    lines = ["# Response Style", ""]

    if "core_style" in enabled:
        if profile.median_length < 100:
            lines.append("Be extremely concise. Lead with answer or action, not reasoning. No preamble, no trailing summaries, no \"I'll now...\" narration. First sentence = the answer. Skip filler.")
        elif profile.median_length < 300:
            lines.append("Be concise but thorough. Lead with the answer, add brief context only when needed.")
        else:
            lines.append("Match the user's detail level. They write detailed prompts — provide proportionally detailed responses.")

    if "corrections" in enabled and profile.correction_count > sc.correction_threshold:
        lines.append('When I say "no X" — change only X, keep everything else.')

    if "approvals" in enabled:
        top_approvals = list(profile.approval_signals.keys())[:3]
        if top_approvals:
            quoted = ", ".join(f'"{a}"' for a in top_approvals)
            lines.append(f"When I say {quoted} — execute immediately, zero recap.")

    if "mega_paste" in enabled and profile.mega_prompt_pct > sc.mega_pct_threshold:
        lines.append("When I paste content — scan it, act on it, don't ask what I want.")

    if "frustration" in enabled and profile.frustration_rate > sc.frustration_threshold:
        lines.append("On frustration signals — pause, re-read context, don't blindly execute. Suggest a different approach.")

    if "compression" in enabled:
        lines.append("")
        lines.append("## Output Compression")
        lines.append("Drop articles (a/an/the), filler words, pleasantries, hedging. Use short synonyms. Fragments OK. Keep technical terms exact, code blocks unchanged, error quotes verbatim. Revert to normal for security warnings, irreversible actions, or multi-step sequences where clarity matters.")

    # Append user's custom rules
    if sc.custom_rules:
        lines.append("")
        lines.append("## Custom Rules")
        lines.extend(sc.custom_rules)

    return "\n".join(lines) + "\n"


def generate_learnings(profile: UserProfile) -> str:
    """Generate transferable LEARNINGS.md from behavioral patterns."""
    sections = ["# Session Learnings", "",
                 "Auto-generated behavioral rules. Drop into ~/.claude/ or share as a template.", ""]

    # Message style
    sections.append("## Communication Style")
    if profile.median_length < 100:
        sections.append(f"- User is terse (median {profile.median_length} chars). Match their brevity.")
    if profile.single_word_pct > 5:
        sections.append(f"- {profile.single_word_pct:.0f}% of messages are single-word commands. Treat as directives.")
    if profile.top_openers:
        top3 = ", ".join(f'"{w}"' for w, _ in profile.top_openers[:5])
        sections.append(f"- Most common openers: {top3}")

    # Corrections
    if profile.correction_count > 5:
        sections.append("")
        sections.append("## Correction Pattern")
        sections.append(f'- User corrects via "no X" ({profile.correction_count} occurrences). Means "change only X."')
        sections.append("- Don't revert unrelated work when correcting.")

    # Approvals
    if profile.approval_signals:
        sections.append("")
        sections.append("## Approval Signals")
        for sig, count in profile.approval_signals.items():
            sections.append(f'- "{sig}" x{count} — means execute now, no confirmation needed.')

    # Frustration
    if profile.frustration_rate > 2:
        sections.append("")
        sections.append("## Frustration Response")
        sections.append(f"- Frustration rate: {profile.frustration_rate:.1f}% of messages.")
        if profile.tool_after_frustration:
            top_tool = list(profile.tool_after_frustration.keys())[0]
            sections.append(f"- After frustration, Claude defaults to {top_tool}. Should Read context first instead.")
        sections.append("- When stuck, suggest /clear and fresh restatement rather than iterating.")

    # Efficiency
    sections.append("")
    sections.append("## Efficiency Rules")
    if profile.rapid_fire_pct > 30:
        sections.append(f"- User sends rapid-fire messages ({profile.rapid_fire_pct:.0f}% within 5s). Don't act on partial sequences.")
    if profile.consecutive_user_msgs > 20:
        sections.append(f"- {profile.consecutive_user_msgs} consecutive messages without response. Wait for completion.")
    if profile.read_edit_read_count > 10:
        sections.append(f"- {profile.read_edit_read_count} read-edit-read cycles detected. Don't re-read after Edit — it confirms success.")

    # Work patterns
    sections.append("")
    sections.append("## Work Patterns")
    if profile.peak_hours:
        hours_str = ", ".join(f"{h}:00" for h in profile.peak_hours)
        sections.append(f"- Peak hours (UTC): {hours_str}")
    if profile.projects_per_day_avg > 2:
        sections.append(f"- Avg {profile.projects_per_day_avg:.1f} projects/day. Expect frequent context switches.")
    sections.append(f"- Avg session: {_fmt_duration(profile.avg_session_duration)}, {profile.avg_session_messages:.0f} messages")

    # Cost
    sections.append("")
    sections.append("## Cost Awareness")
    sections.append(f"- Top cost driver: {profile.top_cost_driver.replace('_', ' ')}")
    sections.append(f"- Cache hit rate: {profile.cache_hit_rate:.1f}%")
    if profile.avg_session_messages > 200:
        sections.append(f"- Sessions average {profile.avg_session_messages:.0f} messages. Nudge /compact at 150.")
    if profile.top_cost_driver == "model_choice":
        sections.append("- Suggest /model sonnet for routine Read/Edit/Bash work.")

    return "\n".join(sections) + "\n"


def run_learn(payload: dict = {}, *, config: Config | None = None) -> int:
    """Analyze user messages and generate STYLE.md + LEARNINGS.md."""
    config = config or load_config()
    print("Scanning session data...", file=sys.stderr)

    profile = analyze_user_messages(config)

    style_content = generate_style(profile, config)
    learnings_content = generate_learnings(profile)

    # Write to data dir
    config.data_dir.mkdir(parents=True, exist_ok=True)
    style_path = config.data_dir / "STYLE.md"
    learnings_path = config.data_dir / "LEARNINGS.md"
    style_path.write_text(style_content, encoding="utf-8")
    learnings_path.write_text(learnings_content, encoding="utf-8")

    # Print profile summary
    print(f"## User Profile ({profile.total_messages} messages, {profile.total_sessions} sessions)")
    print(f"  Median message: {profile.median_length} chars")
    print(f"  Rapid-fire rate: {profile.rapid_fire_pct:.0f}%")
    print(f"  Frustration rate: {profile.frustration_rate:.1f}%")
    print(f"  Correction count: {profile.correction_count}")
    print(f"  Read-edit-read waste: {profile.read_edit_read_count}")
    print(f"  Avg session: {_fmt_duration(profile.avg_session_duration)}, {profile.avg_session_messages:.0f} msgs")
    print(f"  Top cost driver: {profile.top_cost_driver}")
    print()
    print("--- Generated STYLE.md ---")
    print(style_content)
    print("--- Generated LEARNINGS.md ---")
    print(learnings_content)
    print("Files written to:")
    print(f"  {style_path}")
    print(f"  {learnings_path}")
    print()
    print("To apply: copy STYLE.md to ~/.claude/STYLE.md and add @STYLE.md to ~/.claude/CLAUDE.md")
    print("To share: LEARNINGS.md contains no PII — safe to share as a template.")
    return 0
