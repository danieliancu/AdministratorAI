from django.db import migrations

from apps.core.db.operations import GrantGlobal

P = "legal_knowledge_"
READABLE = [
    "legalsource",
    "legaldocument",
    "legalact",
    "legalactversion",
    "legalapplicability",
    "legalprovision",
    "legalprovisionversion",
    "legalchunk",
    "legalembedding",
    "legalrelationship",
]

WRITER = f"""
    GRANT SELECT ON {", ".join(P + name for name in READABLE)},
        {P}legalsyncjob, {P}legalchangeevent TO aai_legal;
    GRANT INSERT ON {P}legaldocument, {P}legalact, {P}legalactversion, {P}legalapplicability,
        {P}legalprovision, {P}legalprovisionversion, {P}legalchunk, {P}legalembedding,
        {P}legalrelationship, {P}legalsyncjob, {P}legalchangeevent TO aai_legal;
    GRANT UPDATE ON {P}legalsyncjob TO aai_legal;
    GRANT UPDATE (retired_at) ON {P}legalapplicability TO aai_legal;
    -- Status columns only: whether a source runs at all is a decision for a person.
    GRANT UPDATE (last_attempt_at, last_success_at, last_document_at, last_error,
                  consecutive_failures, circuit_open_until) ON {P}legalsource TO aai_legal;
"""

IMMUTABLE_TABLES = [
    "legaldocument",
    "legalact",
    "legalprovision",
    "legalprovisionversion",
    "legalchunk",
    "legalembedding",
    "legalrelationship",
]

TRIGGERS = (
    "".join(
        f"""CREATE TRIGGER {name}_immutable BEFORE UPDATE OR DELETE ON {P}{name}
            FOR EACH ROW EXECUTE FUNCTION app.immutable_row();
        """
        for name in IMMUTABLE_TABLES
    )
    + f"""
    CREATE FUNCTION app.legal_version_text_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP = 'DELETE'
           OR (to_jsonb(NEW) - 'review_status' - 'reviewed_at')
              IS DISTINCT FROM (to_jsonb(OLD) - 'review_status' - 'reviewed_at') THEN
            RAISE EXCEPTION 'legal versions are immutable' USING ERRCODE = '42501';
        END IF;
        RETURN NEW;
    END $$;
    CREATE TRIGGER legalactversion_immutable BEFORE UPDATE OR DELETE ON {P}legalactversion
        FOR EACH ROW EXECUTE FUNCTION app.legal_version_text_immutable();

    -- History of understanding: a row can only be retired once, and never rewritten.
    CREATE FUNCTION app.legal_applicability_append_only() RETURNS trigger
    LANGUAGE plpgsql AS $$
    BEGIN
        IF TG_OP = 'DELETE' OR OLD.retired_at IS NOT NULL OR NEW.retired_at IS NULL
           OR (to_jsonb(NEW) - 'retired_at') IS DISTINCT FROM (to_jsonb(OLD) - 'retired_at') THEN
            RAISE EXCEPTION 'applicability history is append-only' USING ERRCODE = '42501';
        END IF;
        RETURN NEW;
    END $$;
    CREATE TRIGGER legalapplicability_append_only BEFORE UPDATE OR DELETE
        ON {P}legalapplicability
        FOR EACH ROW EXECUTE FUNCTION app.legal_applicability_append_only();

    CREATE FUNCTION app.legal_chunk_search() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        NEW.search_vector := to_tsvector('romanian', NEW.normalized_text);
        RETURN NEW;
    END $$;
    CREATE TRIGGER legalchunk_search BEFORE INSERT ON {P}legalchunk
        FOR EACH ROW EXECUTE FUNCTION app.legal_chunk_search();

    CREATE INDEX legal_embedding_hnsw ON {P}legalembedding
        USING hnsw (embedding vector_cosine_ops);
"""
)

PORTAL_NOTE = (
    "Portal Legislativ, verificat în noiembrie 2026. Serviciul SOAP nu publică limite, condiții "
    "de utilizare sau durata tokenului. Unele acte, inclusiv Codul fiscal, vin doar cu antetul. "
    "Nu oferă forme consolidate sau istoric. Paginile de detaliu răspund cu 403 acestui client."
)
ANAF_NOTE = (
    "Flux RSS public. Canalul „legislatie” are articole doar până în 2016, deci nu semnalează "
    "legislație nouă. Se folosește canalul „comunicate”, ca îndrumare, nu ca text de lege."
)
NOT_BUILT = "Conector neimplementat. Accesul și condițiile de reutilizare nu sunt verificate."

SOURCES = [
    ("portal_legislativ", "Portal Legislativ", "https://legislatie.just.ro/", "soap", 360, 48,
     PORTAL_NOTE),
    ("anaf", "ANAF", "https://www.anaf.ro/", "rss", 180, 48, ANAF_NOTE),
    ("monitorul_oficial", "Monitorul Oficial", "https://monitoruloficial.ro/", "none", 120, 48,
     NOT_BUILT),
    ("mfinante", "Ministerul Finanțelor", "https://mfinante.gov.ro/", "none", 1440, 168, NOT_BUILT),
    ("onrc", "ONRC", "https://www.onrc.ro/", "none", 1440, 168, NOT_BUILT),
    ("eurlex", "EUR-Lex", "https://eur-lex.europa.eu/", "none", 1440, 168, NOT_BUILT),
    ("manual_official", "Import manual din documente oficiale", "", "manual", 0, 0,
     "Documente aduse de un operator, care răspunde de proveniența și datele lor."),
]


def add_sources(apps, schema_editor):
    source = apps.get_model("legal_knowledge", "LegalSource")
    for key, name, url, connector, minutes, hours, note in SOURCES:
        source.objects.create(
            key=key,
            name=name,
            official_url=url,
            connector=connector,
            schedule_minutes=minutes,
            freshness_hours=hours,
            access_restrictions=note,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_app_schema"),
        ("ai_gateway", "0002_row_level_security"),
        ("legal_knowledge", "0001_initial"),
    ]

    operations = [
        *[GrantGlobal(P + name, "SELECT") for name in READABLE],
        migrations.RunSQL(WRITER, migrations.RunSQL.noop),
        migrations.RunSQL(TRIGGERS, migrations.RunSQL.noop),
        migrations.RunPython(add_sources, migrations.RunPython.noop),
    ]
