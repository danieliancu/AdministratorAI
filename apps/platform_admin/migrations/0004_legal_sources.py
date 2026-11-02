from django.db import migrations

ROLE = "aai_platform_definer"
ATTRS = "LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp"
P = "public.legal_knowledge_"

OBJECTS = f"""
    GRANT SELECT ON legal_knowledge_legalsource, legal_knowledge_legalsyncjob,
        legal_knowledge_legalchangeevent, legal_knowledge_legalact,
        legal_knowledge_legalactversion, legal_knowledge_legaldocument,
        legal_knowledge_legalchunk, legal_knowledge_legalembedding,
        ai_gateway_aiplatformbudget TO {ROLE};
    GRANT UPDATE (is_enabled) ON legal_knowledge_legalsource TO {ROLE};
    GRANT UPDATE (status, reviewed_by_id, reviewed_at, review_note)
        ON legal_knowledge_legalchangeevent TO {ROLE};
    GRANT UPDATE (review_status, reviewed_at) ON legal_knowledge_legalactversion TO {ROLE};

    SET LOCAL ROLE {ROLE};

    CREATE VIEW platform.legal_sources WITH (security_barrier) AS
        SELECT s.key, s.name, s.official_url, s.connector, s.access_restrictions,
               s.licence_status, s.is_enabled, s.schedule_minutes, s.freshness_hours,
               s.last_attempt_at, s.last_success_at, s.last_document_at, s.last_error,
               s.consecutive_failures, s.circuit_open_until,
               (s.connector IN ('soap', 'rss') AND (s.last_success_at IS NULL OR
                now() - s.last_success_at > make_interval(hours => s.freshness_hours)))
                   AS is_stale,
               (SELECT count(*) FROM {P}legaldocument d WHERE d.source_id = s.key) AS documents
        FROM {P}legalsource s;

    CREATE VIEW platform.legal_changes WITH (security_barrier) AS
        SELECT c.id, c.kind, c.summary, c.status, c.created_at, c.review_note, c.reviewed_at,
               c.source_id, c.version_id, d.url AS document_url, d.title AS document_title
        FROM {P}legalchangeevent c
        LEFT JOIN {P}legaldocument d ON d.id = c.document_id;

    CREATE VIEW platform.legal_corpus WITH (security_barrier) AS
        SELECT
            (SELECT count(*) FROM {P}legalact) AS acts,
            (SELECT count(*) FROM {P}legalactversion) AS versions,
            (SELECT count(*) FROM {P}legalchunk) AS chunks,
            (SELECT count(*) FROM {P}legalembedding) AS embeddings,
            (SELECT count(*) FROM {P}legalembedding WHERE is_synthetic) AS synthetic_embeddings,
            (SELECT count(*) FROM {P}legalchangeevent WHERE status = 'pending') AS pending;

    CREATE VIEW platform.ai_platform_budget WITH (security_barrier) AS
        SELECT period_start, period_end, currency, limit_amount, spent, reserved
        FROM public.ai_gateway_aiplatformbudget;

    CREATE FUNCTION platform.set_legal_source_enabled(
        actor uuid, source text, enabled boolean, reason text
    ) RETURNS void {ATTRS} AS $$
    BEGIN
        PERFORM platform.require_superadmin(actor);
        PERFORM platform.require_reason(reason);
        UPDATE {P}legalsource SET is_enabled = enabled
            WHERE key = source AND connector IN ('soap', 'rss');
        IF NOT FOUND THEN
            RAISE EXCEPTION 'source has no connector' USING ERRCODE = 'P0002';
        END IF;
        PERFORM platform.record_event(actor, 'legal.source.' ||
            CASE WHEN enabled THEN 'enabled' ELSE 'disabled' END, NULL, reason,
            jsonb_build_object('source', source));
    END $$;

    CREATE FUNCTION platform.review_legal_change(
        actor uuid, change uuid, decision text, note text
    ) RETURNS void {ATTRS} AS $$
    DECLARE
        event record;
    BEGIN
        PERFORM platform.require_superadmin(actor);
        PERFORM platform.require_reason(note);
        IF decision NOT IN ('approved', 'rejected') THEN
            RAISE EXCEPTION 'unknown decision' USING ERRCODE = '22023';
        END IF;
        SELECT * INTO event FROM {P}legalchangeevent WHERE id = change FOR UPDATE;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'change not found' USING ERRCODE = 'P0002';
        END IF;
        IF event.status <> 'pending' THEN
            RAISE EXCEPTION 'change already reviewed' USING ERRCODE = '22023';
        END IF;
        UPDATE {P}legalchangeevent
            SET status = decision, reviewed_by_id = actor, reviewed_at = now(), review_note = note
            WHERE id = change;
        IF event.version_id IS NOT NULL THEN
            UPDATE {P}legalactversion
                SET review_status = CASE WHEN decision = 'approved' THEN 'reviewed'
                                         ELSE 'rejected' END,
                    reviewed_at = now()
                WHERE id = event.version_id;
        END IF;
        PERFORM platform.record_event(actor, 'legal.change.' || decision, NULL, note,
            jsonb_build_object('change', change, 'version', event.version_id));
    END $$;

    REVOKE ALL ON FUNCTION platform.set_legal_source_enabled(uuid, text, boolean, text),
        platform.review_legal_change(uuid, uuid, text, text) FROM PUBLIC;
    GRANT EXECUTE ON FUNCTION platform.set_legal_source_enabled(uuid, text, boolean, text),
        platform.review_legal_change(uuid, uuid, text, text) TO aai_platform;
    GRANT SELECT ON platform.legal_sources, platform.legal_changes, platform.legal_corpus,
        platform.ai_platform_budget TO aai_platform;

    RESET ROLE;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("platform_admin", "0003_ai_costs_superadmin_only"),
        ("ai_gateway", "0005_platform_budget_grants"),
        ("legal_knowledge", "0002_protection_and_sources"),
    ]

    operations = [migrations.RunSQL(OBJECTS, migrations.RunSQL.noop)]
