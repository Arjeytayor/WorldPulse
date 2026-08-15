"""Pipeline scheduler — APScheduler with corrected deep-dive timing."""

from datetime import date

from logger import logger


def run_pipeline() -> int:
    """Full daily pipeline — fetch, score, deep-dive, generate, deliver.

    Returns the number of topics that produced content. Raises on failure so
    callers (``run_once.py``, cron) see a non-zero exit code — a scheduled run
    that cannot report failure is indistinguishable from one that succeeded.
    """
    from research import fetch_all_briefs, cleanup_old_cache
    from topic_scorer import pick_best_topics
    from generator_article import generate_article
    from generator_script import generate_script
    from telegram_bot import send_daily_output
    from humanizer import humanize
    from agent_reach import deep_dive
    from config import DEEP_DIVE_THRESHOLD
    import config

    try:
        logger.info("=== WorldPulse pipeline started ===")

        # ── Step 1: Fetch broad discovery (Stage 1 only) ──
        logger.info("Fetching research briefs...")
        all_research = fetch_all_briefs()
        total_topics = len(all_research)

        # ── Step 2: Deduplicate + score + pick top topics ──
        logger.info("Scoring and picking best topics...")
        best_topics = pick_best_topics(all_research, max_picks=2)
        if not best_topics:
            logger.warning("No topics passed deduplication — skipping today")
            return 0

        picked_count = len(best_topics)
        logger.info(f"Selected {picked_count} topics for content generation")

        # ── Step 3: Deep dive (Stage 2) for picked topics only ──
        for research in best_topics:
            topic = research.get("_topic", "")
            display_topic = research.get("_headline", topic)  # Show headline if available
            engagement = research.get("engagement_score", 0)

            if engagement >= DEEP_DIVE_THRESHOLD:
                logger.info(f"Topic '{display_topic}' (engagement={engagement}) — firing Agent-Reach deep dive")
                raw = deep_dive(topic, research)
                research["_deep_dive"] = raw
                research["_deep_dive_fired"] = True
            else:
                logger.info(f"Topic '{display_topic}' (engagement={engagement}) — deep dive skipped (below threshold)")
                research["_deep_dive"] = {}
                research["_deep_dive_fired"] = False

        # ── Step 4: Generate content ──
        generated_count = 0
        for research in best_topics:
            topic = research.get("_topic", "")
            display_topic = research.get("_headline", topic)
            logger.info(f"Generating article + script for '{display_topic}'...")

            article_orig = generate_article(research)
            script_orig = generate_script(research)

            # Skip if either generation produced empty content
            if not article_orig or not article_orig.strip():
                logger.error(f"Article generation failed for topic '{display_topic}' — skipping")
                continue
            if not script_orig or not script_orig.strip():
                logger.error(f"Script generation failed for topic '{display_topic}' — skipping")
                continue

            # Humanizer pass (optional — config flag)
            if config.HUMANIZE_DEFAULT:
                article_humanized = humanize(article_orig)
                script_humanized = humanize(script_orig)
            else:
                article_humanized = None
                script_humanized = None

            article = article_humanized if article_humanized else article_orig
            script = script_humanized if script_humanized else script_orig

            # Build paths (topic_slug based on the search key for uniqueness)
            import os
            topic_slug = topic.lower().replace(" ", "_")
            today = date.today().isoformat()
            articles_dir = os.path.join(config.OUTPUT_DIR, "articles")
            scripts_dir = os.path.join(config.OUTPUT_DIR, "scripts")
            article_path = os.path.join(articles_dir, f"{today}_{topic_slug}.md")
            script_path = os.path.join(scripts_dir, f"{today}_{topic_slug}_script.md")
            article_orig_path = os.path.join(articles_dir, f"{today}_{topic_slug}_original.md")
            script_orig_path = os.path.join(scripts_dir, f"{today}_{topic_slug}_original_script.md")

            # Save even if Telegram fails (so we have the content)
            os.makedirs(os.path.dirname(article_path), exist_ok=True)
            with open(article_path, "w", encoding="utf-8") as f:
                f.write(article)
            os.makedirs(os.path.dirname(script_path), exist_ok=True)
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(script)
            # Always save original too
            with open(article_orig_path, "w", encoding="utf-8") as f:
                f.write(article_orig)
            with open(script_orig_path, "w", encoding="utf-8") as f:
                f.write(script_orig)

            generated_count += 1

            # ── Step 5: Build briefing card ──
            score = research.get("_score", 0)
            word_count = len(article.split())
            runtime_estimate = max(1, len(script.split()) // 3) if script else 0
            humanize_status = "Applied" if config.HUMANIZE_DEFAULT else "Skipped (original only)"

            briefing = f"""📡 <b>WorldPulse Daily Brief — {date.today().strftime('%B %d, %Y')}</b>

Topics researched today: {total_topics}
Topics filtered as duplicate: {total_topics - picked_count}
Topics selected for content: {picked_count}

━━━━━━━━━━━━━━
📝 TODAY'S ARTICLE
Topic: {display_topic}
Trending score: {score:.2f}
Word count: {word_count}
Deep dive fired: {'Yes' if research.get('_deep_dive_fired') else 'No'}
Humanizer: {humanize_status}

🎬 TODAY'S SHORTS SCRIPT
Topic: {display_topic}
Estimated runtime: ~{runtime_estimate}s

Content ready below 👇"""

            # ── Step 6: Deliver ──
            send_daily_output(
                briefing, article, script,
                article_path, script_path,
                article_orig_path, script_orig_path,
                article_humanized if config.HUMANIZE_DEFAULT else "",
                script_humanized if config.HUMANIZE_DEFAULT else ""
            )

            # ── Step 7: Publish to Substack + X ──
            if config.POST_SUBSTACK or config.POST_X:
                from posts import publish_article, post_x

            if config.POST_SUBSTACK:
                logger.info(f"Publishing article to Substack: {topic}")
                try:
                    publish_article(
                        title=topic,
                        article=article,
                        excerpt=research.get("synthesis", "")[:200],
                        publish=False,  # always draft first for manual review
                    )
                except Exception:
                    logger.error("Substack publish failed", exc_info=True)

            if config.POST_X:
                logger.info(f"Posting to X: {topic}")
                try:
                    # Build a concise thread from the script + article
                    from posts import post_x_thread
                    hook = research.get("synthesis", topic)[:200]
                    # First tweet: the hook
                    # Second tweet: one key data point
                    data_point = research.get("synthesis", ".")[:250]
                    thread = [
                        hook,
                        f"Key signal: {data_point}",
                        "Follow for daily global finance takes.",
                    ]
                    post_x_thread(thread)
                except Exception:
                    logger.error("X post failed", exc_info=True)

        # ── Step 7b: A run that produced nothing is a failed run ──
        # Every per-topic failure above only logs and `continue`s, so without
        # this check the pipeline reaches "completed successfully" having
        # written zero files — the exact failure a dead model pool produces.
        if generated_count == 0:
            raise RuntimeError(
                f"Pipeline generated no content: {picked_count} topic(s) selected, "
                f"0 produced both an article and a script. Check model availability "
                f"with nim_client.health_check()."
            )

        # ── Step 8: Cleanup ──
        cleanup_old_cache(days=7)
        logger.info(
            f"=== WorldPulse pipeline completed successfully — "
            f"{generated_count}/{picked_count} topics generated ==="
        )
        return generated_count

    except Exception:
        logger.error("Pipeline top-level failure", exc_info=True)
        raise


def start():
    """Start the APScheduler (blocking).  Called from main.py."""
    import pytz
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    wat = pytz.timezone("Africa/Lagos")
    scheduler = BlockingScheduler(timezone=wat)
    scheduler.add_job(run_pipeline, CronTrigger(hour=7, minute=0, timezone=wat))
    print("WorldPulse scheduler started. Running daily at 07:00 WAT.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("Scheduler stopped.")
